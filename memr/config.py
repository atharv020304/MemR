
"""
═══════════════════════════════════════════════════════════════
memr/config.py — Path resolution and defaults
═══════════════════════════════════════════════════════════════
"""

import os
from pathlib import Path


def resolve_memory_root(explicit: str | None = None) -> str:
    """
    Resolve the memory root directory. Priority:
      1. Explicit argument (from CLI or constructor)
      2. MEMR_PATH environment variable
      3. .memr/ in the current working directory
    """
    if explicit:
        return str(Path(explicit).resolve())
    if env := os.getenv("MEMR_PATH"):
        return str(Path(env).resolve())
    return str(Path.cwd() / ".memr")


# Default limits
DEFAULT_SESSION_TOKEN_LIMIT = 8000
DEFAULT_PER_CALL_TOKEN_LIMIT = 4000
DEFAULT_TOKEN_RESERVE = 1000
