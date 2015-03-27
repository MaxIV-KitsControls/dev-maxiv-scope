tangods-scope
=============

Device servers for oscilloscopes.

Provide a standard interface along with devices
for RTO and RTM oscilloscopes.

Information
-----------

 - Package: tangods-scope
 - Import:  scopedevice
 - Servers: RTMScope, RTOScope
 - Devices: RTMScope, RTOScope
 - Repo:    [dev-maxiv-scope][scope]

[scope]: https://github.com/MaxIV-KitsControls/dev-maxiv-scope/

Requirement
-----------

 - library: [lib-maxiv-rohdescope][rohdescope] >= 0.4.2

[rohdescope]: https://github.com/MaxIV-KitsControls/lib-maxiv-rohdescope

Unit testing
------------

Run:

    $ python setup.py nosetests

See the [devicetest][test] library.

[test]: https://github.com/vxgmichel/python-tango-devicetest

Documentation
-------------

A sphinx generated documentation is available [here][pages].

To build it manually, run:

    $ python setup.py build_sphinx
    $ sensible-browser docs/build/html/index.html

See the [devicedoc][doc] library.

[pages]: http://maxiv-kitscontrols.github.io/dev-maxiv-scope/
[doc]: https://github.com/vxgmichel/python-tango-devicedoc

Contact
-------

- Vincent Michel: vincent.michel@maxlab.lu.se
- Paul Bell:      paul.bell@maxlab.lu.se
