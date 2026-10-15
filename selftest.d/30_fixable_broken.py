#!/usr/bin/env python3
# smoke-test: fixable
"""Self-test fixture: proves the fix -> RE-TEST path.

First check fails (the sentinel file is absent). The harness sees the static
`# smoke-test: fixable` marker, runs this file once with SMOKE_FIX=1 (the
bounded, idempotent fix creates the sentinel), then RE-TESTS. Second check
passes -> harness reports FIXED, not FAIL.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SENTINEL = os.path.join(HERE, ".selftest-sentinel")

mode = "fix" if os.environ.get("SMOKE_FIX") == "1" else "check"

if mode == "fix":
    with open(SENTINEL, "w", encoding="utf-8") as fh:
        fh.write("ok\n")
    sys.exit(0)

if os.path.exists(SENTINEL):
    print("sentinel present")
    sys.exit(0)

print("sentinel absent — a bounded fix would create it")
sys.exit(1)
