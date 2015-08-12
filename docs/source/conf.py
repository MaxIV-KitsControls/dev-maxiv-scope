# Imports
import sys
import os

# To find module
sys.path.insert(0, os.path.abspath('.'))

# Configuration
extensions = ['sphinx.ext.autodoc', 'devicedoc', 'sphinxcontrib.napoleon']
master_doc = 'index'

# Data
project = 'tangods-scope'
copyright = '2015, MAXIV'
release = '3.2.4'
