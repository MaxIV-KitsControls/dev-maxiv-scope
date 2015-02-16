"""Common functions for the scope devices."""

# Imports
import PyTango
import traceback
from time import sleep
from functools import wraps, partial
from contextlib import contextmanager
from timeit import default_timer as time
from PyTango import DevState, AttrWriteType


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
    # Create device
    return PyTango.server.DeviceMeta(name, bases, dct)


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
def safe_method(handler_name):
    """Decorator to define an exception handler."""
    # Decorator
    def decorator(func):
        # Wrapper
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Run method
            try:
                return func(self, *args, **kwargs)
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
rw_attribute = partial(
    PyTango.server.attribute,
    access=PyTango.AttrWriteType.READ_WRITE,
    fisallowed="is_read_write_allowed",
    memorized=True,
)

# Read attribute
read_attribute = partial(
    PyTango.server.attribute,
    fisallowed="is_read_allowed",
)
