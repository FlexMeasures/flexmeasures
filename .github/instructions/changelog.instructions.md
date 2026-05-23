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

Replace `XXXX` with the actual PR number. If the PR number is not yet known, alert the maintainer.

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
- Small agent instruction updates
- Pure documentation typo fixes
