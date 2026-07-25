"""Shared test setup for EMIOS.

The project is intentionally runnable from the repository root.  Keeping the
backend directory on ``sys.path`` here makes direct ``pytest`` runs and CI
runs behave the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
