"""Pytest configuration."""

import os
import tempfile
from pathlib import Path

# Force a per-process temp data dir so tests can never touch the real
# %LOCALAPPDATA%\WIA database — even if the developer has WIA_DATA_DIR
# already exported in their shell. We use ``os.environ[...] = ...`` (not
# ``setdefault``) so an inherited value cannot bleed in.
_test_data_dir = Path(tempfile.gettempdir()) / f"wia-tests-{os.getpid()}"
_test_data_dir.mkdir(parents=True, exist_ok=True)
os.environ["WIA_DATA_DIR"] = str(_test_data_dir)
