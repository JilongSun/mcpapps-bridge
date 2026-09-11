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
- the optional Agent Target and its assigned stable Gateway endpoint path;
- bridge session history, current inspection snapshots, and paginated event history.

The HTTP control-plane prefix is `/api/v1/gateway`. MCP data-plane routes remain under `/mcp`, and
OpenAI-compatible Agent Host routes remain under `/v1`.

Read responses expose only the current revision metadata (`revision_id`, `revision_number`, and
`created_at`). Revision-history listing is not part of v0.1. The trusted developer-preview profile
does not introduce field-level redaction in this read-only slice; configured connection values are
returned as persisted. Authentication, RBAC, secret references, and redaction must be designed
together before a topology write API is added.

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
| `GET` | `/api/v1/gateway/status` | Gateway process, publication, and optional Agent Target status |
| `GET` | `/api/v1/gateway/topology` | One internally consistent current topology snapshot |
| `GET` | `/api/v1/gateway/sessions` | Filtered bridge session history with opaque keyset pagination |
| `GET` | `/api/v1/gateway/sessions/{session_id}` | One bridge session lifecycle record |
| `GET` | `/api/v1/gateway/sessions/{session_id}/snapshot` | Current detailed inspection snapshot |
| `GET` | `/api/v1/gateway/sessions/{session_id}/events` | Ordered event history after a sequence cursor |

`/topology` returns upstreams and endpoints together rather than introducing separate CRUD-shaped
resource routes. Each endpoint contains its bindings, and current upstream and endpoint revisions
include `revision_id`, `revision_number`, and `created_at`. The snapshot includes enabled and
disabled managed heads, not only the enabled endpoints loaded into the running coordinator.

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
and configured application composition completed and whether the HTTP application is accepting
work. A process with no enabled published endpoint returns `503` because the Gateway data plane has
no serviceable route. The response does not require the independently deployed Hermes runtime or
every configured upstream to be reachable. Those remote checks need explicit timeout, degradation,
and capability semantics.

When Agent Host is enabled, management status exposes the configured Target identity and the stable
assigned `endpoint_path`, for example `/mcp/agent-tools`. The backend does not construct an absolute
MCP URL in v0.1 because listener configuration cannot reliably determine the address reachable by
Hermes across reverse proxies or container networks.

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
- Secret references, encryption, and field-level response redaction.
- Hermes capability probing and effective-capability calculation.
- Absolute public MCP URL construction.
- Management event streaming.

## Implementation Status

As of 2026-09-11:

- **Implemented foundations:** SQLite-authoritative seed-if-empty topology, immutable revisions,
  startup publication, Agent Target endpoint assignment validation, bridge session history, events,
  snapshots, and liveness.
- **Pending:** read-only topology DTOs and routes, status and readiness contracts, Agent Target
  assignment exposure, paginated session/event queries, RFC 9457 error mapping, and the first-party
  read-only management UI.
- **Deferred beyond v0.1:** topology mutations and all restart-required write behavior.
