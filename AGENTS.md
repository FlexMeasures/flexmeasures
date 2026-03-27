# FlexMeasures Agents

This repository uses GitHub Copilot agents to automate code reviews, development tasks, and project planning.

## Default Agent: Lead

The **Lead** agent is the primary entry point for all agent-based work. It orchestrates specialist agents and coordinates task execution.

- **Location**: [.github/agents/lead.md](.github/agents/lead.md)
- **Responsibilities**: 
  - Interprets user assignments (reviews, features, bug fixes, refactoring)
  - Selects and runs relevant specialist agents
  - Synthesizes findings and coordinates implementations
  - Delivers unified output and sees changes through to completion

## Specialist Agents

The Lead agent coordinates with specialized agents, each owning specific domains:

1. **Test Specialist** ([.github/agents/test-specialist.md](.github/agents/test-specialist.md))
   - Test quality, coverage, and correctness
   
2. **Architecture & Domain Specialist** ([.github/agents/architecture-domain-specialist.md](.github/agents/architecture-domain-specialist.md))
   - Domain model, invariants, long-term architecture
   
3. **Performance & Scalability Specialist** ([.github/agents/performance-scalability-specialist.md](.github/agents/performance-scalability-specialist.md))
   - System performance under realistic loads
   
4. **Data & Time Semantics Specialist** ([.github/agents/data-time-semantics-specialist.md](.github/agents/data-time-semantics-specialist.md))
   - Time, units, and data semantics
   
5. **API & Backward Compatibility Specialist** ([.github/agents/api-backward-compatibility-specialist.md](.github/agents/api-backward-compatibility-specialist.md))
   - User and integrator protection
   
6. **Documentation & Developer Experience Specialist** ([.github/agents/documentation-developer-experience-specialist.md](.github/agents/documentation-developer-experience-specialist.md))
   - Project understandability
   
7. **Tooling & CI Specialist** ([.github/agents/tooling-ci-specialist.md](.github/agents/tooling-ci-specialist.md))
   - Automation reliability and maintainability
   
8. **Coordinator** ([.github/agents/coordinator.md](.github/agents/coordinator.md))
   - Meta-agent managing agent lifecycle and system coherence

## Using the Agents

### In GitHub Chat
When you mention **@copilot** in GitHub issues, pull requests, or discussions, the Lead agent will be invoked to handle your request.

### Task Types
- **Code Reviews**: The Lead agent orchestrates specialists to review PRs
- **Feature Development**: The Lead coordinates implementation across domains
- **Bug Fixes**: The Lead triages and coordinates fixes with specialists
- **Refactoring**: The Lead ensures changes maintain architecture and performance

## Agent Instructions

Each agent has detailed instructions in its markdown file, including:
- **Role**: Primary responsibility and scope
- **Scope**: What the agent must/must not do
- **Review Checklist**: Concrete steps to perform
- **Domain Knowledge**: FlexMeasures-specific facts and patterns
- **Interaction Rules**: How agents coordinate
- **Self-Improvement Notes**: How agents evolve their instructions

## FlexMeasures Context

This repository is a flexible power balancing platform that serves complex domain semantics, time-aware operations, and integration requirements.

**Key Characteristics**:
- Python/Flask-based platform with PostgreSQL backend
- Complex asset and sensor data models
- Time and unit semantics are critical
- Backward compatibility with existing integrations
- CI/CD with Python 3.10-3.12 matrix testing

For more information, see the [README.md](README.md) and project documentation.

