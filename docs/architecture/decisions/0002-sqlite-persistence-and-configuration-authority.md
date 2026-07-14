# ADR 0002: SQLite Persistence and Configuration Authority

- Status: Accepted
- Date: 2026-07-14

## Context

The bridge currently creates in-memory repositories and an in-memory session store factory in `mcp/builder.py`. These implementations are useful for controlled tests and debugger runs, but all topology, session records, snapshots, and events disappear when the process exits.

The YAML file currently contains both host settings and upstream topology. Future administrative CRUD APIs require one authoritative topology store. Treating both YAML and the database as live sources of truth would make changes order-dependent and could silently overwrite administrative updates during restart.

SQLite is the first persistent backend. The live MCP SDK servers, upstream clients, and task groups remain process-local and cannot be restored from database rows after a process restart.

## Decision

### Storage profiles

The normal application uses the `sqlite` storage profile by default. `debug_main.py` explicitly selects the `memory` profile.

The existing `repositories/memory.py` implementations are process-local repositories, not an in-memory SQL database. The memory profile uses those repositories and `InMemoryBridgeSessionStoreFactory` directly. It does not use `sqlite:///:memory:`.

Storage selection is an assembly concern. Domain models, `BridgeManager`, MCP runtimes, handlers, and API routes depend only on repository and session-store ports.

### Configuration boundary

YAML and environment variables configure the host process:

- API bind host and port.
- Storage profile and database URL.
- Logging and bootstrap policy.
- Optional topology seed definitions.

The repository uses `backend/var/` for mutable runtime artifacts such as the SQLite database and future local log files. The directory is not source-controlled. The default SQLite path is:

```text
backend/var/mcpapps-bridge.db
```

Configuration uses a path field rather than exposing a SQLAlchemy URL. Relative paths are resolved from the YAML file directory, making the default value `./backend/var/mcpapps-bridge.db` in the repository-root configuration. Environment overrides may supply an absolute deployment path.

SQLite is authoritative at runtime for:

- Upstream server definitions and transport settings.
- Endpoint definitions, bindings, and session policies.
- Bridge session records.
- Session events and current inspection snapshots.

The default bootstrap policy is `seed-if-empty`:

1. Create or migrate the database schema.
2. If no upstream servers and endpoints exist, import the topology seed from YAML in one transaction.
3. If topology already exists, do not compare, merge, or overwrite it from YAML.
4. Load all enabled published endpoints from the database into `BridgeManager`.

The topology seed format adds explicit endpoint definitions and bindings so it can describe passthrough and aggregate endpoints. For compatibility, a legacy configuration containing `defaultUpstream` but no endpoints generates one same-slug passthrough endpoint during the first seed. This compatibility conversion is input-only and does not recreate or modify that endpoint after the database contains topology.

Future explicit import/export commands may merge topology, but normal startup never performs an implicit merge. Administrative CRUD writes the database, not the YAML file.

### Relational schema

The initial schema uses seven tables.

| Table | Responsibility |
| --- | --- |
| `upstream_servers` | Upstream identity, slug, display name, enabled state, metadata, and one transport configuration |
| `endpoints` | Published endpoint identity, slug, display name, mode, enabled state, metadata, and session policy |
| `endpoint_bindings` | Ordered endpoint-to-upstream bindings with namespace and enabled state |
| `bridge_sessions` | Domain session identity, endpoint, transport-session correlation, lifecycle status, timestamps, and failure details |
| `upstream_sessions` | Auditable upstream connection lifecycle for each bridge session and upstream server |
| `session_events` | Append-only typed session event envelopes and payloads |
| `session_snapshots` | One replaceable current inspection snapshot per bridge session |

Transport configuration is stored on `upstream_servers` as typed columns plus JSON fields where the values are naturally maps or lists:

- `transport`, `url`, `command`, `cwd`, and `timeout_seconds` are scalar columns.
- `args`, `env`, `headers`, and domain metadata are JSON columns.

Endpoint session policy is stored on `endpoints` because it is a required one-to-one value object, not an independently managed entity. It uses scalar columns for upstream session mode, lazy connection behavior, and idle timeout.

This avoids one-row auxiliary tables that add joins without providing an independent lifecycle. Credentials must not be persisted in plaintext JSON. A later secrets provider may store references; until then, sensitive values should be supplied through environment expansion during explicit topology import.

Minimum constraints and indexes are:

- Unique `upstream_servers.slug`.
- Unique `endpoints.slug`.
- Unique `bridge_sessions.downstream_transport_session_id` when non-null.
- Index `endpoint_bindings(endpoint_id, enabled, priority)`.
- Index `bridge_sessions(endpoint_id, status, created_at)`.
- Unique `upstream_sessions(bridge_session_id, upstream_server_id)` for the initial isolated model.
- Monotonic `session_events.sequence` unique within a session, with index `(session_id, sequence)`.
- Unique `session_snapshots.session_id`.

UUIDs are stored in a portable SQLAlchemy representation so the same domain IDs work with SQLite and PostgreSQL. Timestamps are stored as UTC. SQLite foreign keys are enabled for every connection.

### Repository and transaction boundary

SQLAlchemy ORM classes stay under a persistence package and never enter domain or MCP modules. Async repository adapters translate between ORM rows and Pydantic domain models.

A short-lived async unit of work owns each database transaction. Repository methods must not retain an `AsyncSession` across MCP network calls. Topology publication, session creation, transport binding, lifecycle transitions, and event/snapshot updates use explicit transaction boundaries.

The persistent session store appends an event and updates its snapshot in one transaction. `wait_for_events` uses an in-process notification primitive for active sessions and queries persisted events by sequence. SQLite is not used as a polling event bus.

### Schema management

Alembic owns schema migrations from the first persistent release. Application startup applies pending migrations by default in the supported single-process SQLite deployment. A configuration switch and dedicated CLI command remain available for environments that require controlled migrations. The application does not use `metadata.create_all()` as the long-term migration mechanism.

Session events are retained indefinitely in the first persistent release. Retention by age or per-session count is deferred until real storage growth can inform a pruning policy. Manual pruning must preserve referential integrity and rebuild or retain the current snapshot.

### Restart semantics

At startup, any session left in `starting`, `active`, or `closing` is marked `failed` with a restart reason and close timestamp. Persisted session history remains queryable, but transport sessions and upstream connections are never reconstructed.

### Deployment profile

The supported SQLite deployment is one application process with one Uvicorn worker. Live MCP transport state remains in that process. SQLite persistence improves configuration durability and inspection history; it does not provide session failover or horizontal scaling.

PostgreSQL is the later persistence target. Multi-process operation additionally requires session affinity or an explicit distributed ownership design; changing the database alone cannot make live MCP SDK sessions portable.

## Consequences

- Production restarts preserve managed topology and historical debugging data.
- Debug runs remain disposable and do not modify the normal SQLite database.
- YAML becomes safe bootstrap input instead of a competing management database.
- Future CRUD APIs can operate against stable repository and transaction contracts.
- Session event persistence adds write volume, but provides the audit surface needed by the management product.
- SQLite deployments are intentionally single-process.

## Implementation Sequence

1. Add storage and bootstrap configuration models; make SQLite the normal default and memory an explicit debug override.
2. Add SQLAlchemy engine/session factories, ORM models, and Alembic migrations.
3. Implement async SQLAlchemy repositories and the persistent session store factory.
4. Refactor application assembly to accept a storage bundle rather than constructing memory adapters directly.
5. Implement transactional `seed-if-empty` topology bootstrap and database-driven endpoint loading.
6. Mark interrupted sessions failed during startup and validate restart behavior.
7. Add topology CRUD APIs after repository contracts and authorization requirements are reviewed.

## Deferred Decisions

- Exact environment variable names for storage overrides will be chosen with the configuration implementation.
- Event retention and pruning are deferred until usage data establishes a safe default.