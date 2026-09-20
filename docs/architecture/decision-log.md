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
| [0001](decisions/0001-managed-endpoints-and-session-ownership.md) | Accepted; amended by 0003, 0008, 0013, and 0014 | Partial | Managed topology, core-owned endpoint dispatch, isolated sessions, and v0.1 read-only management are implemented; writable management is deferred |
| [0002](decisions/0002-sqlite-persistence-and-configuration-authority.md) | Accepted; amended by 0008, 0013, and 0014 | Partial | SQLite, reset migrations, revisions, events, bootstrap, and management read adapters exist; v0.1 topology is frozen after seed |
| [0003](decisions/0003-mcp-apps-gateway-and-optional-agent-host.md) | Accepted; amended by 0008, 0010, 0011, and 0014 | Partial | Gateway data plane, read-only management, and the first provider-neutral text-run/OpenAI slice exist; MCP Apps host workflows and complete Agent Host behavior remain incomplete |
| [0004](decisions/0004-first-release-scope-and-distribution.md) | Accepted; amended by 0008 and 0014 | Partial | The gateway and read-only management foundations are implemented; Agent Host completion, first-party UI, and OCI delivery remain release blockers |
| [0005](decisions/0005-upstream-transport-task-ownership.md) | Accepted | Implemented | Upstream SDK contexts run and close in persistent owner tasks |
| [0006](decisions/0006-core-service-and-server-packages.md) | Accepted | Implemented | Protocol core, application services, and the deployable server are separate dependency-ordered workspace packages |
| [0007](decisions/0007-cembrid-identity-and-deployment-shells.md) | Accepted; brand superseded by 0009 | Partial | Retain Web/OCI and Tauri desktop service shells; its Cembrid identity is superseded |
| [0008](decisions/0008-restart-applied-managed-topology.md) | Accepted; v0.1 scope amended by 0014 | Pending | Retain restart-applied topology mutation as the basis for a post-v0.1 writable management milestone |
| [0009](decisions/0009-mabrid-product-identity.md) | Accepted; code migration timing amended by 0013 | Partial | Mabrid code identity migrates with the backend refactor; repository and remote migration remain deferred |
| [0010](decisions/0010-application-contexts-and-capability-composition.md) | Accepted; amended by 0011, 0012, 0013, and 0014 | Partial | Organize the application layer into Gateway, MCP Apps, and Agent Host contexts within one service package |
| [0011](decisions/0011-single-agent-target-and-endpoint-assignment.md) | Accepted; amended by 0012 and 0014 | Partial | Single Target identity, endpoint validation, management assignment exposure, and reusable Hermes runtime are implemented; streaming and runtime correlation remain deferred |
| [0012](decisions/0012-agent-runtime-profiles-and-integration-composition.md) | Accepted | Partial | Runtime profiles, typed Hermes capability discovery, nested runtime configuration, and single-instance integration composition are implemented |
| [0013](decisions/0013-backend-semantic-boundaries-and-mabrid-code-identity.md) | Accepted | Implemented | Backend contexts are modularized, MCP transport is core-owned, provisional contracts are removed, and Mabrid code identity is adopted |
| [0014](decisions/0014-read-only-v0-1-management-plane.md) | Accepted | Implemented | v0.1 exposes read-only topology, status, readiness, Agent Target assignment, and session inspection while topology mutations remain deferred |

## Current v0.1 Position

The aggregate gateway data plane and the ADR 0014 read-only backend management plane are complete
vertical slices. Remaining backend release work includes:

- Effective Agent Runtime capability exposure and additional runtime interface implementations.
- Complete provider-neutral Agent Host tool, MCP, and MCP Apps run events.
- OpenAI-compatible streaming chat, Responses, capability reporting, and remote Agent Runtime
  readiness reporting.
- Hermes streaming, session continuity, tool-progress events, and separate Hermes-specific APIs.
- Protocol-level integration coverage for the supported MCP specification versions.
- OCI assembly, static frontend serving, and release-image startup validation.

First-party Agent Host and read-only management frontend workflows remain separate v0.1 work.
Writable topology management is no longer part of v0.1 under ADR 0014.
