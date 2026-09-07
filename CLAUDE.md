# FlexMeasures — conventions for coding agents

The repo's cross-cutting conventions live in [`.github/instructions/`](.github/instructions/) as
`*.instructions.md` files (their `applyTo:` frontmatter maps them to file globs). They are written
for GitHub Copilot, but they are the source of truth for **any** agent working here — read the ones
relevant to the files you touch, and follow them.

Most-missed rules, called out so they are not forgotten:

- **Docstrings & comments break lines only after punctuation** — never wrap in the middle of a phrase.
  Each physical line ends at a comma, semicolon, colon, or period. `E501` is ignored and
  `max-line-length` is 160, so prefer a long clause on one line over a mid-phrase break. This keeps
  review comments and text search stable. See [`docstrings.instructions.md`](.github/instructions/docstrings.instructions.md).
- **Run the pre-commit hooks before committing** — they reformat (black), lint (flake8), type-check,
  and regenerate the OpenAPI spec; a hook that rewrites a file aborts the commit, so re-stage and
  commit again. See [`pre-commit-hooks.instructions.md`](.github/instructions/pre-commit-hooks.instructions.md).
- **Add a changelog entry** for user-facing changes, in the right section, with a PR link. See
  [`changelog.instructions.md`](.github/instructions/changelog.instructions.md).
- **Prove a new test can fail** — break what it covers, confirm it goes red, restore. A test that passes
  with the feature disabled asserts nothing. See
  [`testing.instructions.md`](.github/instructions/testing.instructions.md).
- **One logical change per commit** ([`atomic-commits.instructions.md`](.github/instructions/atomic-commits.instructions.md)),
  **timezone-aware datetimes always** ([`timezone-awareness.instructions.md`](.github/instructions/timezone-awareness.instructions.md)),
  **catch specific exceptions** ([`error-handling.instructions.md`](.github/instructions/error-handling.instructions.md)),
  and **"organisation" not "account" in user-facing text** ([`ui-terminology.instructions.md`](.github/instructions/ui-terminology.instructions.md)).

When you add a docstring or comment, re-read it against the line-break rule before moving on.
