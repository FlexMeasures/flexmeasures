---
applyTo: "pyproject.toml,uv.lock"
---
# Dependencies and the Lockfile

See `documentation/dev/dependency-management.rst` for how dependencies are managed and how `uv` is pinned.

## Resolving a `uv.lock` conflict

A conflict in `uv.lock` is almost never about the packages themselves.
Different `uv` versions write environment markers differently, so two lockfiles can disagree on nearly every line while only a few packages differ.

**Never merge `uv.lock` by hand.** Both obvious ways of combining the two sides break it silently:

- Combining by package *name* drops one half of entries that are split by Python version
  (e.g. one version of a package for Python 3.11 and another for 3.12), which breaks one of the CI matrix's Python versions.
- Combining by whole *line* keeps both spellings of every marker, which duplicates the package list.

Neither is caught by the tests, only by reading the diff. Instead, take main's lockfile and lock again:

```bash
git checkout origin/main -- uv.lock
uv lock          # with the uv version that `required-version` in pyproject.toml names
uv lock --check
git diff --stat origin/main -- uv.lock
git diff origin/main -- uv.lock | grep -E '^[+-](name|version) = '   # only the packages you meant to change
```

A lockfile rewritten by a different `uv` version shows up as hundreds or thousands of changed lines; that diff should be a few lines.

## Supported version ranges

A dependency without an upper bound (e.g. `pandas>=2.2.1`) means every later major version is supported, too.
Test a change against both ends of the range, without changing your environment:

```bash
uv run --no-project --with "pandas==2.2.1" python probe.py
uv run --no-project --with "pandas==3.*" python probe.py
```

See `timezone-awareness.instructions.md` for what changed with pandas 3.
