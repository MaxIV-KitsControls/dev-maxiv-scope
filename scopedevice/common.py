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
from collections import Mapping, namedtuple
from PyTango import AttrQuality, AttReqType

# Stamped tuple
_stamped = namedtuple("stamped", ("value", "stamp", "quality"))
stamped = functools.partial(_stamped, quality=AttrQuality.ATTR_VALID)


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
class event_property(object):
    """Property that pushes change events automatically."""

    # Aliases
    INVALID = AttrQuality.ATTR_INVALID
    VALID = AttrQuality.ATTR_VALID

    def __init__(self, attribute, default=None, invalid=None,
                 is_allowed=None, event=True, doc=None):
        self.attribute = attribute
        self.default = default
        self.invalid = invalid
        self.event = event
        self.__doc__ = doc
        default = getattr(attribute, "is_allowed_name", "")
        self.is_allowed = is_allowed or default

    # Helper

    def get_attribute_name(self):
        try:
            return self.attribute.attr_name
        except AttributeError:
            return self.attribute

    def allowed(self, device):
        is_allowed = self.is_allowed
        if is_allowed and isinstance(is_allowed, basestring):
            is_allowed = getattr(device, is_allowed)
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

    @classmethod
    def unpack(cls, value):
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
        if value != self.invalid:
            return value, stamp, quality
        return self.get_default_value(device), stamp, self.INVALID

    def get_default_value(self, device):
        if self.default != self.invalid:
            return self.default
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

    def __del__(self, instance):
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
        self.delete_all(device)

    def reloader(self, device=None, reset=True):
        # Prevent class calls
        if device is None:
            return
        # Delete attributes
        if reset:
            self.deleter(device)
        # Set quality
        if not self.allowed(device):
            self.set_value(device, quality=self.INVALID,
                           disable_event=reset)
        # Force events
        if reset and self.event_enabled(device):
            self.push_event(device, *self.get_value(device))

    # Private attribute access

    def get_value(self, device):
        try:
            value = self.get_private_value(device)
            stamp = self.get_private_stamp(device)
            quality = self.get_private_quality(device)
        except AttributeError:
            value = self.get_default_value(device)
            stamp = time()
            quality = self.get_default_quality()
        return value, stamp, quality

    def set_value(self, device, value=None, stamp=None, quality=None,
                  disable_event=False):
        # Prepare
        old_value, old_stamp, old_quality = self.get_value(device)
        if value is None:
            value = old_value
        if stamp is None:
            stamp = time()
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
        attr = getattr(device, self.get_attribute_name())
        if not attr.is_change_event():
            attr.set_change_event(True, False)
        device.push_change_event(self.get_attribute_name(),
                                 value, stamp, quality)


# Mapping object
class mapping(Mapping):
    """Mapping object to gather python attributes."""

    def __init__(self, instance, base, keys):
        self.base = base
        self.keys = keys
        self.instance = instance

    def __getitem__(self, key):
        if key not in self.keys:
            raise KeyError(key)
        return getattr(self.instance, self.base + str(key))

    def __setitem__(self, key, value):
        if key not in self.keys:
            raise KeyError(key)
        setattr(self.instance, self.base + str(key), value)

    def __iter__(self):
        return iter(self.keys)

    def __len__(self):
        return len(self.keys)
