---
applyTo: "**"
---
# Atomic Commits

Each commit must represent exactly one logical change. Never mix different types of changes.

## What belongs in separate commits

- Production code changes
- Test changes
- Documentation updates
- Agent instruction updates
- Changelog entries
- Configuration / CI changes

## Forbidden in commits

Never commit temporary planning or analysis files:
- `ARCHITECTURE_ANALYSIS.md`, `TASK_SUMMARY.md`, `TEST_PLAN.md`, `DOCUMENTATION_CHANGES.md`
- Any `.md` file created for understanding or planning (use `/tmp/` if you need scratch space)

## Commit message format

```
<area>: <concise description of what changed and why>

Context:
- What triggered this change

Change:
- What was adjusted and why
```

Examples:
```
utils/time: fix duration parsing to respect timezone

Context:
- Bug #1234: PT2H parsed incorrectly in CET timezone

Change:
- Pass timezone through to isodate.parse_duration
```

```
agents/test-specialist: add full-suite requirement after governance failure

Context:
- Session 2026-02-10 revealed partial test execution as root cause

Change:
- Added explicit requirement to run complete test suite
```

Use the file path or area as the prefix (e.g. `api/v3_0`, `data/models`, `cli`, `docs`, `agents/<name>`).
