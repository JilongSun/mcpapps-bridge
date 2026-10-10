# Frontend Readiness and Migration Handoff

- Reviewed: 2026-10-10
- Authority: [ADR 0016](decisions/0016-session-oriented-host-and-frontend-contract-readiness.md)
- Result: The first-party frontend contract and route-partition milestone is complete.
- Boundary: Backend frontend readiness is established; v0.1 release readiness is not.

## Frozen Contract

The reviewed v0.1 baseline consists of:

- [The machine-readable contract](../contracts/v0.1/frontend-contract.json): first-party OpenAPI,
  standalone Host SSE JSON Schema, safe Host error codes/messages/statuses, and stream semantics.
- [Validated examples](../contracts/v0.1/examples.json): requests, local recovery metadata, native
  history, every SSE payload, alternate terminals, control receipts, capabilities, and safe errors.
- [The Host session contract](host-session-contract.md): ownership, runtime evidence, lifecycle,
  pagination, privacy, capability semantics, and reconnect limitations.

The snapshot is generated from the existing routers and public models, without opening a database,
entering the application lifespan, contacting a runtime, or invoking tools. It is not a second DTO
implementation. Contract tests compare it to the current models and production app across deployment
selections, check local schema references, validate exact example JSON, and exercise mature SSE
encoding/decoding. An intentional API change requires review of models, behavior, examples, and the
snapshot together; silently regenerating a failing snapshot is not contract review.

From the repository root, verify the snapshot with:

```sh
uv run --directory backend --all-packages python -m mabrid.server.api.frontend_contract ../docs/contracts/v0.1/frontend-contract.json --check
uv run --directory backend --all-packages pytest apps/server/tests/test_frontend_contract.py -q
```

For an approved contract change, run the same export command without `--check`, inspect the diff,
and rerun tests. The output path is relative to `backend/` because `uv --directory backend` changes
the command's working directory. The exporter and test paths contain no machine-specific root and
can be used after the repository is renamed or moved. The snapshot's `openapi` member is the OpenAPI
document; `host_sse` is the schema for each SSE data envelope. It does not define a stable Python or
JavaScript SDK, an OpenAI wire replacement, or an MCP transport schema.

## Route Partitions

| Surface | Namespace and boundary |
| --- | --- |
| Agent workspace | `/api/v1/host`: local Sessions, runtime-owned history, new-input SSE, cancel/reconcile; safe JSON errors before admission |
| Product capability status | `/api/v1/capabilities`: local/deployment/remote/effective facts, not Run admission or a remote execution health test |
| Gateway topology and inspection | `/api/v1/gateway`: read-only status/topology and Gateway Session pages/snapshots/events; RFC 9457 errors |
| Target assignment | `/api/v1/agent-host/target`: read-only configured Target and endpoint assignment; not per-Run provider selection |
| Compatibility | `/v1/models`, `/v1/chat/completions`: standard OpenAI shapes, no private tool/widget envelopes or simulated native continuity |
| MCP | `/mcp/{endpoint_slug}` and its legacy SSE transport: protocol-owned Gateway ingress, independent of Agent Session history |
| Local status | `/health`, `/ready`: local process/persistence/publication status; remote Host outages do not make Gateway unready |

Gateway Session IDs and Agent Session IDs are different identities. Gateway event pagination is not
Host SSE replay. Diagnostic inspection remains intentionally separate from model-visible MCP
descriptions and public Host presentation. Management errors use `application/problem+json`; Host
errors use `application/json`; successful Host Run delivery uses `text/event-stream`.

## Readiness Evidence

All six ADR 0016 frontend prerequisites are satisfied by controlled tests:

| Prerequisite | Executable evidence |
| --- | --- |
| Two distinct conversations, switching, native history, and new-input-only continuation | [Native Session tests](../../backend/apps/server/tests/test_native_sessions.py): `test_first_party_http_stream_admits_before_headers_and_continues_selected_history` and `test_native_sessions_switch_reopen_and_continue_without_local_transcript` |
| Stable bindings and unresolved ownership across restart | Native Session tests: `test_unresolved_native_execution_blocks_restart_until_remote_terminal` and `test_native_binding_and_unsettled_ownership_survive_database_reopen`; [bootstrap tests](../../backend/apps/server/tests/test_bootstrap.py) cover restoration before compatibility ingress |
| Missing remote Session, changed binding, outage, unsupported history, and busy Target | Native Session error/lifecycle tests; [integration tests](../../backend/packages/application/tests/test_hermes_chat_completions_adapter.py); production capability deployment matrix |
| Timely tools/widgets while the provider is paused, including visible results after widget failure | `test_first_party_composed_http_delivers_tools_and_widget_failure_while_native_pauses`; [composed transport tests](../../backend/apps/server/tests/test_transport_contract.py) exercise real MCP requests with controlled upstreams |
| Distinct admission, failure, cancellation, disconnect, and unsupported/replay behavior | Session-bound cancel ordering and ASGI lifecycle tests; no lease release without verified remote/local settlement |
| Public schema and capability contracts without provider handles or internal Host routing fields | [Contract freeze tests](../../backend/apps/server/tests/test_frontend_contract.py), [OpenAI isolation tests](../../backend/apps/server/tests/test_openai_api.py), and production schema equality checks |

The completion baseline passes 284 backend tests, Pyright with zero errors, Ruff, formatting, and
schema drift checks. These tests use controlled runtime/upstream fixtures and actual application,
HTTP/SSE, MCP, and SQLite code paths. They do not certify an externally deployed Hermes revision,
exercise live model credentials, or prove release-image operation. No frontend implementation was
read, modified, or validated during this milestone.

## Migration and Review

The next work can proceed in this order:

1. Manually commit the completed contract batch and retain that commit as the review baseline.
2. Perform the owner-controlled repository/directory/remote migration, preserving Git history and
   the existing `mabrid` code identity. Do not combine it with a second namespace rewrite or runtime
   behavior changes. Local configuration, secrets, SQLite state, interpreter paths, and editor
   settings need deliberate handling; do not publish them or reset persisted bindings/leases merely
   to make a renamed checkout start.
3. Review the code in the migrated repository before the frontend rewrite. Compare against the
   baseline and rerun contract drift, architecture, type, lint, and backend tests in the new location.
   Review findings and required fixes should remain separate from mechanical migration changes.
4. Discuss expansion points as explicit follow-up decisions, not unfinished work hidden inside this
   completed milestone. SDK replacement, Tauri packaging, further runtime integrations, remote
   conversation import, and Host follow-up actions do not automatically enter v0.1 scope.
5. Start the frontend rewrite as a separate, explicitly requested task against the frozen contract.
   Product design and implementation can now focus on Sessions/history, live Run presentation,
   widgets/sandboxing, read-only Gateway management, inspection, and connection/capability status.
6. Finish integration and distribution gates before tagging v0.1. Backend corrections discovered
   during review or frontend integration still require their own focused regression checks.

The post-migration review should prioritize dependency direction and public facade boundaries;
Target/session identity and deployment binding; restart recovery and uncertain submission;
cancellation ordering, reader/client cleanup, and durable lease release; protocol/resource fidelity;
Host DTO privacy and safe errors; configuration/secret ownership; and production/image startup.
Existing hardcoded debug workflow parameters are intentional owner tooling, not migration cleanup.

## Remaining Release Gates

The backend's planned v0.1 functional baseline is substantially complete. The product is not yet
a complete v0.1 release. Remaining gates include:

- The first-party frontend and MCP Apps renderer, including sandbox restrictions, initialization,
  data exchange, unavailable historical widgets, and explicit unsupported Host actions.
- Actual deployment integration against the selected runtime and MCP servers/transports, including
  externally verified support, advertised endpoint URLs, continuation, stop/disconnect settlement,
  fresh resources, and rendered widgets. Controlled protocol tests are necessary but not sufficient.
- OCI build/distribution, same-origin static frontend serving, and clean-database migration,
  configuration, shutdown, liveness/readiness, and startup validation inside the release image.
- Post-migration code review, integration regressions, and the final release checklist under the
  accepted v0.1 scope. A public release README is written only when the project is complete.

There is no need to reopen completed backend architecture batches merely because release work
remains. There is also no permission to label live integration or distribution complete based on
the contract freeze. Frontend work and release completion are separate, bounded next stages.