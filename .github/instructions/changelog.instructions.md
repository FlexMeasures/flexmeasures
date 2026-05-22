---
applyTo: "**"
---
# Changelog Entries

Every PR that introduces a user-visible change, new feature, infrastructure improvement, or bug fix must include a changelog entry.

## Changelogs

| File | Audience |
|------|----------|
| `documentation/changelog.rst` | Main changelog — API/CLI/UI users and plugin developers |
| `documentation/api/changelog.rst` | API-specific changes |
| `documentation/cli/changelog.rst` | CLI-specific changes |

## Entry format

```rst
* Brief description of the change, written for the intended audience. [see `PR #XXXX <https://www.github.com/FlexMeasures/flexmeasures/pull/XXXX>`_]
```

Replace `XXXX` with the actual PR number. If the PR number is not yet known, alert the maintainer.

## Sections in `documentation/changelog.rst`

- **New features** — new capabilities visible to API/CLI/UI users
- **Bugfixes** — corrections to incorrect behavior
- **Infrastructure / Support** — changes targeting plugin developers and hosts

## PR description checkbox

The PR template includes a changelog checkbox:

```markdown
- [ ] Added changelog item in `documentation/changelog.rst`
```

Tick it once the changelog entry is committed.

## What requires a changelog entry

- New API endpoints or parameters
- Changed or removed API behavior
- New CLI commands or options
- UI feature additions or changes
- Performance improvements that affect users
- Breaking changes (always require a changelog entry, plus migration notes)
- Changes to plugin interfaces

## What does not require a changelog entry

- Internal refactoring with no user-visible effect
- Test-only changes
- Agent instruction updates
- Pure documentation typo fixes
