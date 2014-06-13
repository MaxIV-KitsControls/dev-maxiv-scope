# This functional tests requires the hw to be connected!

import unittest
import PyTango
import time
from mock import patch
import numpy as np

from RohdeSchwarzRTO import channel_area_average


class  RohdeSchwarzRTO_TestCase(unittest.TestCase):

    def setUp(self):
        """ create RTO scope device """
        self.device = PyTango.DeviceProxy("scope/rohdeschwarz/rto-1024")
        self.device.On()
        #in case already running
        self.device.Stop()

    def test_start(self):
        message = """ Changing state to running """
        expected=PyTango.DevState.RUNNING
        self.device.Start()
        actual=self.device.State()
        self.assertEqual(expected, actual,message)

    def test_stop(self):
        expected=PyTango.DevState.ON
        self.device.Stop()
        actual=self.device.State()
        self.assertEqual(expected, actual)

    def test_standby(self):
        expected=PyTango.DevState.STANDBY
        self.device.Standby()
        actual=self.device.State()
        self.assertEqual(expected, actual)

    def test_hscale(self):
        expected=0.01
        self.device.write_attribute("HScale", expected)
        actual=self.device.HScale
        self.assertEqual(expected, actual)

    def test_vscales(self):
        expected1=0.05
        expected2=0.05
        expected3=0.05
        expected4=0.05
        self.device.write_attribute("VScaleCh1", expected1)
        self.device.write_attribute("VScaleCh2", expected2)
        self.device.write_attribute("VScaleCh3", expected3)
        self.device.write_attribute("VScaleCh4", expected4)
        actual1=self.device.VScaleCh1
        actual2=self.device.VScaleCh2
        actual3=self.device.VScaleCh3
        actual4=self.device.VScaleCh4
        self.assertEqual(expected1, actual1)
        self.assertEqual(expected2, actual2)
        self.assertEqual(expected3, actual3)
        self.assertEqual(expected4, actual4)


class CTTestCase(unittest.TestCase):

    def test_channel_area_average_normal(self):
        """The CT area calculation returns the average waveform area"""
        wfs = [(0, np.array([-1., -2., -3.])),
               (1, np.array([-2., -3., -4.])),
               (2, np.array([-3., -4., -5.]))]
        vscale = 0.1
        window = 5.0
        t = 3.0
        res = channel_area_average(wfs, vscale, t, window)
        self.assertEqual(res, -(6 + 9 + 12)*vscale/window)

    def test_channel_area_average_discards_positive(self):
        """The calculation discards positive values
        (treat them as zero in the summing)"""
        wfs = [(0, np.array([-1., -2., 3.])),  # -3
               (1, np.array([2., -3., -4.])),  # -7
               (2, np.array([-3., 4., -5.]))]  # -8
        vscale = 0.1
        window = 5.0
        t = 3.0
        res = channel_area_average(wfs, vscale, t, window)
        self.assertEqual(res, vscale * -(3+7+8) / window)

    def test_channel_area_average_respects_time_window(self):
        "Values older than window seconds are not included in the average."
        wfs = [(0, np.array([-1., -2., 3.])),  # -3
               (1, np.array([2., -3., -4.])),  # -7
               (2, np.array([-3., 4., -5.]))]  # -8
        vscale = 0.1
        window = 2.5
        t = 3.0
        res = channel_area_average(wfs, vscale, t, window)
        self.assertEqual(res, vscale * -(8 + 7) / window)

    def test_channel_area_average_no_shots(self):
        """Return zero if there are no shots within the time window"""
        wfs = []
        vscale = 0.1
        window = 2.5
        t = 3.0
        res = channel_area_average(wfs, vscale, t, window)
        self.assertEqual(res, 0)
