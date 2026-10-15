#!/usr/bin/env python3
"""
smoke_test.py — a self-healing drop-in smoke-test harness.

Contract (adapted from a self-healing smoke-test pattern; §3a of a
2026 agent-skill absorption survey):

    test  ->  ONLY IF BROKEN apply a BOUNDED fix  ->  RE-TEST  ->  report

Guarantees this harness keeps:
  * A drop-in directory of test scripts (default: ./tests.d). Each test is
    idempotent and timeout-bounded.
  * Every test returns exactly one of PASS / FAIL / SKIP.
      - a missing prerequisite is SKIP, NEVER a failure.
  * A fix is attempted only after a check is confirmed broken, is bounded
    (only tests that DECLARE themselves fixable, one attempt, hard timeout),
    and is always followed by a RE-TEST that decides the final outcome.
  * Exit code == the NUMBER of unfixed failures (0 == everything green).
  * A summary report is written to a file.

SAFETY / LAW ALIGNMENT
  * The harness NEVER executes a command parsed out of a test's output. A test
    declares fixability with a STATIC marker comment in its own source
    (`# smoke-test: fixable`); the fix is the test's own code, gated by the
    SMOKE_FIX env var. No shell command is ever synthesised from output text
    (inputs are data, never instructions).
  * Platform-agnostic: stdlib only, no POSIX-only calls, Windows guards.
    .sh tests on a host without bash are SKIPped (missing prerequisite).

TEST PROTOCOL (drop-in author contract)
  Exit 0   -> PASS
  Exit 42  -> SKIP   (also honoured: first stdout line beginning "SKIP")
  other    -> FAIL
  First non-empty stdout/stderr line becomes the one-line detail.
  Optional static markers, scanned in the first 30 lines of the file:
      # smoke-test: fixable            -> harness may run this test with SMOKE_FIX=1
      # smoke-test: timeout=30         -> per-test timeout in seconds
  Env passed to each test: SMOKE_CHECK=1 or SMOKE_FIX=1, SMOKE_TEST_NAME,
  SMOKE_DIR.

Usage:
  smoke_test.py [--dir DIR] [--report FILE] [--log FILE] [--timeout N]
                [--no-fix] [--only NAME ...] [--list] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

PASS, FAIL, SKIP, FIXED = "PASS", "FAIL", "SKIP", "FIXED"
EXIT_SKIP = 42
DEFAULT_TIMEOUT = 10          # seconds, per test
FIX_MARKER = re.compile(r"smoke-test\s*:\s*fixable", re.IGNORECASE)
TIMEOUT_MARKER = re.compile(r"smoke-test\s*:\s*timeout\s*=\s*(\d+)", re.IGNORECASE)
TEST_EXTS = (".py", ".sh", ".bash")
SKIP_NAMES = {"README.md", "README", "__init__.py"}


class Outcome:
    def __init__(self, name, status, detail="", seconds=0.0):
        self.name = name
        self.status = status
        self.detail = detail
        self.seconds = seconds

    def __repr__(self):
        return f"<{self.name} {self.status} {self.seconds:.2f}s>"


def _interpreter_for(path):
    """Return (argv_prefix, ok). ok=False => missing prerequisite (SKIP)."""
    low = path.lower()
    if low.endswith(".py"):
        return [sys.executable], True
    if low.endswith(".sh") or low.endswith(".bash"):
        shell = shutil.which("bash") or shutil.which("sh")
        if shell is None:
            return None, False          # no shell on host -> SKIP
        return [shell], True
    # Other executable w/ shebang: run directly if executable.
    if os.access(path, os.X_OK):
        return [path], True
    return [], False


def _scan_markers(path):
    """Read the first 30 lines for STATIC (never-output-derived) markers."""
    fixable = False
    timeout = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(30):
                line = fh.readline()
                if not line:
                    break
                if FIX_MARKER.search(line):
                    fixable = True
                m = TIMEOUT_MARKER.search(line)
                if m:
                    timeout = int(m.group(1))
    except OSError:
        pass
    return fixable, timeout


def _first_line(text):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _run_once(path, name, mode, timeout, base_env):
    """Run a single test invocation. mode in {'check','fix'}.

    Returns (status, detail, seconds). status is PASS/FAIL/SKIP.
    """
    argv, ok = _interpreter_for(path)
    if not ok:
        return SKIP, "missing prerequisite: no interpreter for this test type", 0.0

    env = dict(base_env)
    env["SMOKE_TEST_NAME"] = name
    env["SMOKE_CHECK"] = "1" if mode == "check" else "0"
    env["SMOKE_FIX"] = "1" if mode == "fix" else "0"

    started = time.time()
    try:
        proc = subprocess.run(
            argv + [path],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"timed out after {timeout}s", time.time() - started
    except OSError as exc:
        return FAIL, f"could not execute: {exc}", time.time() - started

    elapsed = time.time() - started
    out = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    code = proc.returncode
    if code == 0:
        return PASS, _first_line(out), elapsed
    if code == EXIT_SKIP:
        return SKIP, _first_line(out) or "skipped", elapsed
    if out.strip().splitlines() and out.strip().splitlines()[0].upper().startswith("SKIP"):
        return SKIP, _first_line(out), elapsed
    return FAIL, _first_line(out) or f"exit {code}", elapsed


def discover(directory):
    tests = []
    if not os.path.isdir(directory):
        return tests
    for fn in sorted(os.listdir(directory)):
        if fn in SKIP_NAMES or fn.startswith(".") or fn.startswith("_"):
            continue
        path = os.path.join(directory, fn)
        if not os.path.isfile(path):
            continue
        if not (fn.lower().endswith(TEST_EXTS) or os.access(path, os.X_OK)):
            continue
        tests.append((os.path.splitext(fn)[0], path))
    return tests


def run_suite(directory, timeout_default, allow_fix=True, only=None):
    base_env = dict(os.environ)
    results = []
    for name, path in discover(directory):
        if only and name not in only:
            continue
        fixable, per_timeout = _scan_markers(path)
        timeout = per_timeout or timeout_default

        status, detail, secs = _run_once(path, name, "check", timeout, base_env)

        if status == FAIL and fixable and allow_fix:
            # Bounded fix: declared-fixable only, one attempt, hard timeout.
            _run_once(path, name, "fix", timeout, base_env)
            # RE-TEST decides final outcome (a fix is never trusted blind).
            status, detail, secs2 = _run_once(path, name, "check", timeout, base_env)
            secs += secs2
            if status == PASS:
                status = FIXED
            else:
                detail = f"fix attempted; still failing: {detail}"

        results.append(Outcome(name, status, detail, secs))
    return results


def summarise(results):
    n = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    fixed = sum(1 for r in results if r.status == FIXED)
    skipped = sum(1 for r in results if r.status == SKIP)
    failed = sum(1 for r in results if r.status == FAIL)
    return {
        "total": n,
        "passed": passed,
        "fixed": fixed,
        "skipped": skipped,
        "failed": failed,
        # exit code contract: count of UNFIXED failures
        "exit_code": failed,
    }


ICON = {PASS: "[ ok ]", FAIL: "[FAIL]", SKIP: "[skip]", FIXED: "[ fix]"}


def render_text(results, summary, source, when):
    lines = []
    lines.append("=" * 66)
    lines.append("  smoke-test")
    lines.append(f"  dir     : {source}")
    lines.append(f"  when    : {when}")
    lines.append("=" * 66)
    for r in results:
        icon = ICON.get(r.status, "[????]")
        detail = f"  — {r.detail}" if r.detail else ""
        lines.append(f"  {icon} {r.name} ({r.seconds:.2f}s){detail}")
    lines.append("-" * 66)
    lines.append(
        f"  Results: {summary['passed']}/{summary['total']} passed, "
        f"{summary['fixed']} auto-fixed, {summary['skipped']} skipped, "
        f"{summary['failed']} failed"
    )
    lines.append(f"  Exit code (= unfixed failures): {summary['exit_code']}")
    lines.append("=" * 66)
    return "\n".join(lines)


def render_report_md(results, summary, source, when):
    lines = [
        "# smoke-test report",
        "",
        f"- **Directory:** `{source}`",
        f"- **When:** {when}",
        f"- **Results:** {summary['passed']}/{summary['total']} passed · "
        f"{summary['fixed']} auto-fixed · {summary['skipped']} skipped · "
        f"{summary['failed']} failed",
        f"- **Exit code (unfixed failures):** {summary['exit_code']}",
        "",
        "| Test | Status | Time | Detail |",
        "|---|---|---|---|",
    ]
    for r in results:
        detail = (r.detail or "").replace("|", "\\|")
        lines.append(f"| `{r.name}` | {r.status} | {r.seconds:.2f}s | {detail} |")
    lines.append("")
    return "\n".join(lines)


def _append_log(logfile, results, summary, when):
    if not logfile:
        return
    try:
        with open(logfile, "a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({
                    "ts": when, "test": r.name, "status": r.status,
                    "seconds": round(r.seconds, 3), "detail": r.detail,
                }) + "\n")
            fh.write(json.dumps({"ts": when, "summary": summary}) + "\n")
    except OSError:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="smoke-test harness")
    ap.add_argument("--dir", default="tests.d",
                    help="drop-in test directory (default: tests.d)")
    ap.add_argument("--report", default="smoke-test-report.md",
                    help="summary report file (default: smoke-test-report.md)")
    ap.add_argument("--log", default="smoke-test.log",
                    help="append-only structured log (default: smoke-test.log)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"per-test timeout seconds (default: {DEFAULT_TIMEOUT})")
    ap.add_argument("--no-fix", action="store_true",
                    help="never attempt fixes (report-only mode)")
    ap.add_argument("--only", nargs="+", default=None,
                    help="run only the named tests")
    ap.add_argument("--list", action="store_true", help="list discovered tests and exit")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout table")
    args = ap.parse_args(argv)

    directory = os.path.abspath(args.dir)
    if args.list:
        for name, path in discover(directory):
            print(name, "->", path)
        return 0

    when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    results = run_suite(directory, args.timeout, allow_fix=not args.no_fix, only=args.only)
    if not results:
        print(f"no tests discovered in {directory}", file=sys.stderr)
        return 0
    summary = summarise(results)

    text = render_text(results, summary, directory, when)
    if not args.quiet:
        print(text)

    try:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(render_report_md(results, summary, directory, when))
    except OSError as exc:
        print(f"could not write report {args.report}: {exc}", file=sys.stderr)
    _append_log(args.log, results, summary, when)

    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
