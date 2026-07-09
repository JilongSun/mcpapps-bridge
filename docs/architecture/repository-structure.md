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
│       │   ├── __init__.py
│       │   ├── upstream.py           # Upstream MCP clients (stdio, SSE, streamable HTTP)
│       │   ├── runtime.py            # Bridge runtime: lifecycle, cache, state sync, UI resource synthesis
│       │   ├── downstream.py         # Downstream MCP server + HTTP/SSE/stdio transports
│       │   ├── handlers.py           # MCP method handler registration (tools, resources)
│       │   ├── mapper.py             # Protocol type conversion (internal models ↔ MCP SDK types)
│       │   └── proxy.py              # Assembly helper: wires runtime + downstream together
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
| **Upstream** | `mcp/upstream.py` | Connects to real MCP servers via stdio, SSE, or streamable HTTP; maps SDK objects to internal models |
| **Runtime** | `mcp/runtime.py` | Owns upstream lifecycle, tool/resource caches, session sync, UI resource preloading, and synthesized resource descriptors |
| **Downstream** | `mcp/downstream.py` | Hosts the downstream MCP `Server` with streamable HTTP, SSE fallback, and stdio transports; presents upstream identity to downstream clients |
| **Handlers** | `mcp/handlers.py` | Registers `list_tools`, `call_tool`, `list_resources`, `read_resource` on the MCP Server with dependency injection |
| **Mapper** | `mcp/mapper.py` | Pure protocol type conversion: `ToolDescriptor → types.Tool`, `ToolCallResult → types.CallToolResult`, content blocks, resource contents |
| **Assembly** | `mcp/proxy.py` | Thin factory function that constructs a `BridgeRuntime` + `BridgeDownstreamServer` from config |
| **Session** | `session/state.py` | Single-session state container; event store; thread-safe snapshot access |
| **Events** | `events/models.py` | Typed event envelopes consumed by the control plane and frontend |
| **Models** | `models/protocol.py` | Canonical Pydantic models shared across the backend |
| **API** | `api/app.py` | FastAPI HTTP + WebSocket surface for session snapshot and event streaming |
| **Host** | `host/runtime.py` | Co-locates the proxy and API in one process, sharing `BridgeSessionState` |
| **Config** | `config/` | YAML-based bridge configuration (upstreams, runtime settings) |
| **Frontend** | `frontend/src/` | Consumes `/api/session` and `/api/events/ws`; renders three-panel debug UI |
| **Dev launcher** | `scripts/dev.py` | Starts backend + frontend concurrently (`just dev`) |

