"""Provide the device classes for RTM and RTO Scope devices."""

# Imports
import numpy
import socket
from threading import Thread
from timeit import default_timer as time
from collections import deque, defaultdict

# PyTango imports
import PyTango
from PyTango import DevState, AttrWriteType
from PyTango.server import command, attribute, Device
debug_it = PyTango.DebugIt(True, True, True)

# Library imports
from vxi11 import Vxi11Exception
from rohdeschwarzrtmlib import RohdeSchwarzRTMConnection
from rohdeschwarzrtolib import RohdeSchwarzRTOConnection

# Common imports
from scope.common import DeviceMeta, StopIO
from scope.common import tick_context, safe_method, safe_traceback


# Generic scope device
class Scope(Device):
    """Generic class for scope devices."""
    __metaclass__ = DeviceMeta

    # Attributes
    channels = range(1, 5)
    waveform_names = dict((i, "WaveformDataCh{0}".format(i)) for i in channels)

    # Library
    intrument_class = None

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
    @safe_method("_register_exception")
    def _instrument_loop(self):
        """The target for the thread to access the instrument."""
        # Main loop
        while self._alive:
            # Catch all exceptions
            try:
                # Time control
                with tick_context(self.minimal_period):
                    # Instrument access
                    self._check_connection()
                    self._update_values()
                    self._process_queue()
            # Handle exception
            except Exception as exc:
                self._handle_exception(exc)
        # Close the connection
        self._close_connection()

    def _check_connection(self):
        """Try to connect to the instrument if not connected."""
        # Not connected
        if not self._connected:
            # Try to connect
            self._instrument.connect()
            self._idn = self._instrument.getIDN()
            # Configure the scope
            self._instrument.setBinaryReadout()
        # Status
        self._update_instrument_status()

    def _update_values(self):
        """Get data and waveforms from the instrument."""
        # Rotate channels
        i = self._rotate[0]
        self._rotate.rotate(1)
        # Single data
        if i == 0:
            self._instrument.write('*CLS')
            self._hrange = self._instrument.getHRange()
            self._hposition = self._instrument.getHPosition()
            self._trigger_channel = self._instrument.getTriggerChannel()
            self._trigger_slope = self._instrument.getTriggerSlope()
            self._levels[5] = self._instrument.getTriggerLevel(5)
        # Channel data
        else:
            self._vpositions[i] = self._instrument.getVPosition(i)
            self._vranges[i] = self._instrument.getVRange(i)
            self._coupling[i] = self._instrument.getCoupling(i)
            self._levels[i] = self._instrument.getTriggerLevel(i)
            self._active_channels[i] = self._instrument.getChanState(i)
        # Waveforms
        self._waveform_data = self._instrument.acquire()
        # Push events
        self._update_time_scale()
        self._push_channel_events()

    def _update_time_scale(self):
        """Compute a new time scale if necessary."""
        # Get args
        gen = (len(data) for data in self._waveform_data.values() if len(data))
        length = next(gen, 0)
        start = self._hposition - self._hrange / 2
        stop = self._hposition + self._hrange / 2
        args = (start, stop, length)
        # Update value
        if self._linspace_args != args:
            self._time_scale = numpy.linspace(*args)
            self._push_time_scale_event()
        # Update args attribute
        self._linspace_args = args

# ------------------------------------------------------------------
#    Misc. methods
# ------------------------------------------------------------------

    def _instrument_callback(self, exc):
        """Callback to terminate the thread quickly."""
        # Stop the thread
        if not self._alive:
            msg = "Stopping the thread..."
            raise StopIO(msg)
        # Stop reporting
        if exc and self._reporting and not self._waiting:
            msg = "Stop reporting..."
            raise StopIO(msg)

    def _update_instrument_status(self):
        """Update instrument status and time stamp"""
        self._status = self._instrument.getOperCond()
        self._state_queue.append(self._instrument.getState())
        self._warning = False
        self._stamp = time()

    @debug_it
    def _handle_exception(self, exc):
        """Process an exception raised during the thread execution."""
        # Ignore StopReporting and StopAcquiring exception
        if isinstance(exc, StopIO):
            self.warn_stream(str(exc))
            return
        # Explicit instrument timeout
        if isinstance(exc, Vxi11Exception) and exc.err == 15:
            # Ignore the first one
            if not self._warning:
                self._warning = True
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
        self._register_exception(exc)

    @debug_it
    def _register_exception(self, exc):
        """Register the error and stop the thread."""
        try:
            self._error = str(exc) if str(exc) else repr(exc)
        except:
            self._error = "unexpected error"
        try:
            self.error_stream(safe_traceback())
        except:
            self.error_stream("Cannot log traceback.")
        self._alive = False

    @debug_it
    def _close_connection(self):
        """Close the connection with the instrument."""
        self._instrument.close()

    @property
    def _connected(self):
        """Status of the connection."""
        return self._instrument.connected

# ------------------------------------------------------------------
#    Queue methods
# ------------------------------------------------------------------

    def _enqueue(self, func, *args, **kwargs):
        """Enqueue a task to be process by the thread."""
        report = kwargs.pop('report', False)
        item = func, args, kwargs, report
        try:
            append = (item != self._request_queue[-1])
        except IndexError:
            append = True
        if append:
            self._request_queue.append(item)

    def _process_queue(self):
        """Process all tasks in the queue."""
        while self._request_queue:
            # Get item
            try:
                item = self._request_queue[0]
            except IndexError:
                break
            # Unpack item
            func, args, kwargs, self._reporting = item
            # Process item
            try:
                result = func(*args, **kwargs)
                if self._reporting:
                    self._report_queue.append(result)
            # Remove item
            finally:
                self._reporting = False
                self._request_queue.popleft()

# ------------------------------------------------------------------
#    Event methods
# ------------------------------------------------------------------

    def _push_channel_events(self, channels=channels):
        """Push the TANGO change events for the given channels."""
        if self.events:
            for channel in channels:
                name = self.waveform_names[channel]
                data = self._waveform_data[channel]
                self.push_change_event(name, data)

    def _push_time_scale_event(self):
        """Push the TANGO change event for the time scale."""
        if self.events:
            self.push_change_event("TimeScale", self._time_scale)

    def _setup_events(self):
        """Setup events for waveforms and timescale."""
        if self.events:
            for name in self.waveform_names.values():
                self.set_change_event(name, True, False)
            self.set_change_event("TimeScale", True, False)

#------------------------------------------------------------------
#    Update methods
#------------------------------------------------------------------

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
            string = "Error: " + self._error + "\n"
            string += "Please run the Init command to reconnect." + "\n"
            string += "If the same error is raised, check the hardware state."
            self.set_status(string)
            return
        # Status
        default_status = "No status available."
        status_string = self._status if self._status else default_status
        # Update
        delta = time() - self._stamp
        if delta > self.update_timeout:
            update_string = "Last update {0:.2f} seconds ago.".format(delta)
        else:
            update_string = "Up-to-date."
        self.set_status(status_string + ' ' + update_string)

    def update_state(self):
        """Update the state from connection status, errors and timeout."""
        # Fault state
        if self._error:
            self.set_state(PyTango.DevState.FAULT)
            return
        # Init state
        if self.get_state() != PyTango.DevState.FAULT and self._connected:
            state = DevState.RUNNING if any(self._state_queue) else DevState.ON
            self.set_state(state)
            return

# ------------------------------------------------------------------
#    Initialization methods
# ------------------------------------------------------------------

    def __init__(self, cl, name):
        """Initialize the device and manage events."""
        PyTango.Device_4Impl.__init__(self, cl, name)
        self._setup_events()
        self.init_device()
        self._push_channel_events(self.channels)

    @debug_it
    def init_device(self):
        """Initialize instance attributes and start the thread."""
        self.get_device_properties()
        self.set_state(PyTango.DevState.INIT)

        # Thread attribute
        self._instrument_thread = Thread(target=self._instrument_loop)
        self._stamp = time()
        self._request_queue = deque()
        self._report_queue = deque(maxlen=1)
        self._rotate = deque(range(5))
        self._linspace_args = None
        self._alive = True
        self._error = ""
        self._warning = False
        self._reporting = False
        self._waiting = False

        # Instanciate instrument
        callback_ms = int(self.callback_timeout * 1000)
        connection_ms = int(self.connection_timeout * 1000)
        instrument_ms = int(self.instrument_timeout * 1000)
        callback = self._instrument_callback
        kwargs = {'host': self.Instrument,
                  'callback_timeout': callback_ms,
                  'connection_timeout': connection_ms,
                  'instrument_timeout': instrument_ms,
                  'callback': callback}
        self._instrument = RohdeSchwarzRTMConnection(**kwargs)

        # Instrument attributes
        self._idn = "unknown"
        self._status = ""
        self._time_scale = []
        self._hposition = 0.0
        self._hrange = 0.0
        self._trigger_channel = 0
        self._trigger_slope = 0
        self._state_queue = deque(maxlen=5)
        self._waveform_data = defaultdict(list)
        self._coupling = defaultdict(str)
        self._vpositions = defaultdict(float)
        self._vranges = defaultdict(float)
        self._levels = defaultdict(int)
        self._active_channels = defaultdict(bool)

        # Push events
        self._update_time_scale()
        self._push_channel_events()

        # Run thread
        self._instrument_thread.start()

    @debug_it
    def delete_device(self):
        """Try to stop the thread."""
        self._alive = False
        if self._instrument_thread.is_alive():
            timeout = self.connection_timeout + self.callback_timeout
            self._instrument_thread.join(timeout)
        if self._instrument_thread.is_alive():
            self.error_stream("Cannot join the reading thread")

# ------------------------------------------------------------------
#    General attributes
# ------------------------------------------------------------------

    # Identifier

    Identifier = attribute(
        dtype=str,
        doc="Instrument identification",
    )

    def read_Identifier(self, attr):
        attr.set_value(self._idn)

    def is_Identifier_allowed(self, req_type):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

# ------------------------------------------------------------------
#    Time attributes
# ------------------------------------------------------------------

    # TimeRange

    TimeRange = attribute(
        dtype=float,
        access=AttrWriteType.READ_WRITE,
        label="Time range",
        unit="s",
        min_value=1e-8,
        max_value=1.0,
        format="%.1e",
        memorized=True,
        doc="Horizontal time range"
    )

    def read_TimeRange(self, attr):
        attr.set_value(self._hrange)

    @debug_it
    def write_TimeRange(self, attr):
        data = attr.get_write_value()
        self._enqueue(self._instrument.setHRange, data)

    def is_TimeRange_allowed(self, req_type):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

    # TimePosition

    TimePosition = attribute(
        dtype=float,
        access=AttrWriteType.READ_WRITE,
        label="Time position",
        unit="s",
        min_value=-1.0,
        max_value=1.0,
        format="%.1e",
        memorized=True,
        doc="Horizontal time position"
    )

    def read_TimePosition(self, attr):
        attr.set_value(self._hposition)

    @debug_it
    def write_TimePosition(self, attr):
        data = attr.get_write_value()
        self._enqueue(self._instrument.setHPosition, data)

    def is_TimePosition_allowed(self, req_type):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

    # TimeScale

    TimeScale = attribute(
        dtype=(float,),
        max_dim_x=10000,
        label="Time scale",
        unit="s",
        doc="Time scale value table"
    )

    def read_TimeScale(self, attr):
        attr.set_value(self._time_scale)

    def is_TimeScale_allowed(self, req_type):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

# ------------------------------------------------------------------
#    Commands
# ------------------------------------------------------------------

    # Run command

    @command
    def Run(self):
        self._enqueue(self._instrument.issueRun)

    def is_Run_allowed(self):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

    # Stop command

    @command
    def Stop(self):
        self._enqueue(self._instrument.issueStop)

    def is_Stop_allowed(self):
        return self.get_state() not in [DevState.INIT, DevState.FAULT]

    # Autoset

    @command
    def Autoset(self):
        self._enqueue(self._instrument.issueAutoset)

    def is_Autoset_allowed(self):
        return self.get_state() == PyTango.DevState.RUNNING

    # Execute command

    @command
    def Execute(self, argin):
        # Check report queue
        if self._report_queue:
            msg = "A command is already being executed"
            raise RuntimeError(msg)
        # Set state
        self.events = False
        self._waiting = True
        # Equeue command
        command = " ".join(argin)
        self._enqueue(self._instrument.issueCommand, command, report=True)
        # Handle command timeout
        start = time()
        while time() - start < self.command_timeout:
            # Apply a minimal period
            with tick_context(self.minimal_period):
                # Try to get the report
                try:
                    result = self._report_queue.pop()
                    break
                # Wait for the report
                except IndexError:
                    continue
        # Timeout case
        else:
            result = "No response from the scope"
            result += " (timeout = {0:3.1f} s)".format(self.command_timeout)
        # Restore state
        self._waiting = False
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
    instrument_class = RohdeSchwarzRTMConnection
