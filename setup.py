#!/usr/bin/env python
from distutils.core import setup
setup(name = 'tangods-scope',
      version = '1.0',
      description = 'Tango device for Rohde and Schwarz RTO 1004 oscilloscope',
      package_dir = {'RohdeSchwarzRTO':'src'},
      packages = ['RohdeSchwarzRTO'],
      author='Paul Bell',
      scripts = ['scripts/RohdeSchwarzRTO'],
      )
