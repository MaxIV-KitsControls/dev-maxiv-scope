tangods-scope
=============
***

Device servers for the Rohde and Schwarz oscilloscopes.


Information
-----------

 - Package: tangods-scope
 - Servers: RTMScope, RTOScope
 - Devices: RTMScope, RTOScope
 - Repo:    [dev-maxiv-scope][repo]

[repo]: https://gitorious.maxlab.lu.se/kits-maxiv/dev-maxiv-scope/

Unit testing
------------

Run:

    $ python setup.py nosetests

See the [devicetest][test] library.

[test]: https://github.com/vxgmichel/python-tango-devicetest


Documentation
-------------

Run:

    $ python setup.py build_sphinx
    $ sensible-browser docs/build/html/index.html

See the [devicedoc][doc] library.

[doc]: https://github.com/vxgmichel/python-tango-devicedoc


Contact
-------

Vincent Michel: vincent.michel@maxlab.lu.se
Paul Bell:      paul.bell@maxlab.lu.se