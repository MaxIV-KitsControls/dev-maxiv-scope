"""Provide the device classes for RTM and RTO Scope devices."""

# Imports
import numpy
import socket
import operator
from Queue import Queue
from threading import Thread
from timeit import default_timer as time

# PyTango imports
import PyTango
from PyTango import DevState
from PyTango.server import device_property, command
debug_it = PyTango.DebugIt(True, True, True)

# Library imports
from rohdescope import Vxi11Exception

# Common imports
from scopedevice.common import (read_attribute, rw_attribute, mapping,
                                DeviceMeta, StopIO, partial, stamped,
                                tick_context, safe_loop, safe_traceback,
                                debug_periodic_method, event_property,
                                RequestQueueDevice)


# Generic scope device
class ScopeDevice(RequestQueueDevice):
    """Generic class for scope devices."""
    __metaclass__ = DeviceMeta

    # Attributes
    channels = range(1, 5)
    time_base_name = "TimeBase"
    waveform_names = dict((i, "Waveform" + str(i)) for i in channels)
    raw_waveform_names = dict((i, "RawWaveform" + str(i)) for i in channels)
    busy_wait = True  # Default value for busy wait attribute

    # Library
    connection_class = None

    # Settings
    update_timeout = 2.0        # Up-to-date limit for the device (informative)
    callback_timeout = 0.5      # Communication timeout set in the scope
    connection_timeout = 2.0    # Communication timeout set in the socket
    instrument_timeout = 2.0    # Communication timeout set in the library
    command_timeout = 2.0       # Timeout on the expert command ExecCommand
    update_period = 0.2         # Limit the loop frequency while updating
    acquisition_period = 0.005  # Limit loop frequency when acquiring
    events = True               # Use Tango change events for waveforms

    event_property = partial(event_property, event="events")

# ------------------------------------------------------------------
#    Thread methods
# ------------------------------------------------------------------

    @debug_it
    @safe_loop("register_exception")
    def scope_loop(self):
        """The target for the thread to access the instrument."""
        # Wait to be awaken
        self.safe_wait()
        # Not alive
        if not self.alive:
            # Disconnect the scope
            if self.connected:
                self.disconnect()
            # Break the loop
            return True
        # Get state
        state = self.get_state()
        updating = (state == DevState.ON)
        acquiring = (state == DevState.RUNNING)
        # Set period
        period = 0
        if acquiring:
            period = self.acquisition_period
        elif updating:
            period = self.update_period
        # Control loop time
        with tick_context(period):
            # Update and acquisitions
            try:
                # Update values
                if self.connected and updating:
                    self.update_all()
                # Acquire waveforms
                if self.connected and acquiring:
                    self.acquire_waveforms()
            # Handle exceptions
            except Exception as exc:
                self.handle_exception(exc)
            # Process queue
            try:
                self.process_queue()
            # Handle exceptions
            except Exception as exc:
                self.handle_exception(exc)

    @safe_loop("register_exception")
    def decoding_loop(self):
        """The target for the thread to decode the waveforms."""
        item = self.decoding_queue.get(True)
        # Check item
        if item is None:
            return True
        stamp, string = item
        # Decode waveforms
        args = self.channel_enabled, string
        data = self.scope.parse_waveform_string(*args)
        self.update_waveforms_from_data(data, stamp=stamp)
        self.update_time_base(stamp=stamp)

    @debug_periodic_method("debug_stream")
    def update_all(self):
        """Update all values."""
        self.update_scope_status()
        self.update_single_settings()
        for channel in self.channels:
            self.update_channel_settings(channel)

    def update_single_settings(self):
        """Update all the non-channel related settings."""
        self.update_time_range()
        self.update_time_position()
        self.update_record_length()
        self.update_trigger_source()
        self.update_trigger_slope()
        self.update_trigger_coupling()
        self.update_trigger_level(5)

    def update_channel_settings(self, channel):
        """Update the setting for a given channel."""
        self.update_channel_position(channel)
        self.update_channel_scale(channel)
        self.update_channel_coupling(channel)
        self.update_trigger_level(channel)
        self.update_channel_enabled(channel)

    def update_waveforms(self):
        """Update the waveforms. Currently not used."""
        data = self.scope.get_waveform_data(self.channel_enabled)
        self.update_waveforms_from_data(data)
        self.update_time_base()

    def update_waveforms_from_data(self, data, stamp=None):
        """Update the waveforms with the given raw data."""
        args = data, self.channel_scales, self.channel_positions
        waveforms = self.scope.convert_waveforms(*args)
        raw_waveforms = self.scope.convert_waveforms(data)
        for channel in self.channels:
            waveform = waveforms.get(channel, [])
            raw_waveform = raw_waveforms.get(channel, [])
            self.waveforms[channel] = stamped(waveform, stamp)
            self.raw_waveforms[channel] = stamped(raw_waveform, stamp)

    def update_time_base(self, stamp=None):
        """Compute a new time base if necessary."""
        # Get length
        gen = (len(data) for data in self.waveforms.values()
               if data is not None and len(data))
        length = next(gen, 0)
        # Get boundaries
        mean = self.time_position if self.time_position else 0.0
        half = self.time_range / 2 if self.time_range else 0.0
        start, stop = (op(mean, half) for op in (operator.sub, operator.add))
        # Update value
        args = (start, stop, length)
        if self.linspace_args != args:
            self.time_base = stamped(numpy.linspace(*args), stamp)
        # Update args attribute
        self.linspace_args = args

    @debug_periodic_method("debug_stream")
    def acquire_waveforms(self):
        """Run a single acquisition and stamp it."""
        item = self.scope.stamp_acquisition(self.channel_enabled,
                                            busy=self.busy_wait)
        self.reset_flags()
        self.decoding_queue.put(item)

# ------------------------------------------------------------------
#    Scope methods
# ------------------------------------------------------------------

    def connect(self):
        """Connect to the instrument."""
        self.scope.connect()
        self.update_identifier()
        self.reset_flags()

    def disconnect(self):
        """Disconnect from the intrument."""
        self.scope.disconnect()

    def prepare_acquisition(self):
        """Prepare the waveform acquisition."""
        self.scope.configure()
        self.reset_flags()

    def clean_acquisition(self):
        """Clean the waveform acquisition."""
        self.scope.configure()
        self.reset_flags()

    def check_connection(self):
        """Check the scope connection"""
        if not self.connected:
            return False
        self.scope.get_status()

    @property
    def connected(self):
        """Status of the connection."""
        return self.scope.connected

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
        self.status = self.scope.get_status()
        self.reset_flags()

    def reset_flags(self):
        """Reset the flags that check the status of the scope."""
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
            # Ignore when waiting for a trigger
            if self.get_state() == DevState.RUNNING or exc.note == "wait":
                self.warn_stream(safe_traceback())
                self.enqueue(self.check_connection)
                return
            # Report
            exc = "instrument is connected but not responding"
            exc += " ({0:3.1f} s)".format(self.instrument_timeout)
        # Explicit connection timeout
        elif isinstance(exc, socket.timeout):
            exc = "connection timeout"
            exc += " ({0:3.1f} s)".format(self.connection_timeout)
            exc += "\nCannot reach the hardware."
        # Register exception
        self.register_exception(exc)

    def channel_mapping(self, base, external=False):
        """Helper method to create a mapping interface."""
        channels = list(self.channels)
        if external:
            channels += [5]
        return mapping(self, base + '_', channels)

# ------------------------------------------------------------------
#    State methods
# ------------------------------------------------------------------

    def manage_state(self, state, transition=False):
        """Handle the thread depending on the current state."""
        RequestQueueDevice.manage_state(self, state, transition)
        # Start thread
        if transition and state in (DevState.ON, DevState.RUNNING):
            self.awake.set()
        # Stop thread
        if not transition and self.get_state() == DevState.STANDBY:
            self.awake.clear()
        # Terminate thread
        if not transition and self.get_state() == DevState.FAULT:
            self.alive = False
            self.awake.set()

# ------------------------------------------------------------------
#    Status methods
# ------------------------------------------------------------------

    def dev_status(self):
        """Update the status from state, instrument status and timestamp."""
        # Init state
        if self.get_state() == PyTango.DevState.INIT:
            self.result = "Initializing..."
        # Standby state
        elif self.get_state() == PyTango.DevState.STANDBY:
            self.result = "Scope disconnected."
        # Running state
        elif self.get_state() == PyTango.DevState.RUNNING:
            status = self.get_update_string()
            if not status:
                status = "Scope is acquiring..."
            self.result = status
        # Fault state
        elif self.get_state() == PyTango.DevState.FAULT:
            status = "Error: " + self.error + "\n"
            status += "Please run the Init command to reconnect." + "\n"
            status += "If the same error is raised, check the hardware state."
            self.result = status
        # On state
        else:
            status = self.get_update_string()
            if not status:
                default_status = "No status available."
                status = self.status if self.status else default_status
                status += " Up-to-date."
            self.result = status
        return self.result

    def get_update_string(self):
        delta = time() - self.stamp
        if delta < self.update_timeout:
            return ""
        running = (self.get_state() == DevState.RUNNING)
        string = ("No update", "No trigger detected")[running]
        return string + " in the last {0:.2f} seconds.".format(delta)

# ------------------------------------------------------------------
#    Initialization methods
# ------------------------------------------------------------------

    def update_attributes(self, reset=False):
        """Reload attribute values."""
        cls = type(self)
        for name in dir(cls):
            try:
                getattr(cls, name).reloader(self, reset)
            except AttributeError:
                pass

    @debug_it
    def init_device(self):
        """Initialize instance attributes and start the thread."""
        RequestQueueDevice.init_device(self)
        # Thread attribute
        self.scope_thread = Thread(target=self.scope_loop)
        self.decoding_thread = Thread(target=self.decoding_loop)
        self.decoding_queue = Queue()
        # Misc. attributes
        self.linspace_args = None
        self.waiting = False
        self.stamp = time()
        self.error = ""
        # Mapping attributes
        self.waveforms = self.channel_mapping("waveform")
        self.raw_waveforms = self.channel_mapping("raw_waveform")
        self.channel_coupling = self.channel_mapping("channel_coupling")
        self.channel_positions = self.channel_mapping("channel_position")
        self.channel_scales = self.channel_mapping("channel_scale")
        self.trigger_levels = self.channel_mapping("trigger_level", True)
        self.channel_enabled = self.channel_mapping("channel_enabled")
        # Instanciate scope
        callback_ms = int(self.callback_timeout * 1000)
        connection_ms = int(self.connection_timeout * 1000)
        instrument_ms = int(self.instrument_timeout * 1000)
        callback = self.scope_callback
        kwargs = {'host': self.Host,
                  'callback_timeout': callback_ms,
                  'connection_timeout': connection_ms,
                  'instrument_timeout': instrument_ms,
                  'callback': callback}
        self.scope = self.connection_class(**kwargs)
        # Push events
        self.update_time_base()
        # Run thread
        self.scope_thread.start()
        self.decoding_thread.start()
        # Set state
        self.set_state(PyTango.DevState.STANDBY)

    @debug_it
    def delete_device(self):
        """Try to stop the thread."""
        RequestQueueDevice.delete_device(self)
        self.stop_scope_thread()
        self.stop_decoding_thread()
        self.update_attributes(reset=True)

    def stop_scope_thread(self):
        """Stop the scope thread."""
        timeout = self.connection_timeout + self.callback_timeout
        self.debug_stream("Joining the reading thread...")
        self.scope_thread.join(timeout)
        if self.scope_thread.is_alive():
            self.error_stream("Cannot join the reading thread")

    def stop_decoding_thread(self):
        """Stop the decoding thread."""
        self.decoding_queue.put(None)
        self.debug_stream("Joining the decoding thread...")
        self.decoding_thread.join()

# ------------------------------------------------------------------
#    General attributes
# ------------------------------------------------------------------

    Host = device_property(
        dtype=str,
        doc="Host name of the scope",
        )

# ------------------------------------------------------------------
#    General attributes
# ------------------------------------------------------------------

    # Identifier

    identifier = event_property("Identifier")

    Identifier = read_attribute(
        dtype=str,
        fget=identifier.read,
        doc="Instrument identification",
    )

    def update_identifier(self):
        self.identifier = self.scope.get_identifier()

    def is_read_allowed(self, request=None):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

    def is_write_allowed(self, request=None):
        return self.get_state() in [DevState.ON, DevState.RUNNING]

    def is_read_write_allowed(self, request=None):
        if request is None or request.READ_REQ:
            return self.is_read_allowed()
        return self.is_write_allowed()

# ------------------------------------------------------------------
#    Time attributes
# ------------------------------------------------------------------

    # Time Range

    time_range = event_property("TimeRange")

    TimeRange = rw_attribute(
        dtype=float,
        label="Time range",
        unit="s",
        min_value=1e-8,
        max_value=1.0,
        format="%.1e",
        fget=time_range.read,
        doc="Horizontal time range",
    )

    def write_TimeRange(self, time_range):
        self.enqueue(self.scope.set_time_range, time_range)
        self.enqueue(self.update_time_range)

    def update_time_range(self):
        self.time_range = self.scope.get_time_range()
        self.update_time_base()

    # Time Position

    time_position = event_property("TimePosition")

    TimePosition = rw_attribute(
        dtype=float,
        label="Time position",
        unit="s",
        min_value=-1.0,
        max_value=1.0,
        format="%.1e",
        fget=time_position.read,
        doc="Horizontal time position",
    )

    def write_TimePosition(self, position):
        self.enqueue(self.scope.set_time_position, position)
        self.enqueue(self.update_time_position)

    def update_time_position(self):
        self.time_position = self.scope.get_time_position()
        self.update_time_base()

    # Record length

    record_length = event_property("RecordLength")

    RecordLength = rw_attribute(
        dtype=int,
        label="Record length",
        unit="point",
        min_value=0,
        max_value=10**8,
        format="%d",
        fget=record_length.read,
        doc="Record length for the waveforms",
    )

    def write_RecordLength(self, length):
        self.enqueue(self.scope.set_record_length, length)
        self.enqueue(self.update_record_length)

    def update_record_length(self):
        self.record_length = self.scope.get_record_length()

    # Time Base

    time_base = event_property("TimeBase")

    TimeBase = read_attribute(
        dtype=(float,),
        max_dim_x=10**8,
        label="Time base",
        unit="s",
        fget=time_base.read,
        doc="Time base value table",
    )

# ------------------------------------------------------------------
#    Channel setting attributes
# ------------------------------------------------------------------

    # Channel Enabled

    channel_enabled_1 = event_property("ChannelEnabled1")
    channel_enabled_2 = event_property("ChannelEnabled2")
    channel_enabled_3 = event_property("ChannelEnabled3")
    channel_enabled_4 = event_property("ChannelEnabled4")

    def write_channel_enabled(self, enabled, channel):
        self.enqueue(self.scope.set_channel_enabled, channel, enabled)
        self.enqueue(self.update_channel_enabled, channel)

    def update_channel_enabled(self, channel):
        enabled = self.scope.get_channel_enabled(channel)
        self.channel_enabled[channel] = enabled

    def channel_enabled_attribute(channel,
                                  attrs=[channel_enabled_1, channel_enabled_2,
                                         channel_enabled_3, channel_enabled_4],
                                  write=write_channel_enabled):
        return rw_attribute(
            dtype=bool,
            fget=attrs[channel-1].read,
            label="Channel enabled {0}".format(channel),
            doc="Channel {0} status (enabled or disabled)".format(channel),
            fset=partial(write, channel=channel))

    ChannelEnabled1 = channel_enabled_attribute(1)
    ChannelEnabled2 = channel_enabled_attribute(2)
    ChannelEnabled3 = channel_enabled_attribute(3)
    ChannelEnabled4 = channel_enabled_attribute(4)

    # Channel Coupling

    channel_coupling_1 = event_property("ChannelCoupling1")
    channel_coupling_2 = event_property("ChannelCoupling2")
    channel_coupling_3 = event_property("ChannelCoupling3")
    channel_coupling_4 = event_property("ChannelCoupling4")

    def write_channel_coupling(self, coupling, channel):
        self.enqueue(self.scope.set_channel_coupling, channel, coupling)
        self.enqueue(self.update_channel_coupling, channel)

    def update_channel_coupling(self, channel):
        coupling = self.scope.get_channel_coupling(channel)
        self.channel_coupling[channel] = coupling

    def channel_coupling_attribute(channel,
                                   attrs=[
                                       channel_coupling_1, channel_coupling_2,
                                       channel_coupling_3, channel_coupling_4],
                                   write=write_channel_coupling):
        return rw_attribute(
            dtype=int,
            min_value=0,
            max_value=3,
            fget=attrs[channel-1].read,
            label="Channel coupling {0}".format(channel),
            doc="0 for DC, 1 for AC, 2 for DCLimit, 3 for ACLimit",
            fset=partial(write, channel=channel))

    ChannelCoupling1 = channel_coupling_attribute(1)
    ChannelCoupling2 = channel_coupling_attribute(2)
    ChannelCoupling3 = channel_coupling_attribute(3)
    ChannelCoupling4 = channel_coupling_attribute(4)

    # Channel Position

    channel_position_1 = event_property("ChannelPosition1")
    channel_position_2 = event_property("ChannelPosition2")
    channel_position_3 = event_property("ChannelPosition3")
    channel_position_4 = event_property("ChannelPosition4")

    def write_channel_position(self, position, channel):
        self.enqueue(self.scope.set_channel_position, channel, position)
        self.enqueue(self.update_channel_position, channel)

    def update_channel_position(self, channel):
        position = self.scope.get_channel_position(channel)
        self.channel_positions[channel] = position

    def channel_position_attribute(channel,
                                   attrs=[
                                       channel_position_1, channel_position_2,
                                       channel_position_3, channel_position_4],
                                   write=write_channel_position):
        return rw_attribute(
            dtype=float,
            unit="div",
            format="%4.3f",
            fget=attrs[channel-1].read,
            label="Channel position {0}".format(channel),
            doc="Position for channel {0}".format(channel),
            fset=partial(write, channel=channel))

    ChannelPosition1 = channel_position_attribute(1)
    ChannelPosition2 = channel_position_attribute(2)
    ChannelPosition3 = channel_position_attribute(3)
    ChannelPosition4 = channel_position_attribute(4)

    # Channel Scale

    channel_scale_1 = event_property("ChannelScale1")
    channel_scale_2 = event_property("ChannelScale2")
    channel_scale_3 = event_property("ChannelScale3")
    channel_scale_4 = event_property("ChannelScale4")

    def write_channel_scale(self, scale, channel):
        self.enqueue(self.scope.set_channel_scale, channel, scale)
        self.enqueue(self.update_channel_scale, channel)

    def update_channel_scale(self, channel):
        scale = self.scope.get_channel_scale(channel)
        self.channel_scales[channel] = scale

    def channel_scale_attribute(channel,
                                attrs=[channel_scale_1, channel_scale_2,
                                       channel_scale_3, channel_scale_4],
                                write=write_channel_scale):
        return rw_attribute(
            dtype=float,
            unit="V/div",
            format="%4.3f",
            fget=attrs[channel-1].read,
            label="Channel scale {0}".format(channel),
            doc="Scale for channel {0}".format(channel),
            fset=partial(write, channel=channel))

    ChannelScale1 = channel_scale_attribute(1)
    ChannelScale2 = channel_scale_attribute(2)
    ChannelScale3 = channel_scale_attribute(3)
    ChannelScale4 = channel_scale_attribute(4)

# ------------------------------------------------------------------
#    Waveforms attributes
# ------------------------------------------------------------------

    # Waveforms

    waveform_1 = event_property("Waveform1")
    waveform_2 = event_property("Waveform2")
    waveform_3 = event_property("Waveform3")
    waveform_4 = event_property("Waveform4")

    def waveform_attribute(channel,
                           attrs=[waveform_1, waveform_2,
                                  waveform_3, waveform_4]):
        return read_attribute(
            dtype=(float,),
            unit="V",
            format="%4.3f",
            max_dim_x=10**8,
            fget=attrs[channel-1].read,
            label="Waveform {0}".format(channel),
            doc="Waveform data for channel {0}".format(channel))

    Waveform1 = waveform_attribute(1)
    Waveform2 = waveform_attribute(2)
    Waveform3 = waveform_attribute(3)
    Waveform4 = waveform_attribute(4)

    # Raw waveforms

    raw_waveform_1 = event_property("RawWaveform1")
    raw_waveform_2 = event_property("RawWaveform2")
    raw_waveform_3 = event_property("RawWaveform3")
    raw_waveform_4 = event_property("RawWaveform4")

    def raw_waveform_attribute(channel,
                               attrs=[raw_waveform_1, raw_waveform_2,
                                      raw_waveform_3, raw_waveform_4]):
        return read_attribute(
            dtype=(float,),
            unit="div",
            format="%4.3f",
            max_dim_x=10**8,
            fget=attrs[channel-1].read,
            label="Waveform {0}".format(channel),
            doc="Waveform data for channel {0}".format(channel))

    RawWaveform1 = raw_waveform_attribute(1)
    RawWaveform2 = raw_waveform_attribute(2)
    RawWaveform3 = raw_waveform_attribute(3)
    RawWaveform4 = raw_waveform_attribute(4)

# ------------------------------------------------------------------
#    Trigger attributes
# ------------------------------------------------------------------

    # Trigger levels

    trigger_level_1 = event_property("TriggerLevel1")
    trigger_level_2 = event_property("TriggerLevel2")
    trigger_level_3 = event_property("TriggerLevel3")
    trigger_level_4 = event_property("TriggerLevel4")
    trigger_level_5 = event_property("TriggerLevel5")

    def write_trigger_level(self, level, channel):
        self.enqueue(self.scope.set_trigger_level, channel, level)
        self.enqueue(self.update_trigger_level, channel)

    def update_trigger_level(self, channel):
        level = self.scope.get_trigger_level(channel)
        self.trigger_levels[channel] = level

    def level_attribute(channel,
                        attrs=[trigger_level_1, trigger_level_2,
                               trigger_level_3, trigger_level_4,
                               trigger_level_5],
                        write=write_trigger_level):
        return rw_attribute(
            dtype=float,
            unit="V",
            format="%4.3f",
            fget=attrs[channel-1].read,
            label="Trigger level {0}".format(channel),
            doc="Position for channel {0}".format(channel),
            fset=partial(write, channel=channel))

    TriggerLevel1 = level_attribute(1)
    TriggerLevel2 = level_attribute(2)
    TriggerLevel3 = level_attribute(3)
    TriggerLevel4 = level_attribute(4)
    TriggerLevel5 = level_attribute(5)

    # Trigger slope

    trigger_slope = event_property("TriggerSlope")

    TriggerSlope = rw_attribute(
        dtype=int,
        min_value=0,
        max_value=2,
        format="%1d",
        label="Trigger slope",
        fget=trigger_slope.read,
        doc="0 for negative, 1 for positive, 2 for either",
    )

    def write_TriggerSlope(self, slope):
        self.enqueue(self.scope.set_trigger_slope, slope)
        self.enqueue(self.update_trigger_slope)

    def update_trigger_slope(self):
        self.trigger_slope = self.scope.get_trigger_slope()

    # Trigger source

    trigger_source = event_property("TriggerSource")

    TriggerSource = rw_attribute(
        dtype=int,
        min_value=1,
        max_value=5,
        format="%1d",
        label="Trigger source",
        fget=trigger_source.read,
        doc="Channel 1 to 4, or 5 for external trigger",
    )

    def read_TriggerSource(self):
        return self.trigger_source

    def write_TriggerSource(self, source):
        self.enqueue(self.scope.set_trigger_source, source)
        self.enqueue(self.update_trigger_source)

    def update_trigger_source(self):
        self.trigger_source = self.scope.get_trigger_source()

    # Trigger Coupling

    trigger_coupling = event_property("TriggerCoupling")

    TriggerCoupling = rw_attribute(
        dtype=int,
        min_value=0,
        max_value=2,
        label="Trigger coupling",
        fget=trigger_coupling.read,
        doc="0 for DC, 1 for AC, 2 for HF",
    )

    def write_TriggerCoupling(self, coupling):
        self.enqueue(self.scope.set_trigger_coupling, coupling)
        self.enqueue(self.update_trigger_coupling)

    def update_trigger_coupling(self):
        self.trigger_coupling = self.scope.get_trigger_coupling()

# ------------------------------------------------------------------
#    Commands
# ------------------------------------------------------------------

    # Run command

    @command
    def Run(self):
        """Run the acquisition. Available in ON state."""
        self.enqueue_transition(DevState.ON, DevState.RUNNING,
                                self.prepare_acquisition)

    def is_Run_allowed(self):
        return self.steady_state(DevState.ON)

    # Stop command

    @command
    def Stop(self):
        """Stop the acquisition. Available in RUNNING state."""
        self.enqueue_transition(DevState.RUNNING, DevState.ON,
                                self.clean_acquisition)

    def is_Stop_allowed(self):
        return self.steady_state(DevState.RUNNING)

    # On command

    @command
    def On(self):
        """Connect to the scope. Available in STANDBY state."""
        self.enqueue_transition(DevState.STANDBY, DevState.ON,
                                self.connect)

    def is_On_allowed(self):
        return self.steady_state(DevState.STANDBY)

    # Standby command

    @command
    def Standby(self):
        """Disconnect from the scope. Available in STANDBY state."""
        self.enqueue_transition(DevState.ON, DevState.STANDBY,
                                self.disconnect)

    def is_Standby_allowed(self):
        return self.steady_state(DevState.ON)

    # Execute command

    @command(
        dtype_in=(str,),
        doc_in="Execute aribtrary command",
        dtype_out=str,
        doc_out="Returns the reply if a query,"
        "else DONE if suceeds, else TIMEOUT"
    )
    def Execute(self, command):
        """Execute a custom command. Available in ON and RUNNING state."""
        command = " ".join(command)
        # Check report queue
        if self.report_queue:
            msg = "A command is already being executed"
            raise RuntimeError(msg)
        # Set state
        self.events = False
        self.waiting = True
        # Equeue command
        self.enqueue(self.scope.issue_command, command, report=True)
        # Handle command timeout
        start = time()
        while time() - start < self.command_timeout:
            # Apply a minimal period
            with tick_context(self.update_period):
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
        self.events = ScopeDevice.events
        # Return
        return str(result)

    def is_Execute_allowed(self):
        return (self.steady_state(DevState.ON) or
                self.steady_state(DevState.RUNNING))
