Supported scopes
================

The following devices subclass the ScopeDevice generic interface.

.. autoclass:: scopedevice.RTMScope

    This device use RunContinuous scope command instead of RunSingle.

    It also ignores End-of-file errors.

    The `RecordLength` attribute is different from the ScopeDevice interface:

    .. autotangoitem:: scopedevice.RTMScope.RecordLength

        (Read-only for the RTM scope)

.. autoclass:: scopedevice.RTOScope

    This device turn the display of the scope off before running an acquisition.

    It also forces the display on when deleting the device.

    The `ChannelCouplingX` attributes are different from the ScopeDevice interface:

    .. autotangoitem:: scopedevice.RTOScope.ChannelCoupling1

    .. autotangoitem:: scopedevice.RTOScope.ChannelCoupling2

    .. autotangoitem:: scopedevice.RTOScope.ChannelCoupling3

    .. autotangoitem:: scopedevice.RTOScope.ChannelCoupling4
