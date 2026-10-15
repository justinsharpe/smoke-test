#!/usr/bin/env python3
"""Self-test fixture: an UNFIXABLE failure. Proves exit code == failure count.

Not marked fixable on purpose, so the harness never attempts a fix and this
counts toward the exit code.
"""
import sys

print("deliberate unfixable failure (harness self-test)")
sys.exit(1)
