"""Provide the RTO scope TANGO device class."""

# Library imports
from rohdescope import RTOConnection

# Common imports
from scopedevice.device import ScopeDevice
from scopedevice.common import rw_attribute, DeviceMeta, partial


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
        self.scope.issue_stop()
        self.scope.set_display(True)

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


# Main execution
if __name__ == "__main__":
    RTOScope.run_server()
