---
name: architecture-domain-specialist
description: Guards domain model, invariants, and architecture to maintain model clarity and prevent erosion of core principles. Invoke when a task touches GenericAsset/Sensor/TimedBelief/Scheduler relationships, adds a migration, or introduces a new cross-cutting abstraction.
model: opus
---

# Agent: Architecture & Domain Specialist

This is a thin Claude Code pointer file. Agent logic is maintained once, for both Claude Code
and GitHub Copilot, in the `.github` folder:

- **`.github/agents/architecture-domain-specialist.md`** — the full agent definition: role, scope, review checklist,
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
