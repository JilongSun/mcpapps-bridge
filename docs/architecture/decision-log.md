# Architecture Decision Log

This log separates accepted product and architecture decisions from their current implementation
state. ADRs remain historical records; implementation notes may advance without rewriting the
original context or decision.

Read amended decisions together with their amendment notices. Sections labeled Historical
Implementation Snapshot describe their stated date, not current behavior or release obligations.
ADR 0016 is the current authority for session-oriented first-party readiness and Host action scope.

Implementation states:

- **Implemented**: the decision is represented in executable code and has focused validation.
- **Partial**: a usable slice exists, but one or more stated behaviors or release checks are absent.
- **Pending**: no executable implementation exists yet.
- **Proposed**: the decision is still under discussion and does not constrain implementation yet.

| ADR | Decision status | Implementation state | Summary |
| --- | --- | --- | --- |
| [0001](decisions/0001-managed-endpoints-and-session-ownership.md) | Accepted; amended by 0003, 0008, 0013, and 0014 | Partial | Managed topology, core-owned endpoint dispatch, isolated sessions, and v0.1 read-only management are implemented; writable management is deferred |
| [0002](decisions/0002-sqlite-persistence-and-configuration-authority.md) | Accepted; amended by 0008, 0013, and 0014 | Partial | SQLite, reset migrations, revisions, events, bootstrap, and management read adapters exist; v0.1 topology is frozen after seed |
| [0003](decisions/0003-mcp-apps-gateway-and-optional-agent-host.md) | Accepted; amended by 0008, 0010, 0011, 0012, 0014, 0015, and 0016 | Partial | Gateway, read-only management, streaming text Runs, and widget composition exist; native session/history and first-party Host HTTP remain incomplete |
| [0004](decisions/0004-first-release-scope-and-distribution.md) | Accepted; amended by 0007, 0008, 0012, 0014, and 0016 | Partial | Native session-oriented frontend readiness, first-party UI, and OCI delivery remain release blockers; product Host actions are deferred |
| [0005](decisions/0005-upstream-transport-task-ownership.md) | Accepted | Implemented | Upstream SDK contexts run and close in persistent owner tasks |
| [0006](decisions/0006-core-service-and-server-packages.md) | Accepted | Implemented | Protocol core, application services, and the deployable server are separate dependency-ordered workspace packages |
| [0007](decisions/0007-cembrid-identity-and-deployment-shells.md) | Accepted; brand superseded by 0009 | Partial | Retain Web/OCI and Tauri desktop service shells; its Cembrid identity is superseded |
| [0008](decisions/0008-restart-applied-managed-topology.md) | Accepted; v0.1 scope amended by 0014 | Pending | Retain restart-applied topology mutation as the basis for a post-v0.1 writable management milestone |
| [0009](decisions/0009-mabrid-product-identity.md) | Accepted; code migration timing amended by 0013 | Partial | Mabrid code identity migrates with the backend refactor; repository and remote migration remain deferred |
| [0010](decisions/0010-application-contexts-and-capability-composition.md) | Accepted; amended by 0011, 0012, 0013, 0014, 0015, and 0016 | Partial | Distinct contexts, reusable outbound integrations, and widget composition exist; Agent Session bindings and effective capabilities remain pending; product Host actions are deferred |
| [0011](decisions/0011-single-agent-target-and-endpoint-assignment.md) | Accepted; amended by 0012, 0014, 0015, and 0016 | Partial | Single Target, exclusive endpoint ownership, one-active-Run coordination, attribution, and assignment management exist; durable Agent Sessions are pending |
| [0012](decisions/0012-agent-runtime-profiles-and-integration-composition.md) | Accepted; amended by 0015 and 0016 | Partial | Profiles, typed Hermes discovery, and single-instance integration exist; native session/history, effective capabilities, and runtime availability are required before frontend implementation |
| [0013](decisions/0013-backend-semantic-boundaries-and-mabrid-code-identity.md) | Accepted | Implemented | Backend contexts are modularized, MCP transport is core-owned, provisional contracts are removed, and Mabrid code identity is adopted |
| [0014](decisions/0014-read-only-v0-1-management-plane.md) | Accepted | Implemented | v0.1 exposes read-only topology, status, readiness, Agent Target assignment, and session inspection while topology mutations remain deferred |
| [0015](decisions/0015-agent-host-runs-and-mcp-apps-endpoint-composition.md) | Accepted; amended by 0016 | Partial | Run attribution, fresh resources, widget composition, streaming, and controlled integration exist; timely tool/widget delivery and first-party HTTP remain pending; product Host actions are deferred |
| [0016](decisions/0016-session-oriented-host-and-frontend-contract-readiness.md) | Accepted | Pending | Runtime owns conversation history; Mabrid owns durable Agent Session bindings; native history/continuation, first-party contracts, and capability reporting gate the frontend rewrite |

## Current v0.1 Position

The aggregate gateway data plane and the ADR 0014 read-only backend management plane are complete
vertical slices. ADR 0015 establishes the composed text-Run and widget baseline. ADR 0016 defines
the next backend milestone before repository migration and frontend implementation:

- Verify and implement a native runtime session/history integration and durable Agent Session bindings without duplicating runtime-owned transcripts.
- Establish thin capability assembly, explicit observer failure policy, and timely tool/widget presentation independent of assistant deltas.
- Implement and freeze first-party Host HTTP/history/SSE contracts, lifecycle errors, and conservative capabilities and remote availability reporting.

Real MCP transport integration, OCI assembly, static frontend serving, and release-image startup
validation remain release work. First-party Agent Host and read-only management frontend workflows
follow the reviewed backend contracts. Writable topology management is outside v0.1 under ADR 0014;
product Host actions are outside v0.1 under ADR 0016. Desktop and broader future ideas do not expand
this milestone.
