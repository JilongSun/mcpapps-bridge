# Repository Structure

```
mcpapps-bridge/
│
├── backend/                          # Python bridge host
│   ├── pyproject.toml
│   └── src/mcpapps_bridge/
│       ├── main.py                   # CLI entry point (control plane or combined runtime)
│       ├── api/                      # FastAPI HTTP + WebSocket control plane
│       ├── host/                     # Runtime orchestration (proxy + API co-location)
│       ├── mcp/
│       │   ├── upstream.py           # Upstream MCP client (stdio → SDK session)
│       │   └── proxy.py              # Downstream stdio MCP proxy server surface
│       ├── session/                  # Single-session state container + event store
│       ├── events/                   # Typed event envelopes
│       ├── models/                   # Shared Pydantic models (session, tool, resource)
│       └── agent_adapters/           # Agent-specific wiring (future)
│
├── frontend/                         # React debugging + session surface
│   ├── package.json
│   ├── vite.config.ts                # Dev server with /api proxy to backend
│   └── src/
│       ├── main.tsx                  # React entry point
│       ├── App.tsx                   # Three-panel shell (transcript, activity, app)
│       ├── types.ts                  # Mirror of backend session/event models
│       ├── hooks/
│       │   └── useBridgeSession.ts   # WebSocket subscription + snapshot fetcher
│       └── styles.css
│
├── scripts/
│   └── dev.py                        # Cross-platform full-stack dev launcher
│
├── docs/
│   └── architecture/                 # Architecture notes and ADRs
│
├── .github/
│   └── instructions/                 # Committed project instructions for devs and agents
│
├── justfile                          # Root task commands (install, backend, frontend, dev)
├── README.md
└── LICENSE
```

## Layer Responsibilities

| Layer | Module | Role |
|-------|--------|------|
| **Proxy** | `mcp/proxy.py` | Presents a stdio MCP server to the agent; mirrors upstream tools and resources |
| **Upstream** | `mcp/upstream.py` | Connects to real MCP servers via stdio and maps SDK objects to internal models |
| **Session** | `session/state.py` | Single-session state container; event store; thread-safe snapshot access |
| **Events** | `events/models.py` | Typed event envelopes consumed by the control plane and frontend |
| **Models** | `models/protocol.py` | Canonical Pydantic models shared across the backend |
| **API** | `api/app.py` | FastAPI HTTP + WebSocket surface for session snapshot and event streaming |
| **Host** | `host/runtime.py` | Co-locates the proxy and API in one process, sharing `BridgeSessionState` |
| **Frontend** | `frontend/src/` | Consumes `/api/session` and `/api/events/ws`; renders three-panel debug UI |
| **Dev launcher** | `scripts/dev.py` | Starts backend + frontend concurrently (`just dev`) |

