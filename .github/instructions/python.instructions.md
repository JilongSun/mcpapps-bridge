---
description: "Use when: writing or editing Python backend code, bridge service logic, MCP protocol handling, session runtime, agent adapters, or async service modules."
applyTo: ["**/*.py"]
---
# Python Backend Guidelines

## Tooling

- Use `uv` for all dependency and environment operations.
- Run `uv run pytest` for tests, `uv run ruff check` for linting, `uv run pyright` for type checking.
- Prefer `uv add <package>` and `uv remove <package>` for dependency changes.
- Authoritative configuration lives in `pyproject.toml`, not scattered across setup.cfg and requirements files.
- Prefer mature SDKs and established Python packages when they fit the requirement well. Avoid writing custom protocol, transport, or validation plumbing when a stable package already solves it.

## Module Boundaries

Keep these responsibilities in separate modules:

- **MCP transport logic** — stdio, SSE, HTTP stream handling
- **Bridge host runtime** — protocol interposition, resource cache, UI action routing
- **Session management** — single-session lifecycle, event bus, state tracking
- **Agent adapters** — Hermes or agent-specific wiring that must not leak into the generic bridge

No single module should import from more than one of the above groups without a clear reason.

## Type Discipline

- Model all request, event, and session objects with Pydantic v2.
- Avoid passing raw dictionaries or unstructured tuples across module boundaries.
- Use `typing.Protocol` or ABCs for adapter interfaces, not concrete implementations.
- Use `pathlib.Path` and portable path operations rather than OS-specific string concatenation or hardcoded filesystem separators.

## Async Model

- Use `anyio` or `asyncio` explicitly; do not mix threading primitives without deliberate isolation.
- Long-running bridge loops or MCP client sessions run on their own dedicated tasks.
- Prefer structured concurrency patterns (task groups, scoped cancellation) over bare `asyncio.create_task`.
- Keep sync and async boundaries predictable: a function should be entirely sync or entirely async, not both depending on a runtime flag.

## Testing

- Early in the project, do not add unit-test scaffolding by default when interfaces are still shifting quickly.
- When tests are added, keep them narrow and close to the slice being changed.
- Use `pytest` and `pytest-asyncio` for async test support.
- Bridge and protocol model tests do not need a live agent or a real MCP server; prefer controlled test fixtures.
