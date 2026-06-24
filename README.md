# mcpapps-bridge

A bridge host for bringing MCP Apps support to agent runtimes that do not natively render MCP App UIs.

## Repository Layout

- `backend/` contains the Python bridge host, MCP proxy logic, session runtime, and agent adapters.
- `frontend/` contains the React application for transcript output, bridge activity, and MCP App rendering.
- `docs/architecture/` contains architecture notes and stable repository decisions.
- `.github/instructions/` contains committed instructions for developers and coding agents.

## Current Phase

The repository is in early scaffolding.

- The backend is organized for a protocol-aware bridge and MCP Apps host.
- The frontend starts as a lightweight debugging and session surface.
- Multi-channel support such as CLI, gateway, and IM remains a future extension point.

See `docs/architecture/repository-structure.md` for the current structure rationale.
