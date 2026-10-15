# smoke-test — a self-healing drop-in smoke-test harness

A consolidated **test → bounded fix → RE-TEST → report** harness with
`skip != fail` exit semantics and a drop-in test directory. Stdlib-only,
platform-agnostic (macOS / Linux / Windows).

## Why this exists (the failure class)

Most "health check" setups have the same three holes, and they compound:

1. **A check reports, but nobody fixes.** The script prints red and the human
   is expected to notice and act. Nothing closes the loop.
2. **A missing optional dependency reads as a failure.** The check for "is the
   optional tool present" exits non-zero, so a machine that simply doesn't
   *need* the tool looks broken.
3. **An auto-fix is trusted blind.** A script "fixes" something and reports
   success without ever re-running the check — so a fix that did nothing (or
   made it worse) ships as green.

This harness closes all three: a fix runs only after a check is *confirmed*
broken, is bounded (only tests that declare themselves fixable, one attempt,
hard timeout), and is **always followed by a RE-TEST** that decides the final
outcome. A fix is never trusted blind.

## The contract

```
test  →  ONLY IF BROKEN apply a BOUNDED fix  →  RE-TEST  →  report
```

- **Drop-in directory** of test scripts (`tests.d/` by default). Every test is
  **idempotent** and **timeout-bounded**.
- Each test yields exactly one of **PASS / FAIL / SKIP**.
  - A **missing prerequisite is SKIP, never FAIL**.
- A fix runs **only after a check is confirmed broken**, is **bounded**
  (only tests that declare themselves fixable; one attempt; hard timeout), and
  is **always followed by a RE-TEST** that decides the final outcome.
- **Exit code == the number of unfixed failures** (`0` == all green).
- A **summary report is written to a file**.

## Requirements

Python 3.8+. Standard library only.

## Usage

```sh
python3 smoke_test.py --dir tests.d                 # run the real checks
python3 smoke_test.py --dir selftest.d              # run the harness self-tests
python3 smoke_test.py --dir tests.d --no-fix        # report-only, never fix
python3 smoke_test.py --dir tests.d --only 20_optional_tool
python3 smoke_test.py --dir tests.d --list          # list discovered tests
```

| Flag | Default | Meaning |
|---|---|---|
| `--dir` | `tests.d` | drop-in test directory |
| `--report` | `smoke-test-report.md` | summary report file |
| `--log` | `smoke-test.log` | append-only JSONL log |
| `--timeout` | `10` | per-test timeout (s); overridable per test |
| `--no-fix` | off | never attempt fixes |
| `--only NAME…` | all | run a subset |
| `--list` | — | list discovered tests and exit |
| `--quiet` | off | suppress the stdout table (still writes report/log) |

## Writing a drop-in test

Any executable file in `--dir` (`.py`, `.sh`, `.bash`, or a shebang'd
executable). Name it `NN_something` — the filename stem becomes the test name
and tests run in sorted order.

**Exit-code protocol:**

| Exit | Status |
|---|---|
| `0` | **PASS** |
| `42` | **SKIP** (missing prerequisite) |
| other | **FAIL** |

The first non-empty stdout/stderr line becomes the one-line detail.

**Optional static markers** (scanned in the first 30 lines of the *file*):

```
# smoke-test: fixable           → the harness may run this file with SMOKE_FIX=1
# smoke-test: timeout=30        → per-test timeout in seconds
```

A *fixable* test performs its own bounded, idempotent fix when it sees
`SMOKE_FIX=1`. Env passed to every test: `SMOKE_CHECK`/`SMOKE_FIX`,
`SMOKE_TEST_NAME`, `SMOKE_DIR`.

### The fix protocol (why it is safe)

The harness **never executes a command parsed out of a test's output**.
Fixability is a **static** marker in the test's own source; the fix is the
test's own code, gated by an env var. On a confirmed failure the harness:

1. runs the file once with `SMOKE_FIX=1` (bounded by the same timeout),
2. **re-runs** it with `SMOKE_CHECK=1`,
3. reports **FIXED** only if the re-test passes — a fix is never trusted blind.

## What lives here

| Path | What |
|---|---|
| `smoke_test.py` | the harness (runner, discover, fix/re-test, report) |
| `tests.d/` | example drop-in checks (one pass, one skip) |
| `selftest.d/` | harness **self-tests** proving pass / skip / fixable→fixed / hard-fail / timeout |

## Validation

Harness self-test (`--dir selftest.d`), exit **2** (expected — two deliberate
unfixed failures):

```
[ ok ] 10_pass              — always green
[skip] 20_skip              — no optional dependency on this host
[ fix] 30_fixable_broken    — sentinel present        (FAIL → fix → RE-TEST → PASS)
[FAIL] 40_hard_fail         — deliberate unfixable failure
[FAIL] 50_timeout           — timed out after 2s       (per-test timeout bounded)
Results: 1/5 passed, 1 auto-fixed, 1 skipped, 2 failed
Exit code (= unfixed failures): 2
```

Run it with:

```bash
python3 smoke_test.py --dir selftest.d
```

## Anti-patterns (kept)

- ❌ Running on **every turn**. Post-restart + a periodic sweep is plenty.
- ❌ A drop-in with **no timeout** on a command that could hang — one hung
  test stalls the suite; the harness kills it, but declare tight budgets.
- ❌ **Auto-fixing without confirming broken first** — the
  `check → broken? → fix → RE-TEST` loop is the contract.
- ❌ Treating **SKIP as FAIL** — missing prereqs are skips; the exit code
  counts real failures only.
- ❌ **Hardcoding paths** in a drop-in — read env so the script travels across
  hosts.

## License

MIT — see [LICENSE](LICENSE).
