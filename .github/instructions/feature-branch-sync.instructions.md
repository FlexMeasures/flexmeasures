---
applyTo: "**"
---
# Feature Branch Synchronization

Feature branches must be kept synchronized with `origin/main` before implementing code changes.

## Check branch status

Before starting implementation work, verify the branch is up to date:

```bash
git log --oneline origin/main...HEAD --left-right
```

If you see < markers, origin/main has commits the branch lacks — a fresh merge is needed.

```bash
# ❌ Don't just check git status (it only tells you about uncommitted changes)
git status          # shows "nothing to commit" even if behind main

# ✅ Do check the commit graph
git log --left-right origin/main...HEAD
```

## Merge before implementation

```bash
git fetch origin
git merge origin/main
# Resolve any conflicts
git add .
git commit -m "Merge origin/main into feature branch"
```

This ensures your implementation starts from the latest state of the repository.

## Why this matters

- Merging later causes merge conflicts to compound
- Large late merges are harder to review
- Feature work should build on current main, not diverge
