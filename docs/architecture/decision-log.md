# Architecture Decision Log

This log separates accepted product and architecture decisions from their current implementation
state. ADRs remain historical records; implementation notes may advance without rewriting the
original context or decision.

Implementation states:

- **Implemented**: the decision is represented in executable code and has focused validation.
- **Partial**: a usable slice exists, but one or more stated behaviors or release checks are absent.
- **Pending**: no executable implementation exists yet.
- **Proposed**: the decision is still under discussion and does not constrain implementation yet.

| ADR | Decision status | Implementation state | Summary |
| --- | --- | --- | --- |
| [0001](decisions/0001-managed-endpoints-and-session-ownership.md) | Accepted; amended by 0003 | Partial | Managed topology, stable endpoint dispatch, and isolated sessions exist; full management mutations and shared sessions do not |
| [0002](decisions/0002-sqlite-persistence-and-configuration-authority.md) | Accepted | Partial | SQLite, migrations, revisions, events, and bootstrap exist; the full management and migration command surfaces do not |
| [0003](decisions/0003-mcp-apps-gateway-and-optional-agent-host.md) | Accepted | Partial | Gateway data-plane behavior exists; management and Agent Host planes remain incomplete |
| [0004](decisions/0004-first-release-scope-and-distribution.md) | Accepted | Partial | The gateway foundation is implemented; Agent Host, management UI/API, and OCI delivery remain release blockers |
| [0005](decisions/0005-upstream-transport-task-ownership.md) | Accepted | Implemented | Upstream SDK contexts run and close in persistent owner tasks |
| [0006](decisions/0006-core-service-and-server-packages.md) | Proposed | Proposed | Extract a reusable bridge core, application services, and a deployable server package |

## Current v0.1 Position

The backend is not waiting only on HTTP API routes. The aggregate gateway data plane is the most
complete vertical slice, but the following backend release work remains:

- Full upstream, endpoint, and binding management use cases and HTTP APIs.
- Provider-neutral Agent Host run and event contracts.
- OpenAI-compatible chat, responses, models, streaming, liveness, and readiness APIs.
- The Hermes HTTP/SSE adapter and separation of standard and Hermes-specific behavior.
- Protocol-level integration coverage for the supported MCP specification versions.
- OCI assembly, static frontend serving, and release-image startup validation.

The frontend currently provides session/event inspection and renders the latest loaded MCP App
resource. Transcript input/output, host-owned MCP App actions, management workflows, and complete
connection inspection remain pending or partial.