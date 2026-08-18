---
description: "Stable Python tooling, typing, async, and test conventions for backend packages and applications."
applyTo: ["**/*.py"]
---
# Python Backend Guidelines

## Tooling

- Use `uv` for all dependency and environment operations.
- Run tests with `uv run --all-packages pytest`, lint with `uv run ruff check`, and type-check
	with `uv run pyright` from `backend/`.
- Format changed Python files with `uv run ruff format`.
- Prefer `uv add <package>` and `uv remove <package>` for dependency changes.
- Authoritative configuration lives in `pyproject.toml`, not scattered across setup.cfg and requirements files.
- Prefer mature SDKs and established Python packages when they fit the requirement well. Avoid writing custom protocol, transport, or validation plumbing when a stable package already solves it.

## Type Discipline

- Use project-owned typed models at package boundaries; use Pydantic v2 where runtime validation or
	serialization is required.
- Avoid passing raw dictionaries or unstructured tuples across module boundaries.
- Use `typing.Protocol` or ABCs for adapter interfaces, not concrete implementations.
- Use `pathlib.Path` and portable path operations rather than OS-specific string concatenation or hardcoded filesystem separators.

## Async Model

- Use `anyio` or `asyncio` explicitly; do not mix threading primitives without deliberate isolation.
- Long-running bridge loops or MCP client sessions run on their own dedicated tasks.
- Prefer structured concurrency patterns (task groups, scoped cancellation) over bare `asyncio.create_task`.
- Keep sync and async boundaries predictable: a function should be entirely sync or entirely async, not both depending on a runtime flag.

## Testing

- Keep tests narrow and close to the behavior being changed.
- Use pytest with the repository's configured async support.
- Prefer controlled fixtures over live agents or MCP servers.
