"""Module to run the server."""

# Imports
import sys
from PyTango import server
from scopedevice.device import RTOScope, RTMScope

#: Server name as used in the Tango database
RTO_NAME = "RTOScope"

#: Server name as used in the Tango database
RTM_NAME = "RTMScope"


# Run function
def run_rto(args=None, **kwargs):
    """Run the RTO oscilloscope.
    It is based on the PyTango.server.run method.

    The diffrence is that the device class
    and server name are automatically given.

    Args:
        args (iterable): args as given in the PyTango.server.run method
                         without the server name. If None, the sys.argv
                         list is used
        kwargs: the other keywords argument are as given
                in the PyTango.server.run method.
    """
    if not args:
        args = sys.argv[1:]
    args = [RTO_NAME] + list(args)
    server.run((RTOScope,), args, **kwargs)


# Run function
def run_rtm(args=None, **kwargs):
    """Run the RTM oscilloscope.
    It is based on the PyTango.server.run method.

    The diffrence is that the device class
    and server name are automatically given.

    Args:
        args (iterable): args as given in the PyTango.server.run method
                         without the server name. If None, the sys.argv
                         list is used
        kwargs: the other keywords argument are as given
                in the PyTango.server.run method.
    """
    if not args:
        args = sys.argv[1:]
    args = [RTM_NAME] + list(args)
    server.run((RTMScope,), args, **kwargs)


# Run function
def run(args=None, scope="", **kwargs):
    """Run an oscilloscope from a given scope type.
    It is based on the PyTango.server.run method.

    The diffrence is that the device class
    and server name are automatically given.

    Args:
        args (iterable): args as given in the PyTango.server.run method
                         without the server name. If None, the sys.argv
                         list is used
        scope (str): "RTO", "RTM" or "" to use sys.argv instead
        kwargs: the other keywords argument are as given
                in the PyTango.server.run method.
    """
    # RTO run
    try:
        if scope.lower() != "rto":
            sys.argv.remove("--rto")
        return run_rto(args, **kwargs)
    except ValueError:
        pass
    # RTM run
    try:
        if scope.lower() != "rtm":
            sys.argv.remove("--rtm")
        return run_rtm(args, **kwargs)
    except ValueError:
        pass
    # Help
    if scope is not None:
        raise ValueError("Not a valid scope.")
    print("Use --rto or --rtm options to select the scope type")


# Main execution
if __name__ == "__main__":
    run()
