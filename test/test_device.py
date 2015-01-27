"""Contain the tests for the RTM Scope."""

# Imports
import scope
from time import sleep
from mock import MagicMock
from PyTango import DevState
from devicetest import DeviceTestCase
from itertools import product

# Constants
READ = 0.001
UPDATE = 0.003
PRECISION = 5


# Note:
#
# Since the device uses an inner thread, it is necessary to
# wait during the tests in order the let the device update itself.
# Hence, the sleep calls have to be secured enough not to produce
# any inconsistent behavior. However, the unittests need to run fast.
# Here, we use a factor 3 between the read period and the sleep calls.


# Device test case
class ScopeDeviceTestCase(DeviceTestCase):
    """Test case for packet generation."""

    device = scope.Scope
    properties = {'Instrument': '1.2.3.4'}
    empty = None  # Should be []

    def assertEquals(self, arg1, arg2):
        if isinstance(arg1, float) or isinstance(arg2, float):
            DeviceTestCase.assertAlmostEquals(self, arg1, arg2,
                                              places=PRECISION)
        else:
            DeviceTestCase.assertEquals(self, arg1, arg2)

    @staticmethod
    def gen_update_func(dct):
        def update_states(states):
            states.clear()
            states.update(dct)
            return range(1, 5)
        return update_states

    def attribute_pattern(self, attr, values, read, write,
                          func=None, update=False):
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
            # Apply func
            if func:
                for key, value in write_dct.items():
                    write_dct[key] = func(value)
            # Update
            if update:
                update_func = self.gen_update_func(write_dct)
                setattr(self.instrument, read, update_func)
            else:
                update_func = getattr(self.instrument, read)
                update_func.return_value = write_dct
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
        cls.numpy = scope.numpy = MagicMock()
        cls.numpy.linspace.return_value = []
        # Mock rtm library
        cls.connection = scope.Scope.intrument_class = MagicMock()
        cls.instrument = cls.connection.return_value
        # Set up
        scope.Scope.events = False
        scope.Scope.minimal_period = READ
        cls.instrument.getOperCond.return_value = "Some status."
        cls.instrument.getIDN.return_value = "Some ID"

    def setUp(self):
        """Let the inner thread initialize the device."""
        DeviceTestCase.setUp(self)
        sleep(UPDATE)

    def test_properties(self):
        self.assertEquals("Some ID", self.device.IDN)
        self.assertIn("Some status", self.device.status())
        self.assertEquals(DevState.ON, self.device.state())
        self.connection.assert_called_with('1.2.3.4', 8000, 8000)

    def test_states(self):
        self.attribute_pattern("stateCh", [False, True],
                               "updateChanStates", "setChanState", update=True)

    def test_coupling(self):
        self.attribute_pattern("couplingCh", ["AC", "DC"],
                               "updateCoupling", "setCoupling", update=True)

    def test_position(self):
        self.attribute_pattern("positionCh", [-4.3, 1.25],
                               "getVPositionAll", "setVPosition")

    def test_scale(self):
        func = lambda arg: 8*arg
        self.attribute_pattern("vScaleCh", [-4.3, 1.25],
                               "getVRangeAll", "setVScale", func=func)

    def test_range(self):
        write_range = 0.1
        expected_args = -0.05, 0.05, 0
        read_scale = [x*0.1 for x in range(100)]
        # Write range
        self.assertEqual(self.device.TimeScale, self.empty)
        self.numpy.linspace.return_value = read_scale
        self.instrument.getHRange.return_value = write_range
        self.device.hRange = write_range
        # Wait
        sleep(UPDATE)
        # Check
        arg = self.instrument.setHRange.call_args[0][0]
        self.assertEqual(write_range, arg)
        self.assertEqual(self.device.TimeScale.tolist(), read_scale)
        self.numpy.linspace.assert_called_with(*expected_args)
        # Change read scale
        new_read_scale = [x*0.2 for x in range(100)]
        self.numpy.linspace.return_value = new_read_scale
        # Wait
        sleep(UPDATE)
        # No change detected
        self.assertEqual(self.device.TimeScale.tolist(), read_scale)
        # Change range return value
        write_range = 0.01
        expected_args = -0.005, 0.005, 0
        self.instrument.getHRange.return_value = write_range
        # Wait
        sleep(UPDATE)
        # Change detected
        self.numpy.linspace.assert_called_with(*expected_args)
        self.assertEqual(self.device.TimeScale.tolist(), new_read_scale)

    def test_acquisition(self):
        # Check initial state
        for channel in range(1, 5):
            result = getattr(self.device, "WaveFormDataCh"+str(channel))
            self.assertEqual(result, self.empty)
        # Start device
        self.assertEquals(DevState.ON, self.device.state())
        self.device.start()
        self.assertEquals(DevState.RUNNING, self.device.state())
        # Stop device
        self.device.stop()
        self.assertEquals(DevState.ON, self.device.state())
