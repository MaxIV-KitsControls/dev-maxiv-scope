# This functional tests requires the hw to be connected!

import unittest
import PyTango
import time


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
