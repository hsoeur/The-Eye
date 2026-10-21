"""The Eye - plateforme de supervision modulaire (stdlib uniquement, Python 3.9+)."""
__version__ = "2.0.0"

import sys as _sys
from pathlib import Path as _Path

# Dépendances natives (cryptography) installées hors-ligne depuis vendor/ par deploy.ps1 ; voir requirements.txt
_LIB = _Path(__file__).resolve().parents[1] / "lib"
if _LIB.is_dir() and str(_LIB) not in _sys.path:
    _sys.path.insert(0, str(_LIB))
