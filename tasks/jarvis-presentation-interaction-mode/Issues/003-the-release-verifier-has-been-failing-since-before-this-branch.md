# Issue 003 — `scripts/verify_release.py` has been failing since before this branch

| | |
| --- | --- |
| Raised by | Slice 11 implementer, 2026-09-24 |
| Status | open, **not** this task's to fix |
| Severity | medium — a release gate that always fails is a release gate nobody runs |
| Surface | `scripts/verify_release.py` (the rule) / `jarvis/runtime/barehands_replay.py:144` (the hit) |
| Pre-existing | **yes**, proven on HEAD's own blobs |

## What happens

`scripts/verify_release.py` scans every `.py` under `jarvis/`, minus a two-file
allow-list, for three substrings — `subprocess.run(`, `os.system(`,
`shell=True` — and fails the release on any hit:

```python
source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "jarvis").rglob("*.py") if p not in tooling)
dangerous = ["subprocess.run(", "os.system(", "shell=True"]
for needle in dangerous:
    if needle in source:
        fail(f"dangerous execution primitive in Jarvis package: {needle}")
```

`jarvis/runtime/barehands_replay.py:144` contains one:

```python
done = subprocess.run([binary, str(script)], capture_output=True, text=True, ...)
```

It is not in the allow-list, which names only `speaker_benchmark.py` and
`speaker_benchmark_fixtures.py`. So the verifier fails, and has failed for as
long as that line has existed.

## The evidence that it is not Slice 11's

Scanned over `git ls-tree -r HEAD jarvis/`, i.e. the committed blobs at the
branch point, minus the same two tooling files:

```
HEAD violations of the verifier's 'dangerous execution primitive' rule:
  jarvis/runtime/barehands_replay.py: subprocess.run(
count: 1
```

Exactly one, and it is not a file this task touches. Slice 11's own sub-agent
launcher uses `asyncio.create_subprocess_exec`, the primitive
`jarvis/runtime/claude_local.py` already uses and which the rule deliberately
does not name.

## Why it was not fixed here

Adding a file to a security allow-list widens a gate. That is a judgement about
what `barehands_replay.py` is allowed to do, not a rollout decision, and "the
declared baseline is not yours to fix" is this task's own rule. It is raised
rather than normalised.

## What the other six gates say

Run one by one, with the verifier's pytest step stubbed (the single process is
killed by this machine's memory reaper):

| Gate | Result |
| --- | --- |
| no provider/runtime import in `jarvis/core` | pass |
| benchmark tooling allow-list points at real files | pass |
| benchmark tooling never imported by production | pass |
| **no dangerous execution primitive in `jarvis/`** | **FAIL** |
| no dangerous primitive in the benchmark tooling | pass |
| third-party runtime sources are pinned | pass |
| privacy logging disabled by default | pass |

## Options, for whoever picks this up

1. **Add `barehands_replay.py` to the tooling allow-list**, as
   `speaker_benchmark.py` was, with the same kind of written argument (fixed
   argv, no shell, off the execution path) and a test pinning that nobody
   imports it from production. Cheapest, and it keeps the rule total elsewhere.
2. **Move it to `asyncio.create_subprocess_exec`**, the primitive the rest of
   the repository uses. Larger, and it changes a synchronous helper into an
   async one.
3. **Decide the rule is wrong** and scope it to production modules only. Widest
   blast radius; not recommended without measuring what else it would let past.

Whichever is chosen, `docs/ACCEPTANCE_STATUS.md` says "release verifier passed"
of a 2026-09-12 run, and that sentence should be dated or corrected: it is not
true of this tree.
