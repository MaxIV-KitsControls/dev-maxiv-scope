"""Common functions for the scope devices."""

# Imports
import weakref
import PyTango
import functools
import traceback
import collections
from time import sleep
from PyTango import AttrQuality
from contextlib import contextmanager
from timeit import default_timer as time
from threading import _Condition, _Event
from collections import Mapping, namedtuple

# Stamped tuple
stamped = namedtuple("stamped", ("value", "stamp"))

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


# Event property
def event_property(attribute, default=None, invalid=None,
                   is_allowed=None, event=True, dtype=None, doc=None):
    """Return a property that pushes change events automatically."""
    is_allowed = is_allowed or getattr(attribute, "is_allowed_name", "")

    # Helper

    def get_attribute_name():
        try:
            return attribute.attr_name
        except AttributeError:
            return attribute

    def get_private_name():
        return "__" + get_attribute_name()

    # Descriptor methods

    def getter(device, is_allowed=is_allowed):
        if is_allowed and isinstance(is_allowed, basestring):
            is_allowed = getattr(device, is_allowed)
        if is_allowed and not is_allowed(None):
            set_value(device, invalid)
        return get_value(device)

    def setter(device, value, is_allowed=is_allowed):
        if is_allowed and isinstance(is_allowed, basestring):
            is_allowed = getattr(device, is_allowed)
        if is_allowed and not is_allowed(None):
            value = invalid
        set_value(device, value)

    def deleter(device):
        del_value(device)

    # Private attribute access

    def get_value(device):
        try:
            return getattr(device, get_private_name())
        except AttributeError:
            set_value(device, default)
            return default

    def set_value(device, value, event=event):
        try:
            value, stamp = value.value, value.stamp
        except AttributeError:
            stamp = None
        try:
            diff = (getattr(device, get_private_name()) == value)
            if diff:
                return
        except ValueError:
            if diff.all():
                return
        except AttributeError:
            pass
        setattr(device, get_private_name(), value)
        if event and isinstance(event, basestring):
            event = getattr(device, event)
        if event:
            push_event(device, value, stamp)

    def del_value(device):
        try:
            return delattr(device, get_private_name())
        except AttributeError:
            pass

    # Event method

    def push_event(device, value, dtype=dtype, stamp=None):
        attr = getattr(device, get_attribute_name())
        if not attr.is_change_event():
            attr.set_change_event(True, False)
        if not dtype and attr.get_data_type() == PyTango.DevString:
            dtype = str
        elif not dtype and attr.get_max_dim_x() > 1:
            dtype = list
        elif not dtype:
            dtype = int
        if not stamp:
            stamp = time()
            value == invalid
        if value == invalid:
            validity = AttrQuality.ATTR_INVALID
            value = dtype()
        else:
            validity = AttrQuality.ATTR_VALID
        device.push_change_event(get_attribute_name(), value, stamp, validity)

    # Build property
    return property(getter, setter, deleter, doc=doc)


class mapping(Mapping):
    """Mapping object to gather python attributes."""

    def __init__(self, instance, base, keys, default=None):
        self.base = base
        self.keys = keys
        self.default = default
        self.instance = instance
        for key in keys:
            self[key] = default

    def __getitem__(self, key):
        if key not in self.keys:
            raise KeyError(key)
        return getattr(self.instance, self.base + str(key))

    def __setitem__(self, key, value):
        if key not in self.keys:
            raise KeyError(key)
        return setattr(self.instance, self.base + str(key), value)

    def __iter__(self):
        return iter(self.keys)

    def __len__(self):
        return len(self.keys)
