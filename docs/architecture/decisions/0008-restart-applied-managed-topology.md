# ADR 0008: Restart-Applied Managed Topology

- Status: Accepted
- Date: 2026-08-21
- Amends: ADR 0001, ADR 0002, ADR 0003, and ADR 0004

## Context

The first release is primarily a personal client and trusted self-hosted Web application. The
first-party UI must eventually replace hand-edited topology YAML as the normal way to configure
upstream servers, endpoints, and bindings. SQLite is already authoritative for that managed
topology, and bridge sessions already capture immutable endpoint and upstream revisions.

Applying a topology mutation to a running gateway would add a separate runtime problem: published
endpoint indexes would need to refresh atomically, new sessions would need to select the new
revision while existing sessions remained pinned, and upstream runtimes might need reconnect or
drain policies. Tauri would add another process owner, but its sidecar supervision is outside the
v0.1 boundary.

Version 0.1 needs editable product configuration without taking on live topology reload or desktop
process management.

## Decision

### Configuration ownership

YAML and environment variables configure process and deployment concerns, including the listener,
SQLite path, logging, migrations, and bootstrap policy. While the management UI cannot yet perform
first-run setup, YAML may also contain a transitional topology seed. The seed is imported only when
the database is empty and is never treated as a second live source of truth. Once first-run UI
management is complete, topology seeding is no longer part of the normal product workflow and YAML
returns to process and deployment configuration only.

SQLite is authoritative for product-managed upstream servers, endpoints, bindings, and session
policies. The first-party UI and management HTTP API read and write this managed topology. Normal
startup does not merge later YAML topology changes into a non-empty database.

### Restart-applied publication

The gateway loads enabled current topology revisions once during process startup. That set is the
published runtime topology for the lifetime of the process.

Management mutations persist configuration for the next process start. A successful mutation:

1. validates the complete affected topology;
2. creates immutable upstream and endpoint revisions as required;
3. atomically advances the affected database head pointers; and
4. reports that a restart is required.

Changing an upstream revision also creates coherent new revisions for current endpoints that bind
that upstream. This preserves the existing rule that an endpoint revision captures exact upstream
revisions. The database transaction does not refresh the running coordinator, replace routers,
reconnect upstreams, or alter active bridge sessions.

The current process continues serving the topology loaded at startup. After restart, the new
process loads the saved database heads before accepting sessions. Existing sessions are closed by
normal process shutdown and are never migrated between topology revisions.

### Minimal management semantics

Version 0.1 supports the configuration operations required by the first-party UI: create, inspect,
revise, enable, and disable upstreams and endpoints, including endpoint bindings. Destructive
history deletion is not part of the normal API. A user-facing remove operation disables the
managed object while immutable revisions and session references remain available.

The server keeps a simple process-local `restart_required` latch. It becomes true after a
successful topology mutation and resets when a new process loads its startup topology. This latch
is a user-interface signal, not a durable topology generation protocol. Direct external database
mutation is unsupported.

Authentication and RBAC are deferred for the trusted personal-client profile. Management routes
remain separated from MCP data-plane routes, and sensitive connection values must not be returned
unredacted by read APIs.

### Restart ownership

The v0.1 Web service does not expose an HTTP endpoint that terminates or restarts its own process.
The UI reports that a restart is required. A user, service manager, or container runtime owns the
actual Web/OCI restart.

The future Tauri supervisor may expose a desktop host action that gracefully restarts its Python
sidecar. That capability belongs to the Tauri shell described by ADR 0007 and does not change the
gateway-service management contract.

### Explicitly deferred

Version 0.1 does not include:

- live coordinator or endpoint-index refresh;
- active-session topology migration;
- automatic upstream reconnect after configuration changes;
- a durable draft/published generation workflow;
- rollback orchestration or background topology reconciliation;
- a generic process-restart API; or
- Tauri sidecar management.

## Consequences

- The Web UI becomes the normal product-configuration surface without making YAML a live database;
  the current YAML topology seed remains only as transitional bootstrap compatibility.
- Configuration can be saved safely while sessions are active, but users must restart before the
  gateway behavior changes.
- Immutable revisions retain their session-history value without requiring hot reload semantics.
- An upstream revision mutation still republishes dependent endpoint revisions in one database
  transaction, but it does not coordinate with live runtime objects.
- A process-local restart flag is intentionally simpler than a durable applied-versus-desired
  generation model and may conservatively remain true after a user reverses a change.
- Tauri can later own sidecar restart through a shell adapter without entering bridge core or
  gateway service.

## Implementation Status

As of 2026-08-21:

- **Implemented:** SQLite is authoritative, seed-if-empty bootstrap is transactional, immutable
  revisions exist, and the coordinator loads published endpoints during startup.
- **Pending:** management commands, revision-producing update/disable transactions, read/write HTTP
  APIs, redacted management DTOs, the restart-required latch, and the first-party management UI.
- **Deferred:** live topology reload and desktop sidecar restart.
