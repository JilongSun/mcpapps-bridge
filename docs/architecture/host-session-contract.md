# Host Session Contract Baseline

- Decision: [ADR 0016](decisions/0016-session-oriented-host-and-frontend-contract-readiness.md)
- Reviewed: 2026-10-08
- State: Source-verified integration selection and executable schema drafts; not a frozen HTTP API.

## Evidence and Integration Selection

Hermes evidence was read from a clean local source checkout at
`6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d`. The relevant upstream surfaces are
[the API server](https://github.com/NousResearch/hermes-agent/blob/6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d/gateway/platforms/api_server.py)
and [its session tests](https://github.com/NousResearch/hermes-agent/blob/6ce7ab8bfb3fce3ba116f52a11a438d6c7e4c03d/tests/gateway/test_session_api.py).
This is evidence about that source revision, not a claim that the owner's deployed runtime is
running it. No live agent or live runtime was invoked during this contract batch.

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
reverse-proxy prefix. Concrete native URL configuration belongs to the implementation batch.

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
its Agent Session UUID stable. The next implementation must distinguish a verified same-runtime
continuation from a changed deployment binding and update references with an expected-reference
check rather than silently replacing a conversation or binding it to another runtime.

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
  completion. Confirmed cancellation is not advertised before that policy is implemented.
- Status records are process-local and expire. A missing status or unreachable runtime after
  disconnection means unknown execution state, not safe permission for another attributed Run.

The next batch must validate these behaviors with paused/failed/closed stream fixtures. It must
not reuse the current text adapter's unconditional generator-finalization release as proof of
remote session execution settlement.

## Typed Boundaries and Public Drafts

The [Agent Host session contracts](../../backend/packages/application/src/mabrid/application/agent_host/contracts/session.py)
define durable bindings separately from native references, presentation history, new input,
remote execution handles, stop receipts, and observed execution states. Session records contain
no transcript. [Application ports](../../backend/packages/application/src/mabrid/application/agent_host/application/ports.py)
separate persistence, native session catalog, history, execution, and optional Run control without
changing the existing text `AgentRuntime` port.

[Hermes wire documents](../../backend/packages/application/src/mabrid/application/agent_host/integrations/hermes/session_documents.py)
are isolated inside the integration. Their forward-compatible extra fields are not public Host
fields. [Host HTTP schema drafts](../../backend/apps/server/src/mabrid/server/api/host_contracts.py)
reject unrecognized request fields and expose session metadata and binding availability without
remote session/run IDs or Gateway routing keys.

The planned paths in ADR 0016 remain unchanged. These models establish the session/history portion
of that contract; they do not register routes or finish the live tool/widget SSE family. Binding
availability is separate from persisted identity, and a stored handle does not imply a reachable
remote conversation. The final router batch must establish HTTP status mappings, admission before
SSE headers, stream errors, and cancellation transport using the verified application behavior.

## Controlled Validation and Remaining Work

The existing Agent Host tests now validate session/history separation, input-only continuation,
bounded pagination, explicit unsupported content, tool-call presentation, and nonterminal stop
receipts. Existing Hermes tests include a controlled HTTP wire fixture for native resource shapes,
named SSE events, missing sessions, and stop/status responses. Server tests validate public schema
round trips and rejection of private identifiers and transcript input.

Those tests validate contract drafts and controlled wire documents. They do not run Hermes, create
real remote conversations, test a production native adapter, or prove durable restart continuity.
The following remain implementation gates:

- SQLite bindings and lifecycle-safe create/reopen/history/continuation use cases.
- A native adapter with history normalization, SSE parsing, failure and stop reconciliation, and
  effective-session-reference handling.
- Timely Gateway tool/widget presentation and the first-party HTTP routes.
- Conservative capabilities and remote runtime availability.
- Final OpenAPI/SSE schema freeze and ADR 0016's complete frontend readiness gate.
