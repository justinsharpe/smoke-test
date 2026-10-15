#!/usr/bin/env python3
# smoke-test: timeout=2
"""Self-test fixture: proves per-test timeout bounding.

Sleeps far longer than its declared 2s budget; the harness must kill it and
report FAIL 'timed out', never hang the whole suite.
"""
import sys
import time

print("about to hang (should be killed at 2s)")
sys.stdout.flush()
time.sleep(30)
sys.exit(0)
