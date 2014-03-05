#!/usr/bin/env python
from distutils.core import setup
setup(name = 'tangods-scope',
      version = '0.1',
      description = 'Tango device for Rohde and Schwarz RTO 1004 oscilloscope',
      packages = ['RohdeSchwarzRTO'],
      author='Paul Bell',
      scripts = ['scripts/Scope'],
      package_dir = {'RohdeSchwarzRTO' : 'src'},
      )
