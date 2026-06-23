---
description: "Use when: writing or editing React frontend code, session UI, MCP App rendering, tool activity panels, or frontend event wiring."
applyTo: ["frontend/**", "**/*.tsx", "**/*.ts"]
---
# Frontend Guidelines

## Tooling

- Use React with Vite and pnpm.
- Run `pnpm dev` for development, `pnpm build` for production builds, `pnpm test` for Vitest.
- Keep dependencies minimal; add new packages only when the built-in platform or existing stack cannot solve the problem cleanly.
- Prefer mature SDKs and established packages when they fit the requirement well. Avoid custom UI infrastructure when a stable package already solves the problem.

## Structural Boundaries

Avoid large-chat-application patterns. The frontend is a bridge debugging and session surface, not a product chat shell.

Organize code so these concerns stay separate:

- **Transcript rendering** — user messages, model text output, streaming delta display
- **Tool activity** — tool call lifecycle, timing, input/output summaries
- **MCP App rendering** — integration with `@mcp-ui/client`, sandboxed iframe, resource loading
- **Session transport** — WebSocket or SSE event subscription, reconnection, error handling
- **UI action handling** — widget `postMessage` dispatch, action routing back to the host

## State Management

- Prefer local component state and React Context for shared session data.
- Do not introduce global state libraries (Redux, Zustand) unless a specific task proves React Context is insufficient.
- Keep session event stream and derived UI state in separate layers so the transcript does not need to understand MCP App rendering internals.

## Component Rules

- A component that renders chat transcript should not also manage WebSocket lifecycle.
- A component that wraps `@mcp-ui/client` AppRenderer should not also own tool-activity polling.
- Event handlers (`onMessage`, `onOpenLink`, `onUiAction`) must validate origins and payload shapes before acting.
- Avoid OS-specific path, shell, or URL assumptions in the frontend toolchain and development scripts when portable alternatives exist.

## Testing

- Early in the project, do not add unit-test scaffolding by default when interfaces are still shifting quickly.
- When tests are added, use Vitest for unit and component tests.
- Use Playwright for integration tests that span the WebSocket session and the rendered MCP App widget.
- Do not test framework behavior; test session flows, event rendering, and action dispatch.
