---
description: "Use when: working on any file in the repository. Defines project scope, architecture, stack choices, and cross-cutting conventions that all developers and agents must follow."
applyTo: "**"
---
# Project Standards

## Scope

This project is an MCP Apps Gateway for agent runtimes, with MCP Apps UI hosting as a core capability and an optional adapter-driven Agent Host plane.

- Prioritize the MCP data plane, management plane, and MCP Apps host lifecycle over chat-product polish. Keep room for an optional Agent Host surface with transcript output, tool activity, and rendered MCP App widgets.
- Treat multi-channel support (web, CLI, gateway, IM) as future extension points unless the current task explicitly requires them.
- Organize the repository as a traditional frontend/backend split. Keep package management and runtime configuration files inside `backend/` and `frontend/` rather than at the repository root.

## Architecture

- Keep the bridge as the protocol-aware system boundary between agent runtimes and real MCP servers.
- Preserve MCP Apps semantics at the protocol layer, especially `initialize`, `tools/list`, `tools/call`, `resources/read`, and relevant MCP notifications.
- Design around a single-session runtime first. Do not introduce multi-session orchestration unless the task requires it.
- Keep agent adapters isolated from the generic bridge runtime. Agent-specific logic must not leak into reusable core modules.
- Prefer host-owned UI action handling first. Route widget actions back to the host unless a task explicitly requires folding them into the agent reasoning loop.

## Backend

- Implement backend and bridge logic in Python.
- Keep MCP transport logic, session runtime logic, and agent adapter logic in separate modules.
- Favor typed request, event, and session models over ad hoc dictionaries.
- Keep async boundaries explicit and predictable.
- Prefer mature SDKs and established packages when they fit the requirement well. Discuss and justify new SDK adoption when the tradeoff is not obvious.

## Frontend

- Use React with Vite and pnpm.
- Use a lightweight React frontend instead of adopting a large chat application scaffold unless there is a clear payoff.
- Favor minimal structure that supports transcript rendering, tool activity visibility, and MCP App rendering over product-heavy UI abstractions.
- Prefer mature SDKs and established packages when they fit the requirement well. Avoid writing custom infrastructure where a stable package already solves the problem.

## Conventions

- Keep repository terminology aligned with MCP and MCP Apps concepts. Prefer precise names such as `bridge`, `host`, `adapter`, `session`, and `resource` over vague aliases.
- Use contract-first design when defining frontend-backend interaction. Shared event and session models must be stable before expanding features.
- Keep implementations small and explicit. Avoid speculative abstractions for channels, agents, or UI capabilities not yet proven by the current milestone.
- Preserve cross-platform behavior. Do not hardcode Windows-only or Linux-only paths, shell assumptions, or filesystem separators when a portable standard-library or framework abstraction exists.

## Testing

- In the early phase of the project, do not add unit-test scaffolding by default just to satisfy structure. Prioritize executable validation, narrow checks, and integration-critical coverage as interfaces stabilize.
- When tests are added, prefer narrow tests for the bridge, protocol models, and frontend rendering slices.
- Bridge and protocol model tests should use controlled fixtures, not live agents or real MCP servers.
