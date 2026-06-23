# Repository Structure

This repository uses a traditional frontend/backend split.

## Top-Level Layout

- `backend/` contains the Python bridge host, MCP proxy logic, session runtime, and agent adapters.
- `frontend/` contains the React application that will render transcript output, bridge activity, and MCP App widgets.
- `docs/architecture/` contains architecture notes and stable repository decisions.
- `.github/instructions/` contains committed project instructions for developers and agents.

## Backend Layout

- `backend/src/mcpfront_bridge/api/` for HTTP and WebSocket surfaces
- `backend/src/mcpfront_bridge/agent_adapters/` for Hermes and future agent adapters
- `backend/src/mcpfront_bridge/host/` for MCP Apps host behavior
- `backend/src/mcpfront_bridge/mcp/` for proxy, transport, and resource modules
- `backend/src/mcpfront_bridge/session/` for single-session lifecycle and state
- `backend/src/mcpfront_bridge/events/` for backend event envelopes and event bus helpers
- `backend/src/mcpfront_bridge/models/` for typed backend models

## Frontend Layout

- `frontend/src/` for the session UI and bridge debugging surface
- The frontend starts as a lightweight Vite app rather than a product-scale chat scaffold.
- MCP App rendering will be integrated into the frontend through `@mcp-ui/client`.

## Notes

- Shared frontend/backend contracts should be defined before large feature expansion.
- Cross-platform behavior is required for scripts, paths, and runtime assumptions.
- In the early project phase, the repository favors executable validation and integration-critical checks over default unit-test scaffolding.
