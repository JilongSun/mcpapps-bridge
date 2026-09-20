# ADR 0014: Read-Only v0.1 Management Plane

- Status: Accepted
- Date: 2026-09-11
- Amends: ADR 0001, ADR 0002, ADR 0003, ADR 0004, ADR 0008, ADR 0010, and ADR 0011 for
  v0.1 scope only

## Context

ADR 0008 selected restart-applied topology mutation so the first-party UI could replace hand-edited
topology configuration without requiring live Gateway reload. Implementing that write surface still
requires a complete command model, optimistic concurrency, revision-producing transactions,
dependent endpoint republication, restart reporting, credential handling, and recovery behavior.

Those contracts are larger than the read and inspection capabilities needed to complete the v0.1
developer preview. Freezing them around the current transitional YAML seed would also make that
bootstrap format a premature public management contract. The write model should instead be designed
with the future first-party configuration workflow and a dedicated secret-reference contract.

The current persistence model already supports a smaller coherent boundary: an empty SQLite
database is seeded once, immutable revisions are loaded at startup, and the resulting process can
expose topology and session state without mutating either the published runtime or the saved
topology.

## Decision

### Read-only management scope

The v0.1 management plane is read-only. It exposes:

- current managed upstreams and their current revision metadata;
- current managed endpoints, bindings, and their current revision metadata;
- local process status and readiness;
- the optional Agent Target and its declared Gateway endpoint assignment;
- bridge session history, current inspection snapshots, and paginated event history.

Gateway management routes use `/api/v1/gateway`. Agent Host management routes use
`/api/v1/agent-host`. MCP data-plane routes remain under `/mcp`, and OpenAI-compatible Agent Host
routes remain under `/v1`.

Read responses expose only the current revision metadata (`revision_id`, `revision_number`, and
`created_at`). Revision-history listing is not part of v0.1. Ordinary connection fields are
returned, but HTTP header and stdio environment values are never returned by the management API.
Those maps are represented as key names with `configured: true`; this avoids expanding the exposure
of values that are temporarily stored in plaintext without introducing encryption or a secret
provider. Authentication, RBAC, durable secret references, and write-time redaction semantics must
be designed before a topology write API is added.

Session events use cursor-style reads based on their existing monotonically increasing sequence:
clients provide an `after` sequence and a bounded `limit`. A management SSE subscription is not
part of this slice.

All management JSON fields use `snake_case`. This is an explicit HTTP contract rather than a direct
serialization promise for internal Pydantic or ORM models.

### HTTP contract

The v0.1 read-only routes are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process liveness |
| `GET` | `/ready` | Local service readiness |
| `GET` | `/api/v1/gateway/status` | Gateway process and publication status |
| `GET` | `/api/v1/gateway/topology` | One internally consistent current topology snapshot |
| `GET` | `/api/v1/gateway/sessions` | Filtered bridge session history with opaque keyset pagination |
| `GET` | `/api/v1/gateway/sessions/{session_id}` | One bridge session lifecycle record |
| `GET` | `/api/v1/gateway/sessions/{session_id}/snapshot` | Current detailed inspection snapshot |
| `GET` | `/api/v1/gateway/sessions/{session_id}/events` | Ordered event history after a sequence cursor |
| `GET` | `/api/v1/agent-host/target` | Configured Agent Target and Gateway endpoint assignment |

`/topology` returns upstreams and endpoints together rather than introducing separate CRUD-shaped
resource routes. Each endpoint contains its bindings, and current upstream and endpoint revisions
include `revision_id`, `revision_number`, and `created_at`. The snapshot includes enabled and
disabled managed heads, not only the enabled endpoints loaded into the running coordinator. It also
returns the configured `advertised_base_url`, and each endpoint includes its stable `endpoint_path`
and derived `advertised_url` when the base URL is configured.

`/status` is a concise operational summary rather than another topology representation. It returns
the service version, process lifecycle state, frozen-seeded topology mode, advertised base URL, and
the count and slugs of process-lifetime published endpoints. Full managed definitions and revision
metadata remain exclusive to `/topology`.

The topology response is therefore served by a dedicated application-owned management read port.
It must not reuse the runtime `TopologyReader.list_current_revisions()` behavior, which intentionally
returns only enabled published endpoints and embeds only the upstream revisions reachable through
those endpoints. The SQLAlchemy adapter executes the management snapshot query in one read
transaction so its upstream, endpoint, and binding heads cannot be mixed across database states.

`/sessions` defaults to 50 items and accepts at most 200. It supports `endpoint_id` and lifecycle
`status` filters. Its `cursor` is an opaque string representing a descending `(created_at,
session_id)` keyset; clients must not construct or parse it. Responses use an `items` array and a
nullable `next_cursor`.

`/events` defaults to 100 items and accepts at most 500. Its `after` value is the last observed
non-negative event sequence, with zero meaning the beginning. Each returned item is an envelope
containing the persisted `sequence` and the existing typed event payload. The response includes a
nullable `next_after`, which is present only when another page is available. This API does not
change the provider-independent event models solely to expose a persistence sequence.

Session snapshots and events return the complete persisted diagnostic content, including tool
arguments, tool results, resource contents, and error details. This matches the trusted
developer-preview deployment profile. Deployments must not expose these unauthenticated management
routes to an untrusted network.

Management errors use RFC 9457 Problem Details with `application/problem+json`. The response
contains stable `type`, `title`, `status`, `detail`, and `code` fields. Validation failures, unknown
sessions, malformed cursors, and not-ready responses use this same error shape rather than exposing
FastAPI's default validation document.

### Frozen seeded topology

The transitional YAML topology remains input to `seed-if-empty`. After the initial seed, the
SQLite topology is frozen for the lifetime of that v0.1 database. Normal startup never merges YAML
changes into a non-empty database.

The supported developer-preview reset workflow is to stop the process, replace or remove the
SQLite database, update the YAML seed, and start again. This intentionally discards the session
history stored in that database. v0.1 does not add a topology import, merge, re-seed, or migration
command to avoid creating a second mutation contract.

YAML topology remains transitional rather than the intended long-term management surface. A later
write-management decision will define database mutations for the first-party frontend and may then
remove topology from the normal YAML product workflow. A backend-only YAML-managed deployment mode
is outside the v0.1 decision.

### Readiness and Agent Target assignment

`/health` remains process liveness. `/ready` reports whether local bootstrap, topology publication,
and configured application composition completed, whether the HTTP application is accepting work,
and whether SQLite answers a lightweight query. A process with no enabled published endpoint or an
unavailable database returns `503` because the Gateway data plane or its required persistence is not
serviceable. The response does not require the independently deployed Hermes runtime or every
configured upstream to be reachable. Those remote checks need explicit timeout, degradation, and
capability semantics.

`bridge.advertisedBaseUrl` is the deployment owner's declaration of the HTTP(S) origin reachable by
external MCP clients. It is distinct from the listener bind host and port. Personal deployments may
use `http://127.0.0.1:8765`; container deployments may use a service DNS name; shared deployments
should normally use a stable internal DNS or reverse-proxy origin. The value must not contain a
path, query, or fragment. It is required when Agent Host is enabled and optional otherwise. Mabrid
does not infer it from `apiHost` or `apiPort`.

When Agent Host is enabled, `/api/v1/agent-host/target` exposes the Target identity and its declared
Gateway endpoint assignment. The assignment uses the stable endpoint slug and includes the resolved
endpoint ID, fixed `streamable-http` transport, `endpoint_path`, and `advertised_url`. The advertised
URL is the exact value the operator should configure in Hermes. Legacy SSE remains a Gateway
compatibility transport but is not offered as an Agent Target assignment choice. This remains
non-invasive: Mabrid validates that the assigned endpoint exists and is enabled, but it does not
modify Hermes configuration or claim that the external Hermes process currently uses that URL.
When Agent Host is disabled, the route returns an RFC 9457 `404` with code
`agent_host_disabled`.

### Deferred write model

The following ADR 0008 behaviors move out of v0.1 but remain the intended basis for a later design:

- create, revise, enable, and disable commands for upstreams and endpoints;
- endpoint-owned binding updates;
- complete affected-topology validation;
- immutable revision creation and atomic head advancement;
- coherent dependent endpoint republication after an upstream change;
- optimistic concurrency;
- process-local restart-required reporting; and
- a credential-reference and redaction contract.

No v0.1 HTTP route writes topology, edits YAML, restarts the process, or refreshes the live
coordinator.

## Consequences

- The v0.1 backend gains a useful topology and diagnostics surface without committing to an
  incomplete mutation or secret-storage design.
- SQLite remains authoritative after first-run seeding, but topology changes require a destructive
  database reset during the developer preview.
- The v0.1 frontend can inspect configuration and operation but cannot manage topology.
- ADR 0004's writable management UI and mutation release gate no longer block v0.1.
- ADR 0008 remains accepted architecture for a later writable management milestone rather than an
  implementation requirement for v0.1.
- Readiness remains conservative and local; it does not overstate remote Agent Runtime or upstream
  availability.

## Explicitly Deferred

- All topology mutation HTTP APIs and application commands.
- A topology writer, unit of work, and optimistic concurrency contract.
- Revision-history APIs.
- Secret references, encryption, and write-time credential semantics.
- Hermes capability probing and effective-capability calculation.
- Management event streaming.

## Implementation Plan

### Configuration and advertised URLs

`BridgeRuntimeConfig` gains `advertised_base_url`. File syntax remains camel case as
`advertisedBaseUrl`. Validation accepts only an HTTP(S) origin with no path other than `/`, no
query, and no fragment. The normalized runtime value has no trailing slash. Agent Host
configuration validation requires this value when `agentHost.enabled` is true.

Endpoint URLs are joined structurally from the validated origin and `/mcp/{endpoint_slug}`; they
are never assembled from `apiHost`, `apiPort`, forwarded headers, or unchecked string
concatenation. Startup logging uses the advertised URL when configured and otherwise logs only the
listener-local path. The current logging that presents the listener bind address as an MCP endpoint
URL is replaced.

### Application read contracts

The Gateway application owns three new read-only query boundaries:

- `TopologySnapshotReader` under `mabrid.application.gateway.topology` returns all current upstream
  and endpoint heads, current revision metadata, and nested binding revision references in one
  `TopologySnapshot`.
- `SessionHistoryReader` under `mabrid.application.gateway.sessions` returns filtered session pages
  and individual lifecycle records.
- `SessionInspectionReader` under `mabrid.application.gateway.inspection` returns snapshots and
  sequenced event pages.

These are separate from runtime ports. `TopologyReader` continues to serve process-lifetime
publication and therefore continues to return only enabled publishable endpoint revisions.
`BridgeSessionRepository` continues to serve lifecycle commands and point lookups used by the
coordinator. Pagination and diagnostic HTTP queries are not added to either runtime port.

The application query contracts use typed values rather than HTTP strings:

```text
SessionPageRequest
  endpoint_id: UUID | None
  status: BridgeSessionStatus | None
  before: SessionKeyset | None
  limit: int

SessionKeyset
  created_at: datetime
  session_id: UUID

SessionPage
  items: list[BridgeSessionRecord]
  next_keyset: SessionKeyset | None

SessionEventPage
  items: list[SequencedSessionEvent]
  next_after: int | None
```

`SequencedSessionEvent` contains the persistence sequence and the existing typed `SessionEvent`.
The existing event contracts do not gain storage-specific fields.

Topology connection read models preserve ordinary connection details but represent `headers` and
stdio `env` as lists of `{name, configured}` entries. Secret values therefore do not cross the
application management-read boundary. The runtime topology revision contracts remain unchanged and
continue to contain the resolved values required to open upstream connections.

### Persistence adapters

`SqlAlchemyTopologySnapshotReader` lives with the existing topology persistence adapters. It loads
all upstream heads, upstream current revisions, endpoint heads, endpoint current revisions, current
bindings, and endpoint binding revisions in one read transaction. Missing head revisions or
incoherent binding references are treated as persisted-topology corruption rather than silently
omitted data.

`SqlAlchemySessionHistoryReader` and `SqlAlchemySessionInspectionReader` live with session
persistence. Session pagination orders by `created_at DESC, session_id DESC`, applies a strict tuple
keyset predicate, fetches `limit + 1`, and emits a next keyset only when another page exists. Event
pagination orders by sequence, fetches `limit + 1`, and validates every persisted payload through
the existing `SessionEvent` type adapter. Snapshot absence for a known session is represented as the
default application snapshot; an unknown session remains a `404`.

The existing lifecycle repository is not widened with HTTP-oriented filtering or pagination.
Database readiness uses a separate lightweight server persistence check (`SELECT 1`) rather than a
topology or session query.

### Server composition

Gateway composition creates one lifecycle repository, one runtime topology reader, one topology
snapshot reader, one session history reader, one session inspection reader, and one inspection
store factory from the shared SQLite session factory. A frozen `GatewayManagementComposition`
carries only the read services and deployment metadata needed by the HTTP layer.

Agent Host composition retains the resolved published endpoint used during startup validation.
Its frozen management view combines:

- the application-owned `AgentTarget`;
- the resolved endpoint ID, slug, and path;
- fixed MCP transport `streamable-http`; and
- the URL derived from `bridge.advertisedBaseUrl`.

This composition view is an inbound presentation dependency, not a new field on the
provider-neutral `AgentTarget`. The application Target continues to declare only the stable
endpoint slug.

`BootstrapResult` returns Gateway and optional Agent Host management compositions alongside the
existing runtime owners. `MabridServerRuntime` passes those read-only dependencies into
`create_app()`. API routers never access `AsyncSession`, ORM rows, YAML models, or mutable global
state.

### HTTP adapters

Server-owned Pydantic response DTOs live under `mabrid.server.api.management`. They serialize with
the agreed `snake_case` field names and explicitly map application read models; ORM and runtime
models are never returned directly.

The router split is:

```text
mabrid.server.api.management.gateway
  /api/v1/gateway/status
  /api/v1/gateway/topology
  /api/v1/gateway/sessions...

mabrid.server.api.management.agent_host
  /api/v1/agent-host/target

mabrid.server.api.readiness
  /health
  /ready
```

The session cursor is versioned opaque base64url JSON containing the typed keyset. The decoder
rejects unknown versions, malformed payloads, missing fields, and invalid timestamps or UUIDs. It
is signed by neither a secret nor a database token because it conveys no authority; strict
validation and bounded queries are sufficient.

Problem Details use stable Mabrid URNs such as `urn:mabrid:problem:session-not-found` and include a
machine-readable `code`. The first implementation defines at least:

- `invalid_request` (`422`);
- `invalid_cursor` (`400`);
- `session_not_found` (`404`);
- `agent_host_disabled` (`404`);
- `not_ready` (`503`); and
- `persistence_unavailable` (`503`).

FastAPI request-validation errors are converted to this same response family. Unexpected
persistence corruption remains a logged `500` Problem Details response and does not expose row or
credential content.

### Focused validation

Application tests cover query value validation and sequenced event page contracts without
FastAPI or SQLAlchemy. Server persistence tests cover complete topology snapshots, disabled heads,
credential-key projection, deterministic keyset pagination, filters, event pagination, default
snapshots, and corrupt-reference failures.

HTTP contract tests cover every route and response model, opaque cursor continuation, Problem
Details, disabled Agent Host behavior, fixed Target transport, advertised URL construction, and
absence of header/env values. Readiness tests cover no published endpoint, SQLite failure, and a
healthy locally composed process without contacting Hermes or upstream servers.

Composition tests prove that an enabled Agent Host requires `advertisedBaseUrl`, rejects a missing
or disabled assigned endpoint, and exposes the exact declared assignment while leaving the
application `AgentTarget` provider-neutral.

## Implementation Status

As of 2026-09-20, the backend decision is **Implemented**.

Implemented behavior includes:

- validated advertised MCP origins and structurally derived endpoint URLs;
- application-owned topology snapshot, session history, and session inspection read ports;
- transactional SQLite topology snapshots, deterministic session keyset pagination, and sequenced
  event pagination;
- explicit Gateway and Agent Host management compositions with a local SQLite readiness probe;
- all read-only Gateway and Agent Host routes listed in this ADR, plus `/health` and `/ready`;
- server-owned `snake_case` DTOs, opaque versioned cursors, and RFC 9457 Problem Details; and
- focused contract, persistence, composition, readiness, architecture, and regression coverage.

The implementation does not add a migration, topology mutation path, restart latch, Hermes
reachability or capability probing, secret encryption, or management event streaming. The
first-party frontend workflows remain separate product work and do not change the completed backend
contract recorded here.
