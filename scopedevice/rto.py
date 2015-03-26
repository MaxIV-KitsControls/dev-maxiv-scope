"""Provide the RTO scope TANGO device class."""

# Imports
import PyTango

# Library imports
from rohdescope import RTOConnection

# Common imports
from scopedevice.device import ScopeDevice
from scopedevice.common import (rw_attribute, DeviceMeta,
                                partial, safe_traceback)


# RTO scope device
class RTOScope(ScopeDevice):
    """RTO scope device."""
    __metaclass__ = DeviceMeta

    # Library
    connection_class = RTOConnection

    # Prepare acquisition
    def prepare_acquisition(self):
        """Prepare the acquisition."""
        ScopeDevice.prepare_acquisition(self)
        self.scope.set_display(False)

    # Clean acquisition
    def clean_acquisition(self):
        """Clean the acquisition."""
        ScopeDevice.clean_acquisition(self)
        self.scope.set_display(True)

    # Turn on the display
    def delete_device(self):
        """Turn on the display and stop the threads."""
        try:
            if self.connected:
                self.scope.set_display(True)
        except Exception as exc:
            msg = "Error while turning the display on: {0}"
            self.debug_stream(safe_traceback())
            self.error_stream(msg.format(exc))
        return ScopeDevice.delete_device(self)

    # Channel couling
    def channel_coupling_attribute(channel):
        write = ScopeDevice.write_channel_coupling
        attrs = [ScopeDevice.channel_coupling_1,
                 ScopeDevice.channel_coupling_2,
                 ScopeDevice.channel_coupling_3,
                 ScopeDevice.channel_coupling_4]
        return rw_attribute(
            dtype=int,
            min_value=0,
            max_value=2,
            fget=attrs[channel-1].read,
            label="Channel coupling {0}".format(channel),
            doc="0 for DC, 1 for AC, 2 for DCLimit",
            fset=partial(write, channel=channel))

    ChannelCoupling1 = channel_coupling_attribute(1)
    ChannelCoupling2 = channel_coupling_attribute(2)
    ChannelCoupling3 = channel_coupling_attribute(3)
    ChannelCoupling4 = channel_coupling_attribute(4)

    # Trigger coupling

    TriggerCoupling = rw_attribute(
        dtype=int,
        min_value=0,
        max_value=2,
        label="Trigger coupling",
        fget=ScopeDevice.trigger_coupling.read,
        doc="0 for DC, 1 for AC, 2 for DCLimit",
    )

    # Expert attribute for busy wait

    BusyWait = rw_attribute(
        dtype=bool,
        format="%1d",
        label="Busy wait",
        display_level=PyTango.DispLevel.EXPERT,
        doc="Use busy wait for acquiring (safer)",
    )

    def read_BusyWait(self):
        return self.busy_wait

    def write_BusyWait(self, boolean):
        self.busy_wait = boolean


# Main execution
if __name__ == "__main__":
    import scopedevice
    scopedevice.run_rto()
