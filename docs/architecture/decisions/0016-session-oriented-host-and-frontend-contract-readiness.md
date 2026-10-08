# ADR 0016: Session-Oriented Host and Frontend Contract Readiness

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR 0003, ADR 0004, ADR 0010, ADR 0011, ADR 0012, and ADR 0015

## Context

ADR 0015 established a working Agent Run, Gateway operation, and MCP Apps widget workflow through
the Hermes Chat Completions integration. That text-only interface proves execution and streaming;
it does not define the durable first-party conversation experience.

Mabrid is a non-invasive host of independently deployed agent runtimes. The runtime owns its agent
loop, conversation contents, history, and context continuity. Building a second transcript store
or requiring the frontend to reconstruct and resend that history would give Mabrid responsibilities
that belong to the runtime.

The next backend milestone is first-party contract readiness, not merely router reorganization.
Native session binding, history loading, switching, and continued execution must work before the
frontend rewrite starts. The owner has explicitly included those behaviors in this milestone.

Older ADRs contain historical interface choices and implementation snapshots. Their amendments
must identify which obligations still apply without treating an old snapshot as current evidence.

## Decision

### Runtime-owned conversations and Mabrid-owned sessions

The first-party Host is session-oriented. An **Agent Session** is a durable Mabrid identity used to
select, reopen, and invoke a conversation owned by one configured runtime deployment.

Mabrid persists the session identity, Target and runtime binding, opaque remote session reference,
and necessary lifecycle and display metadata. The runtime remains authoritative for message
history and conversational context. History is fetched through an integration and normalized for
presentation, not copied into a Mabrid transcript database or replayed as a replacement for native
continuity. Existing Gateway diagnostic persistence remains a separate responsibility.

The application owns a session repository port; the server supplies its SQLite implementation and
migrations. Remote session identity is scoped to the configured runtime deployment, not just the
integration kind. Reconfiguring a Target must not silently attach an existing session to another
runtime or create a replacement conversation when its remote session cannot be found.

The identities remain distinct:

| Identity | Owner and lifetime |
| --- | --- |
| Agent Target | Deployment-selected runtime and Gateway endpoint assignment |
| Agent Session | Durable Mabrid handle for one runtime-owned conversation |
| Remote session | Opaque runtime-owned conversation and continuity reference |
| Agent Run | One admitted execution within an Agent Session |
| Gateway session | MCP transport lifecycle, independent of conversation lifetime |
| Tool invocation and widget | Activity attributable to one Run |

The user selects an Agent Session rather than a model or runtime protocol. Switching sessions
selects another binding; it does not restart the runtime or assume one MCP transport session per
conversation. Each first-party Run belongs to exactly one Agent Session. Compatibility requests
without a session remain possible but do not acquire fictional native continuity.

Runtime-independent means a common session-facing contract translated by integrations. It does
not promise conversation migration between runtimes, simultaneous Targets, or automatic fallback
to another runtime. v0.1 retains one configured Target and at most one active or settling Run
across all of its sessions, as required for endpoint-based MCP Apps attribution by ADR 0015.

### Native session integration before frontend implementation

The initial first-party integration must provide:

- creating or explicitly binding a native remote session;
- listing and reopening persisted Mabrid session handles;
- fetching runtime-owned history for a selected session; and
- starting a streamed Run with new input bound to that native session.

Discovery or import of additional remote conversations is optional until the selected runtime's
actual API has been verified. It is distinct from listing locally persisted session handles.
Renaming, deleting, branching, and exporting conversations are not implied by the minimum scope.

Application ports express these behaviors without Hermes request models, SDK types, headers, or
endpoint paths. Runtime-specific history is normalized into typed content for the frontend;
unsupported content must remain distinguishable rather than silently becoming assistant text.
Narrow session/history ports supplement execution ports instead of adding unsupported methods to
every `AgentRuntime` implementation.

The concrete Hermes session and execution interface must be selected from verified runtime API
evidence before adapter implementation. This ADR does not assume that Chat Completions session
headers, Responses, or Hermes Runs provide equivalent behavior. The selected integration may
compose multiple remote interfaces behind its application ports, but the frontend cannot select
those interfaces per Run.

The current Chat Completions adapter remains a working compatibility and protocol-validation
slice. It is not the permanent first-party session contract. Standard `/v1/models` and
`/v1/chat/completions` ingress remains separate; neither a new runtime interface nor this decision
requires implementing `/v1/responses` ingress.

Local message-history replay, invented remote session IDs, and an empty-history success response
are not fallback implementations for missing native session support. Until native behavior is
implemented and verified, capability reporting must identify it as unavailable and the frontend
readiness gate remains unmet.

### Frontend surfaces and HTTP ownership

The frontend is prepared against four functional surfaces, without prescribing page layout:

| Surface | Required backend contract |
| --- | --- |
| Agent workspace | Session list and selection, native history, new input, assistant stream, tool activity/results, widgets, and Run state |
| Gateway topology | Read-only upstream, endpoint, binding, and assigned MCP URL views |
| Session inspection | Gateway session records, snapshots, paged events, resources, and failures |
| Connection and capability status | Product capabilities, local readiness, remote runtime availability, and unsupported or disabled reasons |

Existing management paths stay intact. The planned first-party namespace is `/api/v1/host`:

| Planned interface | Purpose |
| --- | --- |
| `GET /api/v1/host/sessions` | List persisted Agent Session handles |
| `POST /api/v1/host/sessions` | Create a native conversation and persist its Mabrid binding |
| `GET /api/v1/host/sessions/{session_id}` | Inspect an Agent Session's public metadata and binding status |
| `GET /api/v1/host/sessions/{session_id}/history` | Load normalized history from the bound runtime |
| `POST /api/v1/host/sessions/{session_id}/runs` | Admit new input and return the composed presentation stream over SSE |
| `GET /api/v1/capabilities` | Report the effective product capability surface |

These paths are planned contracts, not implemented endpoints. Exact request, pagination, history,
event, and error schemas are frozen after the concrete runtime interface is verified. The frontend
uses `fetch` for POST-based SSE; a WebSocket is not required for this one-way presentation stream.
Cancellation transport must be decided before schema freeze; it must not imply remote stopping
when the runtime integration cannot provide it.

MCP `/mcp/{endpoint_slug}`, standard OpenAI `/v1/*`, first-party Host, and read-only management
remain distinct inbound adapters. OpenAI SSE cannot carry private widget envelopes. Gateway
inspection event pagination is not a substitute for the live Host stream.

Public Host DTOs expose session, Run, tool-invocation, and widget identities needed by the UI.
They do not serialize internal `session_key` and `operation_key` as presentation contracts.
Explicit diagnostic links may expose a separate Gateway session identifier without conflating it
with the Agent Session identifier.

### Timely presentation and lifecycle contracts

The Host presentation stream combines assistant, tool, resource, and widget activity without
changing their domain ownership. Tool and widget delivery must not depend on another assistant
delta arriving. Delivery order is contiguous per Run; it is not a promise of globally sorted
wall-clock timestamps or durable event replay.

Tool results remain visible when a widget fails. Resource contents, MIME types, relevant metadata,
and sandbox restrictions are explicit renderer inputs. Loading native history does not promise
reconstruction of old process-local widgets: when no renderable payload exists, the frontend shows
the historical tool result and an unavailable widget state. It must not re-execute tools or read
resources solely to fabricate a historical widget.

Before contract freeze, schemas and focused tests must distinguish admission rejection, runtime
failure, widget failure, cancellation, and stream disconnection. They must specify session
switching during an active Run, missing remote history, runtime-binding changes, and any replay or
reconnection limitations. Switching the selected UI session is not itself a remote stop command.
Closing a local stream must clean up local resources but cannot be advertised as confirmed remote
cancellation. Unknown remote execution state must not permit unsafe overlapping endpoint-based
attribution.

### Conservative capabilities and bounded composition

Capabilities distinguish locally implemented behavior, deployment selection, verified remote
support, and current availability. Unknown support is not `true`. Session/history capability,
streaming, and remote stop are separate facts. A remote runtime outage may disable Host operations
without making the independently usable Gateway unready.

A thin application assembly boundary may compose Target coordination, operation attribution,
activity projection, optional MCP Apps, and Host presentation through typed ports. Configuration,
secret resolution, runtime construction, database lifecycle, and startup rollback remain server
responsibilities. `HostEventStream` remains per-Run presentation rather than a process-level
plugin manager. There is no generic event bus, dynamic registry, or live capability loader.

Observer ordering and failure policy are explicit contracts. Optional usage recording must not
break MCP operations. Attribution and widget-settling failures cannot simply be swallowed if that
would lose causation or leave a Run waiting forever. Focused tests must establish cleanup and
settlement behavior without assuming every observer has the same reliability policy.

### Host actions are outside v0.1

This ADR defers host-owned conversational follow-up dispatch and other product Host actions beyond
v0.1, amending ADR 0004 and ADR 0015. MCP Apps protocol preservation remains unchanged.

The first-party renderer must still support the initialization and data exchange needed to render
a widget, apply sandbox restrictions, and explicitly reject unsupported host methods or actions.
Capabilities must not claim an interactive follow-up workflow that the Host cannot execute.

## Consequences

- Native session/history integration is a backend prerequisite for the frontend rewrite, not a
  post-v0.1 idea.
- Mabrid persists conversation handles without becoming a second owner of conversation history.
- Future runtime integrations translate a common session contract rather than exposing vendor
  protocols to the frontend.
- Multiple sessions do not weaken the single-active-Run correlation guarantee.
- Router organization follows the reviewed behavior and DTO boundaries instead of becoming an
  independent renaming exercise.
- Earlier streaming and widget integration tests remain useful but do not prove native session
  continuity, immediate activity delivery, first-party HTTP behavior, or release readiness.

## Implementation Sequence

Each numbered item is a separate review and manual-commit batch. Implementation cannot claim a
later gate merely because its routes or types have been declared.

1. Record this decision and reconcile the affected ADRs and current decision log.
2. Verify the concrete runtime's native session, history, execution, and cancellation interfaces;
   define typed application ports, public schemas, and a controlled contract fixture.
3. Implement durable Agent Session bindings and native create/reopen/history/continuation through
   the selected integration, with restart and missing-remote-session tests.
4. Establish thin capability assembly, observer ordering, and failure/settlement contracts without
   moving server infrastructure into the application package.
5. Implement tool activity and timely composed Host delivery, including periods without assistant
   text and early stream closure.
6. Implement first-party Host HTTP DTOs and routes, including session-bound SSE, admission, error,
   cancellation, and disconnection behavior. Preserve standard OpenAI contracts.
7. Expose conservative effective capabilities and remote runtime availability independently of
   Gateway readiness.
8. Freeze OpenAPI and SSE/history schemas, examples, and contract tests; review outstanding release
   gates before the owner migrates the repository and starts the frontend rewrite.

## Frontend Readiness Gate

The backend is ready for frontend implementation when controlled tests demonstrate:

1. Creating two sessions, switching and loading their runtime-owned histories, and continuing the
   selected session without copying or resending its transcript as simulated continuity.
2. Reopening persisted bindings after a Mabrid restart while keeping remote conversations distinct
   from new MCP transport sessions.
3. Correct behavior for missing remote sessions, changed bindings, unavailable runtimes,
   unsupported content, and a second Run while the Target is busy.
4. Timely assistant, tool, and widget presentation, including widget failure and a provider pause.
5. Defined terminal, cancellation, disconnection, and unsupported-action behavior without false
   claims of remote stopping or replay.
6. Public schemas and capability states that the frontend can consume without provider wire types
   or internal protocol routing identifiers.

OCI/static frontend delivery and real MCP transport integration remain release gates; this
readiness milestone does not mark them complete. Tauri, SDK replacement, additional runtime
implementations, and broader post-v0.1 ideas are discussed after this milestone rather than added
to its implementation sequence.

## Implementation Status

As of 2026-10-08, this decision is **Partial**: source verification, typed session/history and
control ports, public schema drafts, native session use cases, SQLite bindings, and controlled
integration tests exist. They do not advertise native session support in a deployment or mark
the frontend readiness gate complete.

The selected native interface and its evidence are recorded in the
[Host session contract baseline](../host-session-contract.md). Hermes session resources and
session chat streaming are selected with run status/stop controls; detached Runs and Responses
submission are not required by this selection.

| Batch | State | Evidence or remaining boundary |
| --- | --- | --- |
| 1. Decision and ADR reconciliation | Completed | Accepted ownership, v0.1 scope, and historical amendment notices |
| 2. Native interface and typed contract baseline | Completed | Pinned Hermes source evidence, application ports, session/history and HTTP schema drafts, controlled wire fixture tests |
| 3. Durable bindings and native integration | Completed | Native Hermes adapter, SQLite migration/repository, create/reopen/history/continuation, effective-reference CAS, durable unsettled Runs, bounded stop/status settlement, and controlled restart tests |
| 4. Capability assembly and observer policy | Pending | Typed assembly, ordering, failure isolation, and settlement tests |
| 5. Tool activity and timely presentation | Pending | Activity delivery without assistant deltas and early-close behavior |
| 6. First-party HTTP | Pending | Actual session routes, composed SSE, admission/errors, cancellation, and disconnect semantics |
| 7. Capabilities and remote availability | Pending | Effective support and availability separate from Gateway readiness |
| 8. Contract freeze | Pending | Final schemas/examples, complete readiness checks, and owner-led migration handoff |

The existing text Run, Hermes/OpenAI streaming, Gateway attribution, fresh resources, and widget
composition remain ADR 0015 prerequisites. Native behavior is implemented behind application
ports but is not yet selected by server bootstrap; the first-party Host router is not registered.
The assembly batch must restore durable unresolved Target ownership before either native or
compatibility ingress can invoke that Target, and compose Gateway settlement with native Run
lifecycle. No frontend files were inspected or changed. OCI and live MCP transport gates remain
separate release work.
