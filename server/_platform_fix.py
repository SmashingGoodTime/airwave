"""Workaround for Python 3.13 Windows WMI hang in platform module.

On some Windows systems, platform.uname() triggers a WMI query via
_wmi.exec_query() that hangs indefinitely. This affects platform.machine(),
platform.node(), and other functions that depend on uname().

This module must be imported BEFORE any library that uses platform.machine()
(e.g., SQLAlchemy).
"""

import platform
import struct
import sys

if sys.platform == "win32" and sys.version_info >= (3, 13):
    # Cache uname result with safe values to avoid WMI calls
    _bits = struct.calcsize("P") * 8
    _machine = "AMD64" if _bits == 64 else "x86"

    _node = __import__("socket").gethostname()
    _cached = platform.uname_result(
        system="Windows",
        node=_node,
        release="",
        version="",
        machine=_machine,
    )
    platform.uname = lambda: _cached
