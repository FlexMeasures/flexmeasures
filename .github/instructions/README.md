# `.github/instructions/` — Path-Specific Custom Instructions

This directory contains [path-specific custom instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions#creating-path-specific-custom-instructions) for GitHub Copilot.

Each `<topic>.instructions.md` file covers a cross-cutting convention that applies to multiple areas of the codebase. Copilot automatically applies these instructions when working on files that match the `applyTo:` glob pattern in the file's frontmatter.

## Files in this directory

| File | `applyTo` | Topic |
|------|-----------|-------|
| `atomic-commits.instructions.md` | `**` | Commit discipline — one logical change per commit |
| `changelog.instructions.md` | `**` | Changelog entry format and location |
| `docstrings.instructions.md` | `**/*.py` | RST docstring format, doctests |
| `error-handling.instructions.md` | `**/*.py` | Catching specific exceptions |
| `marshmallow-schemas.instructions.md` | `flexmeasures/data/schemas/**/*.py` | `data_key`, field naming, `load_default` |
| `pre-commit-hooks.instructions.md` | `**` | Running hooks before every commit |
| `testing.instructions.md` | `flexmeasures/**/tests/**/*.py` | Full suite, `db` vs `fresh_db`, `requesting_user` |
| `timezone-awareness.instructions.md` | `**/*.py` | Always timezone-aware datetimes |
| `ui-terminology.instructions.md` | `flexmeasures/ui/**` | "organisation" not "account" in user-facing text |

## Adding new instruction files

When a convention appears in two or more agent files or is frequently missed, extract it here:

1. Create `<topic>.instructions.md` in this directory.
2. Add a YAML frontmatter block with `applyTo:` pointing to the relevant files.
3. Write concise, actionable instructions in natural language Markdown.
4. Update the table above.
5. Reference the new file from the relevant agent files in `.github/agents/`.
