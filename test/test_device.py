"""Contain the tests for the RTM Scope."""

# Imports
import scopedevice
from time import sleep
from mock import MagicMock
from PyTango import DevState
from itertools import product
from collections import defaultdict
from devicetest import DeviceTestCase


# Constants
READ = 0.01
UPDATE = 0.04
PRECISION = 5


# Note:
#
# Since the device uses an inner thread, it is necessary to
# wait during the tests in order the let the device update itself.
# Hence, the sleep calls have to be secured enough not to produce
# any inconsistent behavior. However, the unittests need to run fast.
# Here, we use a factor 4 between the read period and the sleep calls.


# Device test case
class ScopeDeviceTestCase(DeviceTestCase):
    """Test case for packet generation."""

    device = scopedevice.ScopeDevice
    properties = {'Host': '1.2.3.4'}
    empty = None  # Should be []
    debug = 0

    def assertEquals(self, arg1, arg2):
        if isinstance(arg1, float) or isinstance(arg2, float):
            DeviceTestCase.assertAlmostEquals(self, arg1, arg2,
                                              places=PRECISION)
        else:
            DeviceTestCase.assertEquals(self, arg1, arg2)

    def attribute_pattern(self, attr, values, read, write):
        for values in product(values, repeat=4):
            dct = dict(zip(range(1, 5), values))
            # Write
            for key, value in dct.items():
                setattr(self.device, attr+str(key), value)
            # Wait
            sleep(UPDATE)
            # Get write dict
            call_lst = getattr(self.instrument, write).call_args_list
            write_dct = dict(call[0] for call in call_lst)
            # Check
            for key, value in dct.items():
                self.assertEquals(value, write_dct[key])
            read_func = getattr(self.instrument, read)
            read_func.side_effect = dct.get
            # Wait
            sleep(UPDATE)
            # Read
            for key, value in dct.items():
                result = getattr(self.device, attr+str(key))
                self.assertEquals(value, result)

    @classmethod
    def mocking(cls):
        """Mock external libraries."""
        # Mock numpy
        cls.numpy = scopedevice.device.numpy = MagicMock()
        cls.numpy.linspace.return_value = []
        # Mock rtm library
        cls.connection = scopedevice.ScopeDevice.connection_class = MagicMock()
        cls.instrument = cls.connection.return_value
        is_connected = lambda *args: cls.instrument.connect.called
        cls.instrument.connected.__get__ = is_connected
        # Set up
        scopedevice.ScopeDevice.events = False
        scopedevice.ScopeDevice.acquisition_period = READ
        scopedevice.ScopeDevice.update_period = READ
        cls.instrument.get_status.return_value = "Some status."
        cls.instrument.get_identifier.return_value = "Some ID"
        cls.instrument.get_time_position.return_value = 0
        cls.instrument.stamp_acquisition.return_value = "", 0
        cls.instrument.decode_waveforms.return_value = defaultdict(list)

    def setUp(self):
        """Let the inner thread initialize the device."""
        DeviceTestCase.setUp(self)
        self.device.On()
        sleep(UPDATE)

    def test_properties(self):
        self.assertEquals("Some ID", self.device.Identifier)
        self.assertIn("Some status", self.device.status())
        self.assertEquals(DevState.ON, self.device.state())
        self.assertTrue(self.connection.called)
        callback = self.connection.call_args[1].get("callback")
        self.connection.assert_called_with(host='1.2.3.4',
                                           connection_timeout=2000,
                                           instrument_timeout=2000,
                                           callback_timeout=500,
                                           callback=callback)

    def test_states(self):
        self.attribute_pattern("ChannelEnabled", [False, True],
                               "get_channel_enabled", "set_channel_enabled")

    def test_coupling(self):
        self.attribute_pattern("ChannelCoupling", [0, 1],
                               "get_channel_coupling", "set_channel_coupling")

    def test_position(self):
        self.attribute_pattern("ChannelPosition", [-4.3, 1.25],
                               "get_channel_position", "set_channel_position")

    def test_scale(self):
        self.attribute_pattern("ChannelScale", [-4.3, 1.25],
                               "get_channel_scale", "set_channel_scale")

    def test_range(self):
        write_range = 0.1
        expected_args = -0.05, 0.05, 0
        read_scale = [x*0.1 for x in range(100)]
        # Write range
        self.assertEqual(self.device.TimeBase, self.empty)
        self.numpy.linspace.return_value = read_scale
        self.instrument.get_time_range.return_value = write_range
        self.device.TimeRange = write_range
        # Wait
        sleep(UPDATE)
        # Check
        arg = self.instrument.set_time_range.call_args[0][0]
        self.assertEqual(write_range, arg)
        self.numpy.linspace.assert_called_with(*expected_args)
        self.assertEqual(self.device.TimeBase.tolist(), read_scale)
        # Change read scale
        new_read_scale = [x*0.2 for x in range(100)]
        self.numpy.linspace.return_value = new_read_scale
        # Wait
        sleep(UPDATE)
        # No change detected
        self.assertEqual(self.device.TimeBase.tolist(), read_scale)
        # Change range return value
        write_range = 0.01
        expected_args = -0.005, 0.005, 0
        self.instrument.get_time_range.return_value = write_range
        # Wait
        sleep(UPDATE)
        # Change detected
        self.numpy.linspace.assert_called_with(*expected_args)
        self.assertEqual(self.device.TimeBase.tolist(), new_read_scale)

    def test_acquisition(self):
        # Check initial state
        for channel in range(1, 5):
            result = getattr(self.device, "Waveform"+str(channel))
            self.assertEqual(result, self.empty)
        # Start device
        self.assertEquals(DevState.ON, self.device.state())
        self.device.run()
        sleep(UPDATE)
        self.assertEquals(DevState.RUNNING, self.device.state())
        # Stop device
        self.device.stop()
        sleep(UPDATE)
        self.assertEquals(DevState.ON, self.device.state())
