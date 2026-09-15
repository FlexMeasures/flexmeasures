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

## Never rebase or force-push a branch under review

Merge `origin/main` in; do not rebase onto it, and do not force-push. A pull request's review
history is anchored to its commits, so rewriting them discards the conversation and asks every
reviewer to start again. A merge commit is the cost of keeping that history, and it is worth it.

## A stacked branch, after its base was squash-merged

When branch B is stacked on branch A and A is **squash-merged**, B conflicts almost everywhere:
`main` now holds A's whole diff as a single commit with no shared history, while B still carries
A's original commits. Resolving those conflicts by hand means adjudicating A's entire diff a
second time, which is how a regression slips in.

Do this instead, which needs no force-push:

```bash
# 1. Restore A's branch from a tip you still have (a worktree keeps it after the remote ref goes;
#    `git reflog` otherwise).
git branch A <A's tip>

# 2. Merge into A the state of main from just before A's squash-merge commit.
git switch A && git merge <squash-commit>^

# 3. Merge A into B, so B holds the full unsquashed lineage.
git switch B && git merge A

# 4. Merge main into B, accepting B's side on conflicts.
git merge -X ours origin/main

# 5. Delete A again. Its commits stay reachable from B.
git branch -D A
```

Step 4 is safe by construction: after step 3 every remaining conflict is between two
representations of the *same* content, so taking B's side cannot lose anything.

**Check that it worked by measuring, not by reading the diff.** Before starting, record what B
adds on top of the A state it had:

```bash
git diff $(git merge-base B A) B --stat
```

Afterwards, `git diff origin/main --stat` should report the same files and the same +/- counts.
An identical measurement means nothing of A's was duplicated and nothing of B's was dropped.

## When a shared branch has moved on in ways the merge cannot see

A mechanical merge only reconciles text. After merging a branch that renamed something the API or
the CLI exposes, grep the merged tree for the old name: a field a branch added in the old style is
not a conflict, but it is still wrong once main has moved. The same goes for a changelog entry
whose release section or version number main has since used.
