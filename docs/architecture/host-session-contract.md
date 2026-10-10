# Host Session Contract Baseline

- Decision: [ADR 0016](decisions/0016-session-oriented-host-and-frontend-contract-readiness.md)
- Reviewed: 2026-10-10
- State: Native use cases, persistence, production HTTP/SSE, safe public DTOs, cancellation/disconnection behavior, and conservative capabilities implemented with controlled tests; final schema freeze remains pending.

## Evidence and Integration Selection

Hermes evidence was read from a clean local source checkout at
`6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d`. The relevant upstream surfaces are
[the API server](https://github.com/NousResearch/hermes-agent/blob/6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d/gateway/platforms/api_server.py)
and [its session tests](https://github.com/NousResearch/hermes-agent/blob/6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d/tests/gateway/test_session_api.py).
This is evidence about that source revision, not a claim that the owner's deployed runtime is
running it. No live agent or live runtime was invoked during these backend batches.

The selected first-party behavior uses native Hermes session resources and session chat streaming:

| Behavior | Hermes interface | Verified implementation anchor |
| --- | --- | --- |
| Create | `POST /api/sessions` | `_handle_create_session` |
| Reopen | `GET /api/sessions/{id}` | `_handle_get_session` |
| History | `GET /api/sessions/{id}/messages` | `_handle_session_messages` |
| New streamed turn | `POST /api/sessions/{id}/chat/stream` | `_handle_session_chat_stream` |
| Execution status | `GET /v1/runs/{id}` | `_handle_get_run`, `_set_run_status` |
| Request stop | `POST /v1/runs/{id}/stop` | `_handle_stop_run` |

This does not select `POST /v1/runs`, detached event subscriptions, Responses, or session headers
as the first-party execution interface. Existing Chat Completions remains a separate compatibility
slice. Native resource paths must resolve against the configured runtime API root; the legacy
OpenAI `/v1` base URL must not accidentally produce `/v1/api/sessions` or discard a deployment's
reverse-proxy prefix. Native URL configuration is explicit and separate from the compatibility URL.

## Runtime-Owned History

Creation returns HTTP 201 with `object: "hermes.session"` and a nested `session` containing its
opaque `id`. Get returns the same document family. Missing remote sessions return HTTP 404 with
`error.code: "session_not_found"`; an unavailable session database returns HTTP 503. Neither is an
empty-history success or permission to create a replacement conversation.

History returns `object: "list"`, `session_id`, `data`, and `pagination` containing `limit`,
`offset`, `order`, and `returned`. There is no history `has_more` or total-count field. Hermes
defaults differ depending on whether `limit` was supplied: the Mabrid integration must therefore
always send all three explicit pagination parameters.

The draft Mabrid history query defaults to `limit=100`, `offset=0`, `order="latest"`, with limits
between 1 and 500. A page retains chronological message order; selecting the latest window does
not reverse the transcript. The public `has_more` may be unknown and must not be invented from a
full page alone. The frontend may request another bounded window to determine whether more exists.

History includes assistant tool calls and tool results, not just text. Function arguments are JSON
strings on the Hermes wire and structured JSON values in the presentation contract. Unsupported
roles and non-text content have explicit unsupported representations, not fabricated assistant
text. Message identifiers are opaque strings in the public presentation contract.

Hermes resolves resume/compaction lineage when reading history; its returned effective session ID
may differ from the requested ID. Completion may also report an effective session ID. Mabrid keeps
its Agent Session UUID stable. The implementation distinguishes verified same-runtime continuation
from changed deployment bindings and updates references with an expected-reference check rather
than silently replacing a conversation or binding it to another runtime.

## Execution and Stop Semantics

Native chat accepts a new `message` or `input`; Mabrid chooses the `message` field. The selected
request contains only new text, not a transcript, model override, or reconstructed tool messages.
Hermes loads its own stored conversation in `_conversation_history_for_session` before execution.

The SSE stream emits named events, including `run.started`, `message.started`, `assistant.delta`,
tool activity, `assistant.completed`, `run.completed`, `error`, and `done`. Payloads carry remote
session/run IDs, sequence, and timestamp. The integration translates those events; it does not
forward them as the first-party public stream. Gateway observations remain authoritative for
Mabrid MCP tool causation and widgets, even when Hermes also emits tool progress.

Important boundaries:

- `run.started` provides a remote Run handle for status and stop operations.
- `assistant.completed` carries final text, while `run.completed` carries usage and the effective
  session ID. Its turn transcript can contain intermediate assistant text and tool calls that a
  text-only stream cannot fully reconstruct.
- `done` is a transport sentinel emitted in `finally`, including after an error. It is not a
  successful completion event. Unexpected EOF without a verified terminal event needs explicit
  failure/reconciliation behavior.
- Stop returns `status: "stopping"`. That acknowledges a request; it does not prove execution has
  exited or justify releasing active Target ownership.
- Session-stream disconnection requests interrupt and retains execution control references until
  the executor-backed turn returns. Closing the client stream alone does not acknowledge that
  cleanup has completed.
- The session stream's completion path can still emit `run.completed` after an interrupt. The
  adapter cannot infer cancellation merely from a stop receipt or an event name. A Mabrid
  user-cancelled terminal state requires verified remote exit and a defined ordering against normal
  completion. The first-party acknowledgement-ordering policy is defined below; a stop receipt
  alone never produces a cancelled terminal event.
- Status records are process-local and expire. A missing status or unreachable runtime after
  disconnection means unknown execution state, not safe permission for another attributed Run.

The native adapter validates these behaviors with controlled complete, paused, failed, closed,
and uncertain-submission fixtures. It does not reuse the text adapter's generator-finalization
release as proof of remote settlement.

## Implemented Native Use Cases

[Agent Session use cases](../../backend/packages/application/src/mabrid/application/agent_host/application/sessions.py)
own create, local listing, remote reopening, runtime-owned history presentation, and new-input
execution. [The Hermes adapter](../../backend/packages/application/src/mabrid/application/agent_host/integrations/hermes/sessions.py)
uses explicit native API-root configuration, preserving reverse-proxy prefixes, and a standard
`httpx-sse` decoder rather than an OpenAI wire stream or custom SSE parser.

[The SQLite repository](../../backend/apps/server/src/mabrid/server/persistence/agent_host.py)
persists only Agent Session bindings and unresolved Run ownership. The additive
[migration](../../backend/apps/server/migrations/versions/0002_agent_sessions.py)
does not reset existing topology or copy remote transcripts. Effective remote references are
verified through the catalog and updated by compare-and-set within the same deployment binding.

Every native Run claims the shared Target coordinator and a durable unresolved record before
submission. Its remote handle is recorded on `run.started`. Normal completion or confirmed
early-close settlement releases ownership only after the consumer finishes the Run generator.
Failure to observe remote exit retains both unresolved durable state and process ownership.
Submission timeout/cancellation without a recoverable handle also remains unresolved rather than
creating a new conversation or assuming no execution occurred.

Stop/status cleanup has a bounded settlement timeout. Explicit reconciliation can release an
unresolved record only after observing remote terminal state and settling local Host operations;
missing status remains unknown.
Reconciliation cannot release a locally open Run stream. Unknown execution persists across a
Mabrid restart and blocks new native execution until verified reconciliation succeeds.

## Deployment Assembly and Observer Policy

[Application capability assembly](../../backend/packages/application/src/mabrid/application/host/composition.py)
connects one Target coordinator, attribution registry, optional MCP Apps, Run settlement, and
per-Run presentation through typed ports. Both native and compatibility services share the same
coordinator. Server composition retains configuration, secrets, concrete adapters, repository
construction, migrations, and cleanup; there is no dynamic registry or generic event bus.

Native ports are selected by an optional `agentHost.runtime.sessions` mapping:

```yaml
agentHost:
  enabled: true
  targetId: hermes
  endpointSlug: tools
  runtime:
    baseUrl: http://127.0.0.1:8642/v1
    sessions:
      apiRoot: http://127.0.0.1:8642
      bindingId: local-hermes
```

This fragment assumes the deployment already declares `bridge.advertisedBaseUrl`, the `tools`
endpoint, and the API key environment variable. `apiRoot` is not inferred from `baseUrl`.
`bindingId` identifies the external runtime deployment, not the Mabrid process or a conversation;
keep it stable across Mabrid restarts and change it when replacing the runtime deployment. Do not
reuse a binding to silently migrate conversations to a different runtime. Omitting `sessions`
keeps compatibility-only behavior; it does not erase existing durable unresolved ownership.

Bootstrap restores unresolved Target ownership before either ingress can invoke the runtime,
without a remote probe and even if native configuration is absent or changed. Normal shutdown and
startup rollback close the native client, compatibility client, and database in ownership order,
including when client cleanup fails.

[Host observation and settlement](../../backend/packages/application/src/mabrid/application/host/settlement.py)
keep attribution before tool activity and optional widget projection, separately track actual Gateway tool completion, and
bound observer and Run-settlement waits to five seconds by default. A Host observer exception or
timeout does not replace an MCP tool result. It records an attributable workflow failure and
aborts widget pending state, but actual tools still have to finish. Late widget events for an
aborted Run are not published. External cancellation records failure and propagates unchanged.
The Gateway inspection observer remains outside this Host-specific policy.

Both Run services wait for tools and optional widgets before successful terminal events, and also
settle on early consumer closure. A known workflow failure terminates the Host Run without an
infinite wait. Unknown tool/widget settlement retains Target ownership; native Runs also retain
the durable lease until remote and local settlement permit reconciliation. The compatibility
adapter's client closure still does not prove remote cancellation. Presentation remains per-Run
and does not own runtime conversation history.

## Timely Run Presentation

[Tool activity contracts](../../backend/packages/application/src/mabrid/application/agent_host/contracts/activity.py)
represent invocation start, successful completion, and failure. The
[attributed activity projector](../../backend/packages/application/src/mabrid/application/agent_host/application/activity.py)
assigns an opaque invocation UUID to each Gateway operation and preserves arguments, content,
structured results, error status, and metadata. Its routing-key mapping is internal; activity
models do not serialize Gateway session/operation keys or failure binding details. Tool activity
is enabled independently of MCP Apps. A tool error result and a transport failure are distinct;
widget loading failure does not replace or suppress a successful tool result.

[Host presentation](../../backend/packages/application/src/mabrid/application/host/service.py)
waits on the Agent source, tool activity notifications, and optional widget notifications, without
polling or waiting for another assistant delta. At most one read task per source is retained by
the generator. Normal completion, early closure, consumer cancellation, and reader failure cancel
and join remaining reads before closing the domain source. No reader tasks are detached, and no
task-group cancellation scope spans generator yields across consumer tasks.

The stream emits Run start first, uses contiguous per-Run delivery sequence numbers, presents
recorded tool activity before associated widgets, and drains settled widget events before the
terminal event. This is delivery order, not global wall-clock sorting or durable replay.
`HostToolEvent` carries invocation activity; `HostWidgetEvent.tool_invocation_id` links a widget
to its invocation when the activity source is composed. Resource contents, MIME types, and widget
metadata remain the owned MCP Apps payload rather than fabricated assistant output.

`HostSessionEventStream` uses the same merger for native execution. It retains the stable local
Agent Session UUID and Run UUID in every envelope, translates native callbacks into local Agent
events, and does not forward remote session/run handles. The native command still contains only
new input. Compatibility OpenAI streaming filters all non-Agent envelopes and retains standard
Chat Completion chunks and `[DONE]`.

Closing presentation triggers source cleanup; it does not prove remote stopping. Native unknown
execution retains durable ownership until verified reconciliation, including after tool/widget
events have already been delivered. Runtime errors cross the native source as typed application
errors that the HTTP adapter maps to safe public failures. Run-local stores do not reconstruct old
widgets, expose a resume cursor, or promise reconnection replay.

## Typed Boundaries and Public Drafts

The [Agent Host session contracts](../../backend/packages/application/src/mabrid/application/agent_host/contracts/session.py)
define durable bindings separately from native references, presentation history, new input,
remote execution handles, stop receipts, and observed execution states. Session records contain
no transcript. [Application ports](../../backend/packages/application/src/mabrid/application/agent_host/application/ports.py)
separate persistence, native session catalog, history, execution, and optional Run control without
changing the existing text `AgentRuntime` port.

[Hermes wire documents](../../backend/packages/application/src/mabrid/application/agent_host/integrations/hermes/session_documents.py)
are isolated inside the integration. Their forward-compatible extra fields are not public Host
fields. [Host HTTP contracts](../../backend/apps/server/src/mabrid/server/api/host_contracts.py)
reject unrecognized request fields and expose session metadata and binding availability without
remote session/run IDs or Gateway routing keys.

Binding availability is separate from persisted identity. Local listing reports `unknown`, or
`runtime_changed` for a different deployment binding, without a remote probe. Successful create
and reopen report `available` for that operation; they do not certify future runtime availability.
Missing or unavailable remote operations return typed errors rather than substitute sessions or
empty history. Effective capabilities and availability are reported separately as described below.

## First-Party HTTP and SSE

[The Host router](../../backend/apps/server/src/mabrid/server/api/host.py) is registered in the
production server independently of OpenAI, MCP, and management routes. It remains registered when
native sessions are disabled and returns `unsupported_operation` rather than disappearing.

| Method and path | Successful response |
| --- | --- |
| `POST /api/v1/host/sessions` | 201 session metadata; optional `title` only |
| `GET /api/v1/host/sessions` | 200 local page; `limit=20` (1..200), `offset=0`, boolean `has_more` |
| `GET /api/v1/host/sessions/{session_id}` | 200 remotely verified session metadata |
| `GET /api/v1/host/sessions/{session_id}/history` | 200 runtime-owned normalized history with explicit pagination |
| `POST /api/v1/host/sessions/{session_id}/runs` | 200 POST-based SSE; nonblank `input_text` only |
| `POST /api/v1/host/sessions/{session_id}/runs/{run_id}/cancel` | 202 stop receipt with `accepted` and `settlement: "unconfirmed"` |
| `POST /api/v1/host/sessions/{session_id}/runs/{run_id}/reconcile` | 200 local identifiers and `settled` boolean |

Session metadata includes `target_run`, either null or local Session/Run UUIDs and an `active` or
`unsettled` state for the Target's durable native Session Run, even when another Session is selected. This lets
a reconnecting client discover unresolved ownership without private remote handles. It is a
current snapshot, not a durable Run-result or transcript store. Null means no native lease was
found, not proof that compatibility ingress has no active Run; admission always checks the shared
coordinator. Session switching and history
loading do not stop a Run; starting a second Run is rejected across all Sessions and compatibility
ingress while the shared Target remains owned.

The Run route reads and validates the native start before sending successful SSE headers. Local
and remote Session checks, deployment-binding checks, shared coordination, durable claiming, and
remote handle recording therefore happen before `run.started` is presented. Admission monitors
client disconnection and closes the source. Uncertain accepted submission without a recoverable
remote handle preserves a durable unresolved Run and cannot safely be retried.

[Public SSE projection](../../backend/apps/server/src/mabrid/server/api/host_stream.py) explicitly
selects public fields rather than serializing internal Host envelopes. Every data frame has local
`event_id`, `session_id`, `run_id`, contiguous positive `sequence`, aware `created_at`, and a
discriminated `event` payload. The SSE `event` matches payload `kind`; SSE `id` is the event UUID.
The payload family is:

- `run.started`, `assistant.text.delta`, and `assistant.text.completed`;
- `tool.started`, `tool.completed`, and `tool.failed` with invocation identity and results;
- `widget.created` and `widget.failed` linked to their tool invocation; and
- one terminal `run.completed`, `run.cancelled`, or `run.failed` for a connected consumer.

Tool results and arguments, widget resource contents, MIME types, structured content, and renderer
metadata remain visible. Widget failure retains the tool result. Projection omits remote control
handles, deployment bindings, and Gateway routing keys, and replaces internal diagnostic exception
messages with safe fixed messages. Runtime/tool/resource-owned content remains content, not a
promise that arbitrary upstream payloads have been scrubbed of sensitive text.

The mature `sse-starlette` response owns source cleanup even if sending headers fails before its
body generator begins. It uses `Cache-Control: no-store`, disables proxy buffering, and bounds
individual sends to five seconds. Before emitting a successful terminal frame it closes and
settles the source; unknown cleanup becomes `run.failed`, not false success. Headers cannot change
after admission: typed source failures become safe `run.failed` data frames. A disconnected client
cannot be promised a final frame. Cleanup cancels and joins presentation readers and retains unknown
durable ownership when remote or local exit cannot be verified.

SSE IDs are not replay cursors. `Last-Event-ID` on Run submission is rejected as unsupported.
There is no detached Run subscription, automatic resubmission, or durable event replay. Reopen
metadata and runtime history after reconnecting; discover unresolved local ownership through
`target_run` and reconcile it before new execution. History loading does not regenerate widgets.

## Cancellation and Reconciliation

Both control routes validate the supplied local Session and Run against the current durable lease
and deployment binding. A different Session cannot control that Run. No remote handles enter the
request or response. Stop acceptance does not release ownership or produce terminal cancellation.

For a locally open stream, an accepted stop receipt observed **before** native completion marks
user cancellation. After native completion and local tool/widget settlement, presentation emits
`run.cancelled` rather than `run.completed`. If completion was observed first, a later stop returns
`accepted: false` and does not replace completion. A receipt that returns only after completion was
observed also cannot change that outcome. This is Mabrid's acknowledgement-ordering policy, not a
claim that Hermes emitted a distinct native cancelled event or discarded its transcript.

Disconnect and send failure are cleanup paths, not explicit user-cancel acknowledgements. They
may request remote stop, but never fabricate `run.cancelled`. Unconfirmed cleanup retains a lease
and blocks overlap. Reconciliation returns false while a local stream is open, no remote handle
is known, or remote status is nonterminal/unknown. It releases ownership only after verified remote
terminal status and local settlement. `settled: true` means overlap is safe, not that the original
Run succeeded or that its terminal event can be replayed. There is no public force-unlock route
when submission or status remains unknown. Control of an already released or mismatched local Run
returns `run_not_found`.

## Safe Error Contract

Host validation and failures use `HostErrorResponse`: an allowlisted code, fixed safe message, and
optional local Session/Run UUIDs. Validation does not echo rejected input or Pydantic diagnostics.
Unexpected infrastructure failures are `internal_error`; raw provider bodies and exception strings
are not returned. Existing management and OpenAI error contracts are unchanged.

| HTTP status before SSE admission | Host codes |
| --- | --- |
| 404 | `session_not_found`, `remote_session_not_found`, `run_not_found` |
| 409 | `runtime_binding_changed`, `target_busy`, `run_state_unknown` |
| 422 | `invalid_request` |
| 500 | `internal_error` |
| 502 | `runtime_contract_error` |
| 503 | `runtime_unavailable`, `unsupported_operation` |

OpenAPI describes successful Run delivery as `text/event-stream` and admission errors as
`application/json`. This implemented contract is not the batch-8 schema freeze.

## Effective Capabilities and Remote Availability

`GET /api/v1/capabilities` is a registered, read-only product endpoint with HTTP 200 and
`Cache-Control: no-store`, including when Agent Host is disabled or its runtime is unavailable.
[The HTTP adapter](../../backend/apps/server/src/mabrid/server/api/capabilities.py) separates local
Gateway capabilities from the [Agent Host capability use case](../../backend/packages/application/src/mabrid/application/agent_host/application/capabilities.py).
The response contains `gateway` and `agent_host`; it is not a replacement for `/health`, `/ready`,
Session binding metadata, or Run admission.

Gateway fields report local implementation and deployment composition: protocol passthrough is
implemented, topology/session inspection is exposed when management is composed, and topology
mutation is not exposed in v0.1. These are not claims that any upstream is connected or that a
particular widget is renderable. Agent Host reports its enabled state, optional local Target ID,
independent native/compatibility runtime observations, and `max_concurrent_runs: 1`.

Each effective Host feature has four distinct facts:

| Field | Meaning |
| --- | --- |
| `implemented` | The local backend implements the behavior |
| `enabled` | This deployment selects the behavior; no remote support claim |
| `remote_support` | Explicit supported/unsupported evidence, or null for unknown/not applicable |
| `availability` and `reason` | Effective current classification and safe explanation code |

Effective availability is `disabled` for unselected behavior, `unsupported` for unimplemented or
explicitly remote-unsupported behavior, `unavailable` for a failed current runtime probe,
`unknown` for missing evidence, and `available` for selected local behavior or verified matching
remote declarations. Unknown support never becomes true from a local runtime profile or enabled
configuration. An enabled interface without a probe remains unknown, not disabled.

The feature set covers local Session listing, native create/reopen/history/streaming, Run cancel
and reconciliation, tool activity, widget presentation, and compatibility streaming. Native history
requires reopen/history support; native streaming requires reopen/streaming support. Cancel requires
stop and status support, while reconciliation uses status support. Streaming alone does not imply
remote stop. Tool/widget presentation depends on selected native streaming, and widgets additionally
require the deployment's MCP Apps composition. Widget presentation means live backend payloads,
not a finished renderer, historical widget reconstruction, or support for Host follow-up actions.
`host_actions`, `event_replay`, and `remote_session_import` remain explicitly unimplemented,
disabled, and unsupported even if Hermes advertises related behavior.

The pinned Hermes source advertises `GET /v1/capabilities`, with named feature booleans and endpoint
method/path descriptors. Native discovery resolves `v1/capabilities` against the explicit native
`apiRoot`; compatibility discovery resolves `capabilities` against its own configured OpenAI base
URL. Reverse-proxy prefixes are preserved. The two addresses are probed independently: compatibility
success cannot prove native availability, and native failure does not make compatibility unavailable.
Native declarations from an unselected interface cannot silently enable that interface.

The adapters strictly validate the raw capability document and normalize only relevant support
facts. An explicitly false feature is unsupported. Missing feature flags or missing/mismatched
endpoint descriptors are unknown, not fabricated support or a fallback interface selection.
Raw model identifiers, provider descriptions, URLs, deployment bindings, secrets, and response
bodies are not public capability fields. Runtime observations include an aware `checked_at`,
`availability`, safe `reason`, and normalized `support`.

| Runtime observation | Classification |
| --- | --- |
| Valid capability document | Available discovery endpoint; declared support assessed separately |
| 404, 405, or 501 discovery response | Unknown; `discovery_unsupported` |
| Invalid document or feature types | Unknown; `invalid_response` |
| 401 or 403 | Unavailable; `authentication_failed` |
| Other unsuccessful HTTP response or transport failure | Unavailable; `runtime_unavailable` |
| Bounded probe timeout | Unavailable; `probe_timeout` |
| Unexpected probe exception | Unknown; `probe_failed` |

Both probes run in a request-scoped task group, each bounded to three seconds by default. They are
cancelled and joined on request cancellation, with no background watcher or detached subscription.
Every capability request obtains fresh observations; no previous successful support is cached or
reused after a failed probe. Adapter clients remain owned by server composition and use the existing
shutdown order. No dependency, migration, configuration setting, or new client lifecycle is needed.

`remote_verified` means current validated runtime declarations, not a synthetic Run, an LLM health
test, a particular remote Session's existence, or a guarantee that the next operation succeeds.
No discovery request creates a Session, reads its transcript, starts a Run, requests stop, executes
a tool, or loads a widget resource. Runtime operation errors remain authoritative at use time.
Busy and durable unknown-Run state are separate admission/settlement constraints; an available
capability is never permission to bypass shared Target ownership or force-release its lease.

Startup, `/health`, and `/ready` never invoke these probes. Remote Host outages do not change local
Gateway readiness or MCP Apps passthrough. A disabled Host does not erase the capability route or
perform remote requests. This is the implemented batch-7 contract, not the batch-8 schema freeze.

## Controlled Validation and Remaining Work

The existing Agent Host tests now validate session/history separation, input-only continuation,
bounded pagination, explicit unsupported content, tool-call presentation, and nonterminal stop
receipts. Existing Hermes tests include a controlled HTTP wire fixture for native resource shapes,
named SSE events, missing sessions, and stop/status responses. Server tests validate public schema
round trips and rejection of private identifiers and transcript input.

Controlled tests now also compose the actual native adapter, application use cases, Alembic, and
SQLite. They verify two distinct conversations, switching and input-only continuation, effective
reference updates, database reopen, missing conversations, changed bindings, and unresolved Run
ownership/reconciliation across restart. They do not run live Hermes or prove a deployed runtime
version supports the selected contract. Production bootstrap tests verify native selection,
shared coordination, restoration before compatibility invocation with absent or changed native
configuration, and reverse-order cleanup including cleanup failure. Focused Host tests verify
observer order, failure and timeout isolation, cancellation propagation, and bounded presentation;
native tests verify completion and early-close leases against local Host settlement. Paused
provider tests deliver tool start/result and widget success/failure before any assistant delta,
including MCP Apps-disabled deployments. A controlled paused HTTP byte stream verifies the same
behavior through the actual Hermes native adapter and SQLite, then verifies normal completion or
durable unknown-state retention after early closure. Counting-reader fixtures verify cleanup on
normal completion, early close, consumer cancellation, and tool/widget reader exceptions. OpenAI
wire tests verify that tool activity does not leak into standard response chunks.
First-party HTTP tests exercise production wiring, two-Session input-only continuation, shared
admission, safe validation/errors, public payload projection, and tool/widget delivery while the
native provider is paused. Controlled ASGI probes verify cancel acknowledgement ordering,
cross-Session control rejection, disconnection before and after a remote handle, header-send
failure, durable unknown-state retention, recovery metadata, and verified reconciliation. Gateway
health/readiness remains independent of native Host selection.
Capability tests verify strict discovery, explicit false and missing support, endpoint matching,
proxy paths, independent native/compatibility selection, disabled Host/widgets, read-only safe
responses, fresh observations after timeout, and joined cleanup on request cancellation. Production
bootstrap/main tests exercise the actual adapters and HTTP route with controlled remote responses;
startup and readiness produce no remote requests, and native outage leaves Gateway readiness and
independently available compatibility behavior intact. No live runtime was invoked.
The following remain implementation gates:

- Final OpenAPI/SSE schema freeze and ADR 0016's complete frontend readiness gate.
