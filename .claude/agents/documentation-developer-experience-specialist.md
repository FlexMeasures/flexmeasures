---
name: documentation-developer-experience-specialist
description: Ensures excellent documentation, clear error messages, and smooth developer workflows to keep FlexMeasures accessible. Invoke when a task changes user-facing behavior, CLI/API surface, or error messages that should be reflected in docs or the changelog.
model: sonnet
---

# Agent: Documentation & Developer Experience Specialist

This is a thin Claude Code pointer file. Agent logic is maintained once, for both Claude Code
and GitHub Copilot, in the `.github` folder:

- **`.github/agents/documentation-developer-experience-specialist.md`** — the full agent definition: role, scope, review checklist,
  domain knowledge, interaction rules, and self-improvement notes. Read this file in full before
  acting as this agent. When agent behavior needs to change, edit that file, not this one.
- **`.github/instructions/`** — project-wide conventions shared by every agent (atomic commits,
  changelog entries, docstrings, error handling, Marshmallow schemas, pre-commit hooks, testing,
  timezone awareness, UI terminology).
- **`.github/workflows/copilot-setup-steps.yml`** — the reference environment setup (system
  packages, Python/uv setup, database, environment variables) used for GitHub Copilot's cloud
  agents. Claude Code agents run in their own sandboxed environment, not this one, so treat this
  file as a reference for expected dependencies and services rather than a script to execute
  verbatim.
