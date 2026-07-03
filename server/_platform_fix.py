"""Workaround for Python 3.13 Windows WMI hang in platform module.

On some Windows systems, platform.uname() triggers a WMI query via
_wmi.exec_query() that hangs indefinitely. This affects platform.machine(),
platform.node(), and other functions that depend on uname().

On CPython 3.13, uname_result.processor is a lazily-resolved cached
property that runs the same WMI query, so simply caching a uname_result
is not enough: platform.processor() or uname().processor would still
hang. This module pre-populates the cached property and patches
platform.processor() as well.

This module must be imported BEFORE any library that uses platform.machine()
(e.g., SQLAlchemy).
"""

import os
import platform
import socket
import struct
import sys

if sys.platform == "win32" and sys.version_info >= (3, 13):
    # Cache uname result with safe values to avoid WMI calls
    _bits = struct.calcsize("P") * 8
    _machine = "AMD64" if _bits == 64 else "x86"
    # PROCESSOR_IDENTIFIER is set by Windows itself — no WMI involved.
    _processor = os.environ.get("PROCESSOR_IDENTIFIER", _machine)

    _node = socket.gethostname()
    _cached = platform.uname_result(
        system="Windows",
        node=_node,
        release="",
        version="",
        machine=_machine,
    )
    # uname_result.processor is a functools.cached_property that resolves
    # via WMI on first access. Pre-populating the instance attribute makes
    # every later access return the plain value without any query.
    try:
        _cached.processor = _processor
    except (AttributeError, TypeError):
        # Future Python may make the attribute read-only; the
        # platform.processor patch below still protects direct calls.
        pass

    platform.uname = lambda: _cached
    platform.processor = lambda: _processor
