"""Common functions for the scope devices."""

# Imports
import sys
import time
import weakref
import PyTango
import threading
import functools
import traceback
import contextlib
import collections

# PyTango imports
from PyTango import server
from PyTango import AttrQuality, AttReqType, AttrWriteType

# Stamped tuple
_stamped = collections.namedtuple("stamped", ("value", "stamp", "quality"))
stamped = functools.partial(_stamped, quality=AttrQuality.ATTR_VALID)


# Tango objects
def is_tango_object(arg):
    """Return tango data if the argument is a tango object,
    False otherwise.
    """
    classes = server.attribute, server.device_property
    if isinstance(arg, classes):
        return arg
    try:
        return arg.__tango_command__
    except AttributeError:
        return False


# Run server class method
@classmethod
def run_server(cls, args=None, **kwargs):
    """Run the class as a device server.
    It is based on the PyTango.server.run method.

    The difference is that the device class
    and server name are automatically given.

    Args:
        args (iterable): args as given in the PyTango.server.run method
                         without the server name. If None, the sys.argv
                         list is used
        kwargs: the other keywords argument are as given
                in the PyTango.server.run method.
    """
    if not args:
        args = sys.argv[1:]
    args = [cls.__name__] + list(args)
    return server.run((cls,), args, **kwargs)


# Inheritance patch
def inheritance_patch(attrs):
    """Patch tango objects before they are processed."""
    for key, obj in attrs.items():
        if isinstance(obj, server.attribute):
            if getattr(obj, 'attr_write', None) == AttrWriteType.READ_WRITE:
                if not getattr(obj, 'fset', None):
                    method_name = obj.write_method_name or "write_" + key
                    obj.fset = attrs.get(method_name)


# DeviceMeta metaclass
def DeviceMeta(name, bases, attrs):
    """Enhanced version of PyTango.server.DeviceMeta
    that supports inheritance.
    """
    # Compatibility >= 8.1.8
    if PyTango.__version_info__ >= (8, 1, 8):
        return PyTango.server.DeviceMeta(name, bases, attrs)
    # Attribute dictionary
    dct = {"run_server": run_server}
    # Filter object from bases
    bases = tuple(base for base in bases if base != object)
    # Add device to bases
    if PyTango.server.Device not in bases:
        bases += (PyTango.server.Device,)
    # Set tango objects as attributes
    for base in reversed(bases):
        for key, value in base.__dict__.items():
            if is_tango_object(value):
                dct[key] = value
    # Inheritance patch
    inheritance_patch(attrs)
    # Update attribute dictionary
    dct.update(attrs)
    # Create device class
    cls = PyTango.server.DeviceMeta(name, bases, dct)
    cls.TangoClassName = name
    return cls


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
    if kwargs["dtype"] in (str, bool):
        kwargs.pop("abs_change", None)
    attr = PyTango.server.attribute(*args, **kwargs)
    if fset:
        try:
            return attr.setter(fset)
        except AttributeError:
            pass
    return attr


# Lock Event
class LockEvent(threading._Condition, threading._Event):
    """Event that can be locked to perform additional test."""

    def __init__(self):
        """Initialize the event."""
        threading._Condition.__init__(self)
        threading._Event.__init__(self)

    def wait(self, timeout=None):
        """Wait for the event to be set."""
        with self:
            if not self.is_set():
                threading._Condition.wait(self, timeout)
            return self.is_set()

    def set(self):
        """Set the event."""
        with self:
            threading._Event.set(self)
            self.notify()

    def clear(self):
        """Clear the event."""
        with self:
            threading._Event.clear(self)


# Tick context
@contextlib.contextmanager
def tick_context(value):
    """Generate a context that controls the duration of its execution."""
    start = time.time()
    yield
    sleep_time = start + value - time.time()
    if sleep_time > 0:
        time.sleep(sleep_time)


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
            now = time.time()
            # Log last call
            if stamps:
                msg = "Calling {0} (last call {1:1.3f} s ago)"
                logger(msg.format(func_name, now - stamps[-1]))
            # Call original method
            value = func(self, *args, **kwargs)
            # Log last
            msg = "{0} ran in {1:1.3f} seconds"
            logger(msg.format(func_name, time.time() - now))
            # Save stamps
            stamps.append(now)
            # Log last calls
            if len(stamps) > 1:
                delta = time.time() - stamps[0]
                msg = "{0} ran {1} times in the last {2:1.3f} seconds"
                logger(msg.format(func_name, len(stamps), delta))
            # Return
            return value
        return wrapper
    return decorator


# Event property
class event_property(object):
    """Property that pushes change events automatically."""

    # Aliases
    INVALID = AttrQuality.ATTR_INVALID
    VALID = AttrQuality.ATTR_VALID

    def __init__(self, attribute, default=None, invalid=None,
                 is_allowed=None, event=True, dtype=None, doc=None):
        self.lock_cache = weakref.WeakKeyDictionary()
        self.attribute = attribute
        self.default = default
        self.invalid = invalid
        self.event = event
        self.dtype = dtype if callable(dtype) else None
        self.__doc__ = doc
        default = getattr(attribute, "is_allowed_name", "")
        self.is_allowed = is_allowed or default

    # Helper

    def get_lock(self, device):
        return self.lock_cache.setdefault(device, threading.RLock())

    def get_attribute_name(self):
        try:
            return self.attribute.attr_name
        except AttributeError:
            return self.attribute

    def get_is_allowed_method(self, device):
        if callable(self.is_allowed):
            return self.is_allowed
        if self.is_allowed:
            return getattr(device, self.is_allowed)
        name = "is_" + self.get_attribute_name() + "_allowed"
        return getattr(device, name, None)

    def allowed(self, device):
        is_allowed = self.get_is_allowed_method(device)
        return not is_allowed or is_allowed(AttReqType.READ_REQ)

    def event_enabled(self, device):
        if self.event and isinstance(self.event, basestring):
            return getattr(device, self.event)
        return self.event

    def get_private_value(self, device):
        name = "__" + self.get_attribute_name() + "_value"
        return getattr(device, name)

    def set_private_value(self, device, value):
        name = "__" + self.get_attribute_name() + "_value"
        setattr(device, name, value)

    def get_private_quality(self, device):
        name = "__" + self.get_attribute_name() + "_quality"
        return getattr(device, name)

    def set_private_quality(self, device, quality):
        name = "__" + self.get_attribute_name() + "_quality"
        setattr(device, name, quality)

    def get_private_stamp(self, device):
        name = "__" + self.get_attribute_name() + "_stamp"
        return getattr(device, name)

    def set_private_stamp(self, device, stamp):
        name = "__" + self.get_attribute_name() + "_stamp"
        setattr(device, name, stamp)

    def delete_all(self, device):
        for suffix in ("_value", "_stamp", "_quality"):
            name = "__" + self.get_attribute_name() + suffix
            try:
                delattr(device, name)
            except AttributeError:
                pass

    @staticmethod
    def unpack(value):
        try:
            value.stamp = value.time.totime()
        except AttributeError:
            pass
        try:
            return value.value, value.stamp, value.quality
        except AttributeError:
            pass
        try:
            return value.value, value.stamp, None
        except AttributeError:
            pass
        try:
            return value.value, None, value.quality
        except AttributeError:
            pass
        return value, None, None

    def check_value(self, device, value, stamp, quality):
        if value is None or \
           (self.invalid is not None and value == self.invalid):
            return self.get_default_value(device), stamp, self.INVALID
        if self.dtype:
            value = self.dtype(value)
        return value, stamp, quality

    def get_default_value(self, device):
        if self.default != self.invalid:
            return self.default
        if self.dtype:
            return self.dtype()
        attr = getattr(device, self.get_attribute_name())
        if attr.get_data_type() == PyTango.DevString:
            return str()
        if attr.get_max_dim_x() > 1:
            return list()
        return int()

    def get_default_quality(self):
        if self.default != self.invalid:
            return self.VALID
        return self.INVALID

    # Descriptors

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self.getter(instance)

    def __set__(self, instance, value):
        return self.setter(instance, value)

    def __delete__(self, instance):
        return self.deleter(instance)

    # Access methods

    def getter(self, device):
        if not self.allowed(device):
            self.set_value(device, quality=self.INVALID)
        value, stamp, quality = self.get_value(device)
        if quality == self.INVALID:
            return self.invalid
        return value

    def setter(self, device, value):
        value, stamp, quality = self.unpack(value)
        if not self.allowed(device):
            quality = self.INVALID
        args = device, value, stamp, quality
        self.set_value(device, *self.check_value(*args))

    def deleter(self, device):
        self.reloader(device)

    def reloader(self, device=None, reset=True):
        # Prevent class calls
        if device is None:
            return
        # Delete attributes
        if reset:
            self.delete_all(device)
        # Set quality
        if not self.allowed(device):
            self.set_value(device, quality=self.INVALID,
                           disable_event=reset)
        # Force events
        if reset and self.event_enabled(device):
            self.push_event(device, *self.get_value(device))

    # Private attribute access

    def get_value(self, device, attr=None):
        # Get value
        with self.get_lock(device):
            try:
                value = self.get_private_value(device)
                stamp = self.get_private_stamp(device)
                quality = self.get_private_quality(device)
            except AttributeError:
                value = self.get_default_value(device)
                stamp = time.time()
                quality = self.get_default_quality()
        # Set value
        if attr:
            attr.set_value_date_quality(value, stamp, quality)
        # Return
        return value, stamp, quality

    def set_value(self, device, value=None, stamp=None, quality=None,
                  disable_event=False):
        with self.get_lock(device):
            # Prepare
            old_value, old_stamp, old_quality = self.get_value(device)
            if value is None:
                value = old_value
            if stamp is None:
                stamp = time.time()
            if quality is None and value is not None:
                quality = self.VALID
            elif quality is None:
                quality = old_quality
            # Test differences
            diff = old_quality != quality or old_value != value
            try:
                bool(diff)
            except ValueError:
                diff = diff.any()
            if not diff:
                return
            # Set
            self.set_private_value(device, value)
            self.set_private_stamp(device, stamp)
            self.set_private_quality(device, quality)
            # Push event
            if not disable_event and self.event_enabled(device):
                self.push_event(device, *self.get_value(device))

    # Aliases

    read = get_value
    write = set_value

    # Event method

    def push_event(self, device, value, stamp, quality):
        with self.get_lock(device):
            attr = getattr(device, self.get_attribute_name())
            if not attr.is_change_event():
                attr.set_change_event(True, False)
            attr.set_value_date_quality(value, stamp, quality)
            attr.fire_change_event()


# Mapping object
class mapping(collections.MutableMapping):
    """Mapping object to gather python attributes."""

    def clear(self):
        for x in self:
            del self[x]

    def __init__(self, instance, convert, keys):
        self.key_list = list(keys)
        self.convert = convert
        self.instance = instance

    def __getitem__(self, key):
        if key not in self.key_list:
            raise KeyError(key)
        return getattr(self.instance, self.convert(key))

    def __setitem__(self, key, value):
        if key not in self.key_list:
            raise KeyError(key)
        setattr(self.instance, self.convert(key), value)

    def __delitem__(self, key):
        if key not in self.key_list:
            raise KeyError(key)
        delattr(self.instance, self.convert(key))

    def __iter__(self):
        return iter(self.key_list)

    def __len__(self):
        return len(self.key_list)

    def __str__(self):
        return str(dict(self.items()))

    def __repr__(self):
        return repr(dict(self.items()))


# Request queue device class
class RequestQueueDevice(PyTango.server.Device):
    """Generic class implementing queues and state transitions."""
    __metaclass__ = DeviceMeta

# ------------------------------------------------------------------
#    Initialization methods
# ------------------------------------------------------------------

    def init_device(self):
        """Initialize instance attributes and start the thread."""
        PyTango.server.Device.set_state(self, PyTango.DevState.INIT)
        PyTango.server.Device.init_device(self)
        # State and attributes
        self.update_attributes(reset=True)
        self.next_state = None
        # Request queue
        self.request_queue = collections.deque()
        self.awake = LockEvent()
        self.alive = True

    def delete_device(self):
        PyTango.server.Device.delete_device(self)
        """Try to stop the thread."""
        self.alive = False
        self.awake.set()

# ------------------------------------------------------------------
#    Exception method
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
            self.error_stream("Exception: {0}".format(self.error))
            self.debug_stream(safe_traceback())
        except:
            self.error_stream("Cannot log error and traceback properly.")
        # Set state
        self.set_state(PyTango.DevState.FAULT)

# ------------------------------------------------------------------
#    Attribute method
# ------------------------------------------------------------------

    def update_attributes(self, reset=False):
        """Reload attribute values."""
        cls = type(self)
        for name in dir(cls):
            try:
                getattr(cls, name).reloader(self, reset)
            except AttributeError:
                pass

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
        item = func, args, kwargs
        try:
            append = (item != self.request_queue[-1])
        except IndexError:
            append = True
        if append:
            self.request_queue.append(item)

    def enqueue_transition(self, state1, state2, func, *args, **kwargs):
        """Enqueue a task associated to a state transition."""
        def wrapper():
            with self.ensure_reset_next_state():
                # Check initial state
                if self.get_state() != state1:
                    msg = "Cannot run transition, state is {0} instead of {1}"
                    self.warn_stream(msg.format(self.get_state(), state1))
                    return
                # Execute task
                try:
                    res = func(*args, **kwargs)
                # Reset transition
                except:
                    msg = "Got an exception while running the transition task"
                    self.warn_stream(msg)
                    raise
                # Check initial state
                if self.get_state() != state1:
                    msg = "Cannot transit to {0}, state is {1} instead of {2}"
                    msg = msg.format(state2, self.get_state(), state1)
                    self.warn_stream(msg)
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
            func, args, kwargs = item
            # Process item
            try:
                func(*args, **kwargs)
            # Remove item
            finally:
                self.request_queue.popleft()

# ------------------------------------------------------------------
#    State methods
# ------------------------------------------------------------------

    def manage_state(self, state, transition=False):
        """Handle the thread depending on the current state."""
        self.update_attributes()

    def set_next_state(self, state):
        """Set the next state for a transistion."""
        self.next_state = state
        self.manage_state(state, transition=True)

    def reset_next_state(self):
        """Reset the next state."""
        self.next_state = None

    @contextlib.contextmanager
    def ensure_reset_next_state(self):
        """Context to make sure the next state is reset."""
        try:
            yield self.next_state
        finally:
            self.reset_next_state()

    def set_state(self, state):
        """Awake the scope thread when the device is in the right state."""
        # Check transition
        if self.next_state is None:
            msg = "Unplanned state transition ({0})"
            self.info_stream(msg.format(state))
        elif self.next_state == state:
            msg = "Valid state transition ({0})"
            self.info_stream(msg.format(state))
        else:
            msg = "Invalid state transition ({0} instead of {1})"
            self.warn_stream(msg.format(state, self.next_state))
        # Set state
        PyTango.server.Device.set_state(self, state)
        self.reset_next_state()
        self.manage_state(state, transition=False)

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
