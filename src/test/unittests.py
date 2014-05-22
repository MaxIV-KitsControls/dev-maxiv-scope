from unittest import TestCase

import numpy as np

from RohdeSchwarzRTO import channel_area_average


class RohdeSchwarzRTOUnitTestCase(TestCase):

    def test_channel_area_average_basic(self):
        vrange = 2.0
        tmp = np.zeros(1000)
        tmp[300:600] = -128
        area = channel_area_average([tmp for _ in xrange(10)], vrange/256)
        self.assertEqual(area, -300.0)

    def test_channel_area_average_range(self):
        vrange = 10.0
        tmp = np.zeros(1000)
        tmp[300:600] = -128
        area = channel_area_average([tmp for _ in xrange(10)], vrange/256)
        self.assertEqual(area, -1500.0)

    def test_channel_area_average_ignores_positive_values(self):
        vrange = 2.0
        tmp = np.zeros(1000)
        tmp[300:600] = -128
        #tmp[600:700] = 1
        area = channel_area_average([tmp for _ in xrange(10)], vrange/256)
        self.assertEqual(area, -300.0)
