#!/usr/bin/env python3
"""A modern Python 3 runtime is present."""
import sys
if sys.version_info >= (3, 8):
    print(f"python {sys.version.split()[0]}")
    sys.exit(0)
print("python too old")
sys.exit(1)
