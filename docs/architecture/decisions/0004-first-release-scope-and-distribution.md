# ADR 0004: First Release Scope and Distribution

- Status: Accepted; management publication amended by ADR 0008
- Date: 2026-07-16

## Context

The project now spans an MCP Apps Gateway, a management plane, and an Agent Host with a first-party UI. Without an explicit first-release boundary, topology, graph storage, agent integrations, desktop packaging, and operational features could expand independently and prevent a coherent release.

The source repository currently uses separate Python backend and React frontend projects. Source layout, runtime service boundaries, and user-facing distribution do not need to be identical.

## Decision

### Release identity

Version 0.1 is a self-hosted developer preview of two equal product pillars:

1. An aggregate-first MCP Apps Gateway with a minimal management plane.
2. An Agent Host with an OpenAI-compatible API and a first-party MCP Apps-capable UI.

Agent Host activation is optional at deployment time, but its implementation and UI are required for the 0.1 release. Passthrough remains available for compatibility and diagnosis and does not block aggregate-first milestones.

### Backend scope

The 0.1 backend includes:

- SQLite persistence, Alembic migrations, and seed-if-empty bootstrap.
- Restart-applied upstream and endpoint configuration required by the minimal management UI.
- Normalized immutable upstream and endpoint revisions captured by bridge sessions.
- Aggregate tool discovery and call routing with stable namespaces.
- Reversible aggregate resource routing with MCP Apps metadata preservation.
- Passthrough routing for compatibility and diagnosis.
- Session lifecycle, event, snapshot, and health inspection APIs.
- A provider-neutral internal agent run/event contract.
- `POST /v1/chat/completions`, `POST /v1/responses`, `GET /v1/models`, and health endpoints.
- An HTTP/SSE Hermes adapter targeting an independently deployed Hermes runtime.
- Separate contracts for standard OpenAI-compatible behavior and Hermes-specific HTTP capabilities.

The backend is stabilized before frontend implementation expands. After the backend vertical slices work, the project performs an explicit architecture, terminology, module-ownership, and schema review. Public API contracts and the first-party frontend are frozen against the reviewed model rather than against provisional names.

### Frontend scope

The 0.1 frontend includes:

- Agent conversation input and streaming assistant output.
- Tool activity and result visibility.
- MCP App resource and widget rendering with host-owned UI actions.
- Minimal upstream, endpoint, and binding management.
- Connection, health, and session inspection needed to diagnose the local deployment.

The first release does not attempt to provide a complete enterprise administration console.

### Source and runtime architecture

The repository keeps the traditional `backend/` and `frontend/` source split. Development continues to use independent Python and Vite processes with explicit API contracts.

Production distribution uses one OCI image and one public service. The frontend is compiled to static assets during the image build and served by the backend on the same origin. This avoids a second deployment unit, CORS configuration, and independent frontend/backend version skew without coupling frontend source code to Python modules.

Hermes runs as an independent process or service and communicates with the Agent Host over HTTP/SSE. It is not embedded as a Python dependency. A future Electron distribution may launch an ACP-compatible agent sidecar over JSON-RPC stdio, but Electron and ACP packaging are outside the 0.1 boundary.

### Distribution contract

The primary 0.1 artifact is a versioned OCI image. A tagged source release is also provided for development and review. Python wheels and frontend packages may be built as implementation artifacts, but 0.1 does not promise a stable Python SDK or JavaScript SDK import surface.

The container runs one application process and one Uvicorn worker in the SQLite profile. It is intended for trusted self-hosted evaluation, not public multi-tenant production. Multi-process session ownership, horizontal failover, hardened authentication, and external database operation remain later release concerns.

### Explicit exclusions

The 0.1 release excludes:

- A graph database runtime dependency.
- Multi-process or horizontally scaled MCP session ownership.
- Live topology mutation inside an active bridge session.
- Electron packaging and ACP-based local agent launching.
- A stable embedded Python or JavaScript SDK.
- A full enterprise operations console.
- Live topology reload or process restart orchestration.

## Consequences

- The release demonstrates the original MCP Apps UI goal rather than shipping only backend infrastructure.
- Backend contracts can stabilize before the frontend creates broad compatibility obligations.
- Separate source projects preserve clear engineering boundaries while the single image keeps self-hosted deployment simple.
- The first Hermes integration does not force Hermes dependencies into the gateway process.
- Graph storage, desktop IPC, and enterprise operations can be evaluated against working contracts instead of anticipated requirements.
- A deliberate pre-release refactor is expected; it must preserve behavior through migrations and contract tests rather than becoming an unbounded rewrite.

## Release Gate

Version 0.1 is ready when:

1. Aggregate tool and MCP App resource flows pass protocol-level integration tests.
2. Sessions remain bound to immutable topology revisions.
3. Management mutations create coherent revisions, report that restart is required, and affect
   gateway behavior only after a new process loads them.
4. OpenAI-compatible non-streaming and streaming flows pass contract tests through the Hermes HTTP adapter.
5. Hermes-specific capabilities cannot leak into the generic OpenAI adapter or MCP gateway modules.
6. The first-party UI renders assistant output, tool activity, and MCP App widgets against stable backend contracts.
7. A clean database can migrate and bootstrap inside the release image.
8. The image can start from documented configuration and report liveness and readiness without a development toolchain.

## Implementation Status

As of 2026-08-16:

### Backend Scope

| Requirement | State | Evidence or gap |
| --- | --- | --- |
| SQLite, migrations, and seed-if-empty bootstrap | Implemented | SQLAlchemy/Alembic persistence and SQLite bootstrap are active in normal and debug startup |
| Restart-applied upstream/endpoint/binding management | Partial | Domain and add/read repository foundations exist; revise/disable use cases, HTTP routes, and restart reporting do not |
| Immutable upstream and endpoint revisions | Implemented | Sessions capture an endpoint revision whose bindings reference upstream revisions |
| Aggregate tool discovery and routing | Implemented | Namespaced discovery, calls, degraded availability, retry, and owner-task lifecycle are present |
| Aggregate resource and MCP Apps routing | Implemented | Ordinary/UI routes, metadata, resource links, and embedded resources are rewritten |
| Passthrough compatibility mode | Implemented | One-binding transparent routing remains available |
| Session lifecycle and inspection | Partial | Records, snapshots, events, REST reads, and WebSocket events exist; upstream-session audit and broader health are incomplete |
| Provider-neutral Agent Host contract | Pending | `agent_adapters` contains no runtime contract or implementation |
| OpenAI-compatible API | Pending | Chat completions, responses, and models routes do not exist |
| Hermes HTTP/SSE adapter | Pending | No Hermes adapter implementation exists |
| Standard/Hermes contract separation | Pending | No executable adapter contracts exist yet |

### Frontend Scope

| Requirement | State | Evidence or gap |
| --- | --- | --- |
| Conversation input and streaming output | Pending | The transcript panel explicitly reports that it is not connected |
| Tool activity and results | Partial | Bridge events are listed, but there is no complete agent/tool workflow |
| MCP App rendering and host actions | Partial | The latest resource renders through `@mcp-ui/client`; message actions are placeholders |
| Upstream/endpoint/binding management | Pending | No management surface exists |
| Connection, health, and session inspection | Partial | One session event stream is shown; broader connection and health workflows are absent |

### Release Gates

| Gate | State | Evidence or gap |
| --- | --- | --- |
| Aggregate tool/resource protocol integration tests | Partial | Manual real-transport validation exists; the automated suite covers owner-task lifecycle only |
| Sessions remain on immutable revisions | Implemented | `BridgeSessionRecord.endpoint_revision_id` is required and persisted |
| Management mutations persist coherent revisions for restart | Partial | Initial publication creates revisions; later revise/disable workflows and restart reporting do not exist |
| OpenAI/Hermes contract tests | Pending | APIs and adapter are absent |
| Hermes isolation | Pending | No implementation exists to validate the boundary |
| First-party agent and MCP Apps UI | Partial | MCP App rendering exists; agent transcript and host actions do not |
| Clean database migration/bootstrap in release image | Pending | Source and wheel checks exist, but there is no OCI image |
| Image startup, liveness, and readiness | Pending | No container artifact exists and readiness is absent |
