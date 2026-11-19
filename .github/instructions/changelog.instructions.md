---
applyTo: "**"
---
# Changelog Entries

Each PR generally requires a changelog entry.

## Changelogs

| File | Audience |
|------|----------|
| `documentation/changelog.rst` | Main changelog — API/CLI/UI users and plugin developers |
| `documentation/api/changelog.rst` | API-specific changes |
| `documentation/cli/changelog.rst` | CLI-specific changes |

## Entry format

Always follow the formatting convention already present in the target changelog file — the style may evolve over time. The canonical guide is the file itself.

Current conventions:
- **Main changelog**: one sentence, no period at the end, written for end users (abstract away technical details when possible)
- **API and CLI changelogs**: slightly more technical audience; use a period at the end

Example for the main changelog:

```rst
* Add cross-cutting Copilot instruction files to `.github/instructions/` [see `PR #XXXX <https://www.github.com/FlexMeasures/flexmeasures/pull/XXXX>`_]
```

Replace `XXXX` with the PR number.
For a PR that does not exist yet, fill in the most likely next number before pushing (see below), rather than leaving `XXXX`.

## Guessing the number of a PR that does not exist yet

Issues, PRs and discussions share one number sequence, and a new PR usually takes the next free number.
So before pushing the branch for a new PR, fill in that number:

```bash
R=FlexMeasures/flexmeasures
N=$(( $(gh api "repos/$R/issues?state=all&per_page=1" --jq '.[0].number') + 1 ))
curl -s -o /dev/null -w '%{http_code}\n' "https://github.com/$R/issues/$N"  # 404: the number is still free
```

The issues API lists issues and PRs, but not discussions, so check the web URL:
it answers 404 only while no issue, PR or discussion has the number (otherwise 200, or a redirect).
If it does not answer 404, try the next number.

After creating the PR, compare its number with the one filled in.
If someone took the number in between, correct the entry and push again.
Guessing right is common, and it saves a CI run for a commit that only fills in the number.

## Sections in `documentation/changelog.rst`

Always use this order:

- **New features** — new capabilities visible to API/CLI/UI users
- **Infrastructure / Support** — changes targeting plugin developers and hosts
- **Bugfixes** — corrections to incorrect behavior

## PR description checkbox

The PR template includes a changelog checkbox:

```markdown
- [ ] Added changelog item in `documentation/changelog.rst`
```

Tick it once the changelog entry is committed.

## What requires a changelog entry

Each PR generally requires an entry. Examples of what warrants one:

- New API endpoints or parameters
- Changed or removed API behavior
- New CLI commands or options
- UI feature additions or changes
- Performance improvements that affect users
- Breaking changes (always require a changelog entry, plus migration notes)
- Changes to plugin interfaces
- Significant changes to the repo's AI infrastructure

## What does not require a changelog entry

- Internal refactoring with no user-visible effect
- Test-only changes
- Small agent instruction updates (typo fixes, minor wording changes)
- Pure documentation typo fixes
