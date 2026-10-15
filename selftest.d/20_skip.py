#!/usr/bin/env python3
"""Self-test fixture: the SKIP case (exit 42). Missing prereq != failure."""
import sys

print("no optional dependency on this host")
sys.exit(42)
