"""Common functions for the scope devices."""

# Imports
import weakref
import PyTango
import functools
import traceback
import collections
from time import sleep
from contextlib import contextmanager
from timeit import default_timer as time
from threading import _Condition, _Event


# Patched version of partial
def partial(func, *args, **kwargs):
    """Partial for tango attribute accessors"""
    partial_object = functools.partial(func, *args, **kwargs)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return partial_object(*args, **kwargs)
    return wrapper


# Patched version of tango attribute
def attribute(*args, **kwargs):
    """Patched version of tango attribute."""
    fset = kwargs.pop("fset", None)
    attr = PyTango.server.attribute(*args, **kwargs)
    if fset:
        return attr.setter(fset)
    return attr


# DeviceMeta metaclass
def DeviceMeta(name, bases, attrs):
    """Enhanced version of PyTango.server.DeviceMeta
    that supports inheritance.
    """
    # Save current attrs
    save_key = '_save_attrs'
    dct = {save_key: attrs}
    # Filter object from bases
    filt = lambda arg: arg != object
    bases = tuple(filter(filt, bases))
    # Add device to bases
    if PyTango.server.Device not in bases:
        bases += (PyTango.server.Device,)
    # Update attribute dictionary
    for base in reversed(bases):
        dct.update(getattr(base, save_key, {}))
    dct.update(attrs)
    # Create device class
    cls = PyTango.server.DeviceMeta(name, bases, dct)
    cls.TangoClassName = name
    return cls


# Lock Event
class LockEvent(_Condition, _Event):
    """Event that can be locked to perform additional test."""

    def __init__(self):
        """Initialize the event."""
        _Condition.__init__(self)
        _Event.__init__(self)

    def wait(self, timeout=None):
        """Wait for the event to be set."""
        with self:
            if not self.is_set():
                _Condition.wait(self, timeout)
            return self.is_set()

    def set(self):
        """Set the event."""
        with self:
            _Event.set(self)
            self.notify()

    def clear(self):
        """Clear the event."""
        with self:
            _Event.clear(self)


# Tick context
@contextmanager
def tick_context(value):
    """Generate a context that controls the duration of its execution."""
    start = time()
    yield
    sleep_time = start + value - time()
    if sleep_time > 0:
        sleep(sleep_time)


# Safe traceback
def safe_traceback():
    """Make the traceback output compatible with PyTango log streaming."""
    return traceback.format_exc().replace('%', '%%')


# Safe method decorator
def safe_loop(handler_name):
    """Decorator to define an exception handler."""
    # Decorator
    def decorator(func):
        # Wrapper
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Run method
            try:
                while not func(self, *args, **kwargs):
                    pass
            # Handle exception
            except Exception as exc:
                handler = getattr(self, handler_name, None)
                if not handler:
                    raise
                return handler(exc)
        return wrapper
    return decorator


# Exception
class StopIO(Exception):
    """Exception raised to stop the current IO operation."""
    pass


# RW attribute
rw_attribute = functools.partial(
    attribute,
    access=PyTango.AttrWriteType.READ_WRITE,
    fisallowed="is_read_write_allowed",
    memorized=True,
)

# Read attribute
read_attribute = functools.partial(
    attribute,
    fisallowed="is_read_allowed",
)


# Periodic method logger
def debug_periodic_method(stream=None, track=10):
    """Return a decorator to log information
    about a periodicaly called method.
    """
    cache = weakref.WeakKeyDictionary()

    def decorator(func):
        """Decorator to log information about a periodicaly called method."""
        func_name = func.__name__

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get debug stream
            logger = getattr(self, stream) if stream else lambda msg: None
            # Get stamps
            stamps = cache.setdefault(self, collections.deque(maxlen=track))
            now = time()
            # Log last call
            if stamps:
                msg = "Calling {0} (last call {1:1.3f} s ago)"
                logger(msg.format(func_name, now - stamps[-1]))
            # Call original method
            value = func(self, *args, **kwargs)
            # Log last
            msg = "{0} ran in {1:1.3f} seconds"
            logger(msg.format(func_name, time() - now))
            # Save stamps
            stamps.append(now)
            # Log last calls
            if len(stamps) > 1:
                msg = "{0} ran {1} times in the last {2:1.3f} seconds"
                logger(msg.format(func_name, len(stamps), time() - stamps[0]))
            # Return
            return value
        return wrapper
    return decorator


# Queue device class
class RequestQueueDevice(PyTango.server.Device):
    """Generic class implementing queues and state transiions."""
    __metaclass__ = DeviceMeta

# ------------------------------------------------------------------
#    Initialization methods
# ------------------------------------------------------------------

    def init_device(self):
        """Initialize instance attributes and start the thread."""
        PyTango.server.Device.init_device(self)
        self.set_state(PyTango.DevState.INIT)
        # Request queue
        self.request_queue = collections.deque()
        self.awake = LockEvent()
        self.alive = True
        # Report queue
        self.report_queue = collections.deque(maxlen=1)
        self.reporting = False

    def delete_device(self):
        PyTango.server.Device.delete_device(self)
        """Try to stop the thread."""
        self.alive = False
        self.awake.set()

# ------------------------------------------------------------------
#    Exception methods
# ------------------------------------------------------------------

    def register_exception(self, exc):
        """Register the error and stop the thread."""
        # Set error
        try:
            self.error = str(exc) if str(exc) else repr(exc)
        except:
            self.error = "unexpected error"
        # Log traceback
        try:
            self.error_stream(safe_traceback())
        except:
            self.error_stream("Cannot log traceback.")
        # Set state
        self.set_state(PyTango.DevState.FAULT)

# ------------------------------------------------------------------
#    Queue methods
# ------------------------------------------------------------------

    def safe_wait(self):
        """Wait to be awaken only if the queue is empty."""
        with self.awake:
            if not self.request_queue:
                self.awake.wait()

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

    def enqueue_transition(self, state1, state2, func, *args, **kwargs):
        """Enqueue a task associated to a state transition."""
        def wrapper():
            # Check initial state
            if self.get_state() != state1:
                msg = "Cannot run transition task, state is {0} instead of {1}"
                self.warn_stream(msg.format(self.get_state(), state1))
                return
            # Execute task
            try:
                res = func(*args, **kwargs)
            # Reset transition
            except:
                msg = "Got an exception while running the transition task"
                self.warn_stream(msg)
                self.next_state = None
                raise
            # Check initial state
            if self.get_state() != state1:
                msg = "Cannot transit to {0}, state is {1} instead of {2}"
                self.warn_stream(msg.format(state2, self.get_state(), state1))
                return res
            # Set new state
            self.set_state(state2)
            return res
        # Register next state
        self.set_next_state(state2)
        self.enqueue(wrapper)

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
#    State methods
# ------------------------------------------------------------------

    def set_next_state(self, state=None):
        """Set the next state for a transistion."""
        self.next_state = state
        if state is not None:
            self.manage_state(state, transition=True)
        else:
            self.manage_state(self.get_state(), transition=False)

    def set_state(self, state):
        """Awake the scope thread when the device is in the right state."""
        # Check transition
        try:
            if self.next_state is None:
                msg = "Unplanned state transition ({0})"
                self.debug_stream(msg.format(state))
            elif self.next_state == state:
                msg = "Valid state transition ({0})"
                self.debug_stream(msg.format(state))
            else:
                msg = "Invalid state transition ({0} instead of {1})"
                self.debug_stream(msg.format(state, self.next_state))
        # First state
        except AttributeError:
            msg = "First transition ({0})"
            self.debug_stream(msg.format(state))
        # Set state
        PyTango.server.Device.set_state(self, state)
        self.set_next_state()

    def steady_state(self, state, raise_exception=True):
        """Check that the device is in a given steady state."""
        if self.get_state() != state:
            return False
        if self.next_state is None:
            return True
        if raise_exception:
            PyTango.Except.throw_exception("COMMAND_FAILED",
                                           "The current state is changing",
                                           "ScopeDevice::steady_state()")
        return False
