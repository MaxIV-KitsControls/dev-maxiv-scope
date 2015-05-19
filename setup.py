#!/usr/bin/env python

# Imports
import os
from setuptools import setup, Command


# Upload documentation on github
class UploadPages(Command):
    """Command to update build and upload sphinx doc to github."""
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Import fabric
        try:
            from fabric.api import local
        # Import subprocess
        except ImportError:
            from subprocess import call
            from functools import partial
            local = partial(call, shell=True)
        # Create gh-pages branch
        local('git checkout --orphan gh-pages ')
        # Unstage all
        local('rm .git/index')
        # Build doc
        local('python setup.py build_sphinx')
        # No jekyll file
        local('touch .nojekyll')
        local('git add .nojekyll')
        # Add Readme
        local('git add README.md')
        # Add html content
        local('git add docs/build/html/* -f ')
        # Move html content
        local('git mv docs/build/html/* ./ ')
        # Git commit
        local('git commit -m "build sphinx" ')
        # Git push
        local('git push --set-upstream github gh-pages -f ')
        # Back to master
        local('git checkout master -f ')
        # Delete branch
        local('git branch -D gh-pages ')


# Read function
def safe_read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname)).read()
    except IOError:
        return ""


# Setup
setup(name="tangods-scope",
      version="3.2.2",
      description="Device servers for the Rohde and Schwarz oscilloscopes.",
      author="Vincent Michel; Paul Bell",
      author_email="vincent.michel@maxlab.lu.se; paul.bell@maxlab.lu.se",
      license="GPLv3",
      url="http://www.maxlab.lu.se",
      long_description=safe_read("README.md"),
      packages=["scopedevice"],
      test_suite="nose.collector",
      scripts=["script/RTOScope", "script/RTMScope"],
      cmdclass={'upload_pages': UploadPages},
      )
