# Imports
import sys
import os

# To find module
sys.path.insert(0, os.path.abspath('.'))

# Configuration
extensions = ['sphinx.ext.autodoc', 'devicedoc', 'sphinxcontrib.napoleon']
master_doc = 'index'

# Data
project = u'dev-maxiv-scope'
copyright = u'2014, MAXIV'
release = '3.0.1'
