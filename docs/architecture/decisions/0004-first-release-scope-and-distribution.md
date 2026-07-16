# ADR 0004: First Release Scope and Distribution

- Status: Accepted
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
- Managed upstream and endpoint CRUD required by the minimal management UI.
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
- Multi-tenancy, organization inheritance, RBAC, SSO, and billing.
- Multi-process or horizontally scaled MCP session ownership.
- Live topology mutation inside an active bridge session.
- Electron packaging and ACP-based local agent launching.
- A stable embedded Python or JavaScript SDK.
- A full enterprise operations console.

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
3. Management mutations create new revisions without changing active sessions.
4. OpenAI-compatible non-streaming and streaming flows pass contract tests through the Hermes HTTP adapter.
5. Hermes-specific capabilities cannot leak into the generic OpenAI adapter or MCP gateway modules.
6. The first-party UI renders assistant output, tool activity, and MCP App widgets against stable backend contracts.
7. A clean database can migrate and bootstrap inside the release image.
8. The image can start from documented configuration and report liveness and readiness without a development toolchain.
