"""Test harness shim.

The top-level `custom_components/petlibro/__init__.py` imports from
`homeassistant.*`, which we don't install as a dev dep (it would pull in ~100
transitive packages for what are otherwise pure-Python unit tests).

This conftest puts the package directory itself on sys.path so tests can
import individual submodules (`schedule`, `coordinator` helpers, etc.)
directly, skipping the HA-coupled package `__init__`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).parent.parent / "custom_components" / "petlibro_lite"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))
