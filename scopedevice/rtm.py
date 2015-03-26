"""Provide the RTM scope TANGO device class."""

# Library imports
from rohdescope import RTMConnection

# Common imports
from scopedevice.device import ScopeDevice
from scopedevice.common import read_attribute, DeviceMeta, safe_traceback


# Generic scope device
class RTMScope(ScopeDevice):
    """RTM scope device."""
    __metaclass__ = DeviceMeta

    # Library
    connection_class = RTMConnection

    # Prepare acquisition
    def prepare_acquisition(self):
        """Prepare the acquisition."""
        ScopeDevice.prepare_acquisition(self)
        self.scope.issue_run()

    # Clean acquisition
    def clean_acquisition(self):
        """Clean the acquisition."""
        ScopeDevice.clean_acquisition(self)
        self.scope.issue_stop()

    # Catch EOFError
    def handle_exception(self, exc):
        """"Handle a given exception"""
        if isinstance(exc, EOFError):
            self.warn_stream(safe_traceback())
            self.error_stream("Ignoring an end-of-file error...")
            return
        return ScopeDevice.handle_exception(self, exc)

    # Record length (read-only)
    RecordLength = read_attribute(
        dtype=int,
        label="Record length",
        unit="point",
        min_value=0,
        max_value=10**8,
        format="%d",
        fget=ScopeDevice.record_length.read,
        doc="Record length for the waveforms",
    )


# Main execution
if __name__ == "__main__":
    import scopedevice
    scopedevice.run_rtm()
