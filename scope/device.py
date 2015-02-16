"""Provide the device classes for RTM and RTO Scope devices."""

# Imports
import numpy
import socket
import operator
from threading import Thread
from functools import partial
from timeit import default_timer as time
from collections import deque, defaultdict

# PyTango imports
import PyTango
from PyTango import DevState
from PyTango.server import command, Device
debug_it = PyTango.DebugIt(True, True, True)

# Library imports
from vxi11 import Vxi11Exception
from rohdeschwarzrtmlib import RohdeSchwarzRTMConnection
from rohdeschwarzrtolib import RohdeSchwarzRTOConnection

# Common imports
from scope.common import DeviceMeta, StopIO
from scope.common import read_attribute, rw_attribute
from scope.common import tick_context, safe_loop, safe_traceback


# Generic scope device
class Scope(Device):
    """Generic class for scope devices."""
    __metaclass__ = DeviceMeta

    # Attributes
    channels = range(1, 5)
    time_base_name = "TimeBase"
    waveform_names = dict((i, "Waveform" + str(i)) for i in channels)
    raw_waveform_names = dict((i, "RawWaveform" + str(i)) for i in channels)

    # Library
    connection_class = None

    # Settings
    update_timeout = 3.0      # Up-to-date limit for the device (informative)
    callback_timeout = 0.5    # Communication timeout set in the scope
    connection_timeout = 2.0  # Communication timeout set in the socket
    instrument_timeout = 5.0  # Communication timeout set in the library
    command_timeout = 2.0     # Timeout on the expert command ExecCommand
    minimal_period = 0.002    # Limit the acquiring loop frequency
    events = True             # Use Tango change events

# ------------------------------------------------------------------
#    Thread methods
# ------------------------------------------------------------------

    @debug_it
    @safe_loop("register_exception")
    def scope_loop(self):
        """The target for the thread to access the instrument."""
        # Wait to be awaken
        self.awake.wait()
        # Not alive
        if not self.alive:
            self.close_connection()
            # Break the loop
            return True
        # Catch all exceptions
        try:
            # Connect to the scope
            self.check_connection()
            # Acquire waveforms
            if self.get_state() == DevState.RUNNING:
                self.acquire_waveforms()
            # Update values
            elif self.get_state() == DevState.ON:
                self.update_all()
            # Process queue
            self.process_queue()
            # Handle exception
        except Exception as exc:
            self.handle_exception(exc)

    def check_connection(self):
        """Try to connect to the instrument if not connected."""
        # Not connected
        if not self.connected:
            # Try to connect
            self.scope.connect()
            self.update_identifier()
            # Configure the scope
            self.scope.write('*CLS')
            self.scope.set_binary_readout()
        # Status
        self.update_scope_status()

    def update_all(self):
        """Update all values."""
        self.update_single_settings()
        for channel in self.channels:
            self.update_channel_settings(channel)
        self.update_waveforms()

    def update_single_settings(self):
        """Update all the non-channel related settings."""
        self.update_time_range()
        self.update_time_position()
        self.update_trigger_source()
        self.update_trigger_slope()
        self.update_trigger_level(5)

    def update_channel_settings(self, channel):
        """Update the setting for a given channel."""
        self.update_channel_position(channel)
        self.update_channel_scale(channel)
        self.update_channel_coupling(channel)
        self.update_trigger_level(channel)
        self.update_channel_enabled(channel)

    def update_waveforms(self):
        """Update the waveforms."""
        result = self.scope.get_waveforms(both=True)
        self.waveforms, self.raw_waveforms = result
        self.update_time_base()
        self.push_channel_events()

    def update_time_base(self):
        """Compute a new time base if necessary."""
        # Get length
        gen = (len(data) for data in self.waveforms.values() if len(data))
        length = next(gen, 0)
        # Get boundaries
        mean, half = self.time_position, self.time_range/2
        start, stop = (op(mean, half) for op in (operator.sub, operator.add))
        # Update value
        args = (start, stop, length)
        if self.linspace_args != args:
            self.time_base = numpy.linspace(*args)
            self.push_time_base_event()
        # Update args attribute
        self.linspace_args = args

# ------------------------------------------------------------------
#    Misc. methods
# ------------------------------------------------------------------

    def scope_callback(self, exc):
        """Callback to terminate the thread quickly."""
        # Stop the thread
        if not self.alive:
            msg = "Stopping the thread..."
            raise StopIO(msg)
        # Stop reporting
        if exc and self.reporting and not self.waiting:
            msg = "Stop reporting..."
            raise StopIO(msg)

    def update_scope_status(self):
        """Update instrument status and time stamp"""
        self.status = self.scope.getOperCond()
        self.state_queue.append(self.scope.getState())
        self.warning = False
        self.stamp = time()

    @debug_it
    def handle_exception(self, exc):
        """Process an exception raised during the thread execution."""
        # Ignore StopReporting and StopAcquiring exception
        if isinstance(exc, StopIO):
            self.warn_stream(str(exc))
            return
        # Explicit instrument timeout
        if isinstance(exc, Vxi11Exception) and exc.err == 15:
            # Ignore the first one
            if not self.warning:
                self.warning = True
                self.warn_stream(safe_traceback())
                return
            # Report when two in a row
            exc = "instrument is connected but not responding."
            exc += "\nTwo consecutive instrument timeouts"
            exc += " (2 x {0:3.1f} s)".format(self.instrument_timeout)
        # Explicit connection timeout
        elif isinstance(exc, socket.timeout):
            exc = "connection timeout"
            exc += " ({0:3.1f} s)".format(self.connection_timeout)
            exc += "\nCannot reach the hardware."
        # Register exception
        self.register_exception(exc)

    @debug_it
    def register_exception(self, exc):
        """Register the error and stop the thread."""
        try:
            self.error = str(exc) if str(exc) else repr(exc)
        except:
            self.error = "unexpected error"
        try:
            self.error_stream(safe_traceback())
        except:
            self.error_stream("Cannot log traceback.")
        self.alive = False

    @debug_it
    def close_connection(self):
        """Close the connection with the instrument."""
        self.scope.close()

    @property
    def connected(self):
        """Status of the connection."""
        return self.scope.connected

# ------------------------------------------------------------------
#    Queue methods
# ------------------------------------------------------------------

    def enqueue(self, func, *args, **kwargs):
        """Enqueue a task to be process by the thread."""
        report = kwargs.pop('report', False)
        item = func, args, kwargs, report
        try:
            append = (item != self.request_queue[-1])
        except IndexError:
            append = True
        if append:
            self.request_queue.append(item)

    def process_queue(self):
        """Process all tasks in the queue."""
        while self.request_queue:
            # Get item
            try:
                item = self.request_queue[0]
            except IndexError:
                break
            # Unpack item
            func, args, kwargs, self.reporting = item
            # Process item
            try:
                result = func(*args, **kwargs)
                if self.reporting:
                    self.report_queue.append(result)
            # Remove item
            finally:
                self.reporting = False
                self.request_queue.popleft()

# ------------------------------------------------------------------
#    Event methods
# ------------------------------------------------------------------

    def push_channel_events(self, channels=channels):
        """Push the TANGO change events for the given channels."""
        if self.events:
            for channel in channels:
                name = self.waveform_names[channel]
                data = self.waveform_data[channel]
                self.push_change_event(name, data)

    def push_time_base_event(self):
        """Push the TANGO change event for the time base."""
        if self.events:
            self.push_change_event(self.time_base_name, self.time_base)

    def setup_events(self):
        """Setup events for waveforms and timescale."""
        if self.events:
            for name in self.waveform_names.values():
                self.set_change_event(name, True, True)
            self.set_change_event(self.time_base_name, True, False)

# ------------------------------------------------------------------
#    Update methods
# ------------------------------------------------------------------

    def always_executed_hook(self):
        """Update state and status."""
        self.update_state()
        self.update_status()

    def update_status(self):
        """Update the status from state, instrument status and timestamp."""
        # Init state
        if self.get_state() == PyTango.DevState.INIT:
            self.set_status("Initializing...")
            return
        # Fault state
        if self.get_state() == PyTango.DevState.FAULT:
            string = "Error: " + self.error + "\n"
            string += "Please run the Init command to reconnect." + "\n"
            string += "If the same error is raised, check the hardware state."
            self.set_status(string)
            return
        # Status
        default_status = "No status available."
        status_string = self.status if self.status else default_status
        # Update
        delta = time() - self.stamp
        if delta > self.update_timeout:
            update_string = "Last update {0:.2f} seconds ago.".format(delta)
        else:
            update_string = "Up-to-date."
        self.set_status(status_string + ' ' + update_string)

    def update_state(self):
        """Update the state from connection status, errors and timeout."""
        # Fault state
        if self.error:
            self.set_state(PyTango.DevState.FAULT)
            return
        # Init state
        if self.get_state() != PyTango.DevState.INIT and self.connected:
            self.set_state(DevState.STANDBY)
            return

# ------------------------------------------------------------------
#    Initialization methods
# ------------------------------------------------------------------

    def __init__(self, cl, name):
        """Initialize the device and manage events."""
        PyTango.Device_4Impl.__init__(self, cl, name)
        self.setup_events()
        self.init_device()
        self.push_channel_events(self.channels)

    @debug_it
    def init_device(self):
        """Initialize instance attributes and start the thread."""
        self.get_device_properties()
        self.set_state(PyTango.DevState.INIT)

        # Thread attribute
        self.scope_thread = Thread(target=self.scope_loop)
        self.stamp = time()
        self.request_queue = deque()
        self.report_queue = deque(maxlen=1)
        self.linspace_args = None
        self.alive = True
        self.error = ""
        self.warning = False
        self.reporting = False
        self.waiting = False

        # Instanciate instrument
        callback_ms = int(self.callback_timeout * 1000)
        connection_ms = int(self.connection_timeout * 1000)
        instrument_ms = int(self.instrument_timeout * 1000)
        callback = self.scope_callback
        kwargs = {'host': self.Instrument,
                  'callback_timeout': callback_ms,
                  'connection_timeout': connection_ms,
                  'instrument_timeout': instrument_ms,
                  'callback': callback}
        self.scope = self.connection_class(**kwargs)

        # Instrument attributes
        self.identifier = "unknown"
        self.status = ""
        self.time_scale = []
        self.time_position = 0.0
        self.time_range = 0.0
        self.trigger_channel = 0
        self.trigger_slope = 0
        self.waveform = defaultdict(list)
        self.coupling = defaultdict(str)
        self.vpositions = defaultdict(float)
        self.vranges = defaultdict(float)
        self.levels = defaultdict(int)
        self.active_channels = defaultdict(bool)

        # Push events
        self.update_time_scale()
        self.push_channel_events()

        # Run thread
        self.scope_thread.start()

    @debug_it
    def delete_device(self):
        """Try to stop the thread."""
        self.alive = False
        if self.scope_thread.is_alive():
            timeout = self.connection_timeout + self.callback_timeout
            self.scope_thread.join(timeout)
        if self.scope_thread.is_alive():
            self.error_stream("Cannot join the reading thread")

# ------------------------------------------------------------------
#    General attributes
# ------------------------------------------------------------------

    # Identifier

    Identifier = read_attribute(
        dtype=str,
        doc="Instrument identification",
    )

    def read_Identifier(self):
        return self.identifier

    def update_identifier(self):
        self.identifier = self.scope.get_identifier()

# ------------------------------------------------------------------
#    Time attributes
# ------------------------------------------------------------------

    # Time Range

    TimeRange = rw_attribute(
        dtype=float,
        label="Time range",
        unit="s",
        min_value=1e-8,
        max_value=1.0,
        format="%.1e",
        doc="Horizontal time range",
    )

    def read_TimeRange(self):
        return self.time_range

    def write_TimeRange(self, time_range):
        self.enqueue(self.scope.set_time_range, time_range)
        self.enqueue(self.update_time_range)

    def update_time_range(self):
        self.time_range = self.scope.get_time_range()

    # Time Position

    TimePosition = rw_attribute(
        dtype=float,
        label="Time position",
        unit="s",
        min_value=-1.0,
        max_value=1.0,
        format="%.1e",
        doc="Horizontal time position",
    )

    def read_TimePosition(self):
        return self.time_position

    def write_TimePosition(self, position):
        self.enqueue(self.scope.set_time_position, position)
        self.enqueue(self.update_time_position)

    def update_time_position(self):
        self.time_position = self.scope.get_time_position()

    # Time Base

    TimeBase = read_attribute(
        dtype=(float,),
        max_dim_x=10000,
        label="Time base",
        unit="s",
        doc="Time base value table",
    )

    def read_TimeBase(self):
        return self.time_base

# ------------------------------------------------------------------
#    Channel settings
# ------------------------------------------------------------------

    # Channel Enabled

    channel_enabled_attribute = lambda channel: rw_attribute(
        dtype=bool,
        label="Channel enabled {0}".format(channel),
        doc="Channel {0} status (enabled or disabled)".format(channel),
    )

    def read_channel_enabled(self, channel):
        return self.channel_enabled[channel]

    def write_channel_enabled(self, enabled, channel):
        self.enqueue(self.scope.set_channel_enabled, channel, enabled)
        self.enqueue(self.update_channel_enabled, channel)

    def update_channel_enabled(self, channel):
        self.channel_enabled = self.scope.get_channel_enabled(channel)

    ChannelEnabled1 = channel_enabled_attribute(1)
    read_ChannelEnabled1 = partial(read_channel_enabled, channel=1)
    write_ChannelEnabled1 = partial(write_channel_enabled, channel=1)

    ChannelEnabled2 = channel_enabled_attribute(2)
    read_ChannelEnabled2 = partial(read_channel_enabled, channel=2)
    write_ChannelEnabled2 = partial(write_channel_enabled, channel=2)

    ChannelEnabled3 = channel_enabled_attribute(3)
    read_ChannelEnabled3 = partial(read_channel_enabled, channel=3)
    write_ChannelEnabled3 = partial(write_channel_enabled, channel=3)

    ChannelEnabled4 = channel_enabled_attribute(4)
    read_ChannelEnabled4 = partial(read_channel_enabled, channel=4)
    write_ChannelEnabled4 = partial(write_channel_enabled, channel=4)

    # Channel Coupling

    channel_coupling_attribute = lambda channel: rw_attribute(
        dtype=str,
        label="Channel coupling {0}".format(channel),
        doc="Coupling for channel {0}".format(channel),
    )

    def read_channel_coupling(self, channel):
        return self.channel_coupling[channel]

    def write_channel_coupling(self, coupling, channel):
        self.enqueue(self.scope.set_channel_coupling, channel, coupling)
        self.enqueue(self.update_channel_coupling, channel)

    def update_channel_channel_coupling(self, channel):
        self.channel_coupling = self.scope.get_channel_coupling(channel)

    ChannelCoupling1 = channel_coupling_attribute(1)
    read_ChannelCoupling1 = partial(read_channel_coupling, channel=1)
    write_ChannelCoupling1 = partial(write_channel_coupling, channel=1)

    ChannelCoupling2 = channel_coupling_attribute(2)
    read_ChannelCoupling2 = partial(read_channel_coupling, channel=2)
    write_ChannelCoupling2 = partial(write_channel_coupling, channel=2)

    ChannelCoupling3 = channel_coupling_attribute(3)
    read_ChannelCoupling3 = partial(read_channel_coupling, channel=3)
    write_ChannelCoupling3 = partial(write_channel_coupling, channel=3)

    ChannelCoupling4 = channel_coupling_attribute(4)
    read_ChannelCoupling4 = partial(read_channel_coupling, channel=4)
    write_ChannelCoupling4 = partial(write_channel_coupling, channel=4)

    # Channel Position

    channel_position_attribute = lambda channel: rw_attribute(
        dtype=float,
        unit="V",
        format="%4.3f",
        label="Channel position {0}".format(channel),
        doc="Position for channel {0}".format(channel),
    )

    def read_channel_position(self, channel):
        return self.channel_positions[channel]

    def write_channel_position(self, position, channel):
        self.enqueue(self.scope.set_channel_position, channel, position)
        self.enqueue(self.update_channel_position, channel)

    def update_channel_position(self, channel):
        self.channel_position = self.scope.get_channel_position(channel)

    ChannelPosition1 = channel_position_attribute(1)
    read_ChannelPosition1 = partial(read_channel_position, channel=1)
    write_ChannelPosition1 = partial(write_channel_position, channel=1)

    ChannelPosition2 = channel_position_attribute(2)
    read_ChannelPosition2 = partial(read_channel_position, channel=2)
    write_ChannelPosition2 = partial(write_channel_position, channel=2)

    ChannelPosition3 = channel_position_attribute(3)
    read_ChannelPosition3 = partial(read_channel_position, channel=3)
    write_ChannelPosition3 = partial(write_channel_position, channel=3)

    ChannelPosition4 = channel_position_attribute(4)
    read_ChannelPosition4 = partial(read_channel_position, channel=4)
    write_ChannelPosition4 = partial(write_channel_position, channel=4)

    # Channel Scale

    channel_scale_attribute = lambda channel: rw_attribute(
        dtype=float,
        unit="V/div",
        format="%4.3f",
        label="Channel scale {0}".format(channel),
        doc="Scale for channel {0}".format(channel),
    )

    def read_channel_scale(self, channel):
        return self.channel_scales[channel]

    def write_channel_scale(self, scale, channel):
        self.enqueue(self.scope.set_channel_scale, channel, scale)
        self.enqueue(self.update_channel_position, channel)

    def update_channel_scale(self, channel):
        self.channel_scale = self.scope.get_channel_scale(channel)

    ChannelScale1 = channel_scale_attribute(1)
    read_ChannelScale1 = partial(read_channel_scale, channel=1)
    write_ChannelScale1 = partial(write_channel_scale, channel=1)

    ChannelScale2 = channel_scale_attribute(2)
    read_ChannelScale2 = partial(read_channel_scale, channel=2)
    write_ChannelScale2 = partial(write_channel_scale, channel=2)

    ChannelScale3 = channel_scale_attribute(3)
    read_ChannelScale3 = partial(read_channel_scale, channel=3)
    write_ChannelScale3 = partial(write_channel_scale, channel=3)

    ChannelScale4 = channel_scale_attribute(4)
    read_ChannelScale4 = partial(read_channel_scale, channel=4)
    write_ChannelScale4 = partial(write_channel_scale, channel=4)

# ------------------------------------------------------------------
#    Waveforms
# ------------------------------------------------------------------

    # Waveforms

    waveform_attribute = lambda channel: read_attribute(
        dtype=(float),
        unit="V",
        format="%4.3f",
        max_dim_x=10000,
        label="Waveform {0}".format(channel),
        doc="Waveform data for channel {0}".format(channel),
    )

    def read_waveform(self, channel):
        return self.waveforms[channel]

    Waveform1 = waveform_attribute(1)
    read_Waveform1 = partial(read_waveform, channel=1)

    Waveform2 = waveform_attribute(2)
    read_Waveform2 = partial(read_waveform, channel=2)

    Waveform3 = waveform_attribute(3)
    read_Waveform3 = partial(read_waveform, channel=3)

    Waveform4 = waveform_attribute(4)
    read_Waveform4 = partial(read_waveform, channel=4)

    # Raw waveforms

    raw_waveform_attribute = lambda channel: read_attribute(
        dtype=(float),
        unit="div",
        format="%4.3f",
        max_dim_x=10000,
        label="Waveform {0}".format(channel),
        doc="Waveform data for channel {0}".format(channel),
    )

    def read_raw_waveform(self, channel):
        return self.raw_waveforms[channel]

    RawWaveform1 = raw_waveform_attribute(1)
    read_RawWaveform1 = partial(read_raw_waveform, channel=1)

    RawWaveform2 = raw_waveform_attribute(2)
    read_RawWaveform2 = partial(read_raw_waveform, channel=2)

    RawWaveform3 = raw_waveform_attribute(3)
    read_RawWaveform3 = partial(read_raw_waveform, channel=3)

    RawWaveform4 = raw_waveform_attribute(4)
    read_RawWaveform4 = partial(read_raw_waveform, channel=4)

# ------------------------------------------------------------------
#    Trigger related attributes
# ------------------------------------------------------------------

    # Trigger levels

    level_attribute = lambda channel: rw_attribute(
        dtype=float,
        unit="V",
        format="%4.3f",
        label="Trigger level {0}".format(channel),
        doc="Position for channel {0}".format(channel),
    )

    def read_level(self, channel):
        return self.trigger_levels[channel]

    def write_level(self, level, channel):
        self.enqueue(self.scope.set_trigger_level, channel, level)
        self.enqueue(self.update_trigger_level, channel)

    def update_trigger_level(self, channel):
        self.trigger_level = self.scope.get_trigger_level(channel)

    TriggerLevel1 = level_attribute(1)
    read_TriggerLevel1 = partial(read_level, channel=1)
    write_TriggerLevel1 = partial(write_level, channel=1)

    TriggerLevel2 = level_attribute(2)
    read_TriggerLevel2 = partial(read_level, channel=2)
    write_TriggerLevel2 = partial(write_level, channel=2)

    TriggerLevel3 = level_attribute(3)
    read_TriggerLevel3 = partial(read_level, channel=3)
    write_TriggerLevel3 = partial(write_level, channel=3)

    TriggerLevel4 = level_attribute(4)
    read_TriggerLevel4 = partial(read_level, channel=4)
    write_TriggerLevel4 = partial(write_level, channel=4)

    # Trigger slope

    TriggerSlope = rw_attribute(
        dtype=int,
        min_value=0,
        max_value=2,
        format="%1d",
        label="Trigger slope",
        doc="0 for negative, 1 for positive, 2 for either",
    )

    def read_TriggerSlope(self):
        return self.trigger_slope

    def write_TriggerSlope(self, slope):
        self.enqueue(self.scope.set_trigger_slope, slope)
        self.enqueue(self.update_trigger_slope)

    def update_trigger_slope(self):
        self.trigger_slope = self.scope.get_trigger_slope()

    # Trigger source

    TriggerSource = rw_attribute(
        dtype=int,
        min_value=1,
        max_value=5,
        format="%1d",
        label="Trigger source",
        doc="Channel 1 to 4, or 5 for external trigger",
    )

    def read_TriggerSource(self):
        return self.trigger_source

    def write_TriggerSource(self, source):
        self.enqueue(self.scope.set_trigger_source, source)
        self.enqueue(self.update_trigger_source)

    def update_trigger_source(self):
        self.trigger_source = self.scope.get_trigger_source()

# ------------------------------------------------------------------
#    Commands
# ------------------------------------------------------------------

    # Run command

    @command
    def Run(self):
        self.set_state(DevState.RUNNING)

    def is_Run_allowed(self):
        return self.get_state() == DevState.STANDBY

    # Stop command

    @command
    def Stop(self):
        self.set_state(DevState.ON)

    def is_Stop_allowed(self):
        return self.get_state() == DevState.RUNNING

    # On command

    @command
    def On(self):
        self.set_state(DevState.ON)

    def is_On_allowed(self):
        return self.get_state() == DevState.STANDBY

    # Standby command

    @command
    def Standby(self):
        self.set_state(DevState.STANDBY)

    def is_Standby_allowed(self):
        return self.get_state() == DevState.ON

    # Autoset

    @command
    def Autoset(self):
        self.enqueue(self.scope.issueAutoset)

    def is_Autoset_allowed(self):
        return self.get_state() in [DevState.ON, DevState.RUNNING]

    # Execute command

    @command(
        dtype_in=(str,),
        doc_in="Execute aribtrary command",
        dtype_out=(str,),
        doc_out="Returns the reply if a query,"
        "else DONE if suceeds, else TIMEOUT"
    )
    def Execute(self, argin):
        # Check report queue
        if self.report_queue:
            msg = "A command is already being executed"
            raise RuntimeError(msg)
        # Set state
        self.events = False
        self.waiting = True
        # Equeue command
        command = " ".join(argin)
        self.enqueue(self.scope.issueCommand, command, report=True)
        # Handle command timeout
        start = time()
        while time() - start < self.command_timeout:
            # Apply a minimal period
            with tick_context(self.minimal_period):
                # Try to get the report
                try:
                    result = self.report_queue.pop()
                    break
                # Wait for the report
                except IndexError:
                    continue
        # Timeout case
        else:
            result = "No response from the scope"
            result += " (timeout = {0:3.1f} s)".format(self.command_timeout)
        # Restore state
        self.waiting = False
        self.events = Scope.events
        # Return
        return result

    def is_ExecCommand_allowed(self):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]


# RTO scope device
class RTOScope(Device):
    """RTO scope device."""
    __metaclass__ = DeviceMeta

    # Library
    instrument_class = RohdeSchwarzRTOConnection


# Generic scope device
class RTMScope(Device):
    """RTM scope device."""
    __metaclass__ = DeviceMeta

    # Library
    connection_class = RohdeSchwarzRTMConnection
