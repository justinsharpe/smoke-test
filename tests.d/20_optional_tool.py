#!/usr/bin/env python3
"""An optional dependency that may be absent: SKIP (exit 42), never FAIL."""
import shutil, sys
if shutil.which("gh"):
    print("gh present")
    sys.exit(0)
print("gh not installed")
sys.exit(42)
