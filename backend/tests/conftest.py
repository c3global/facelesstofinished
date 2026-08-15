"""Add /app/backend to sys.path for all backend tests.

This lets tests use bare imports like ``from render_runtime import ...``
or ``from providers.registry import ...`` regardless of the pytest
invocation directory. Previously the tests only ran cleanly when pytest
was called from /app/backend/; running from /app failed to collect the
watchdog test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
