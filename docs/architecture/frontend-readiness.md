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
2. Perform the owner-controlled remote repository rename and update About and the checkout's
   remote URL, preserving Git history and the existing `mabrid` code identity. The owner explicitly
   retains the local `mcpapps-bridge` root directory for the active editor session; no directory
   move or fresh clone is required. Do not combine hosting migration with another namespace rewrite
   or runtime behavior changes. Preserve local configuration, secrets, SQLite state, interpreter
   paths, and editor settings; do not publish them or reset persisted bindings/leases.
3. Review the code after remote migration before the frontend rewrite. Compare against the
   baseline and rerun contract drift, architecture, type, lint, and backend tests in the retained checkout.
   Review findings and required fixes should remain separate from mechanical migration changes.
4. Discuss expansion points solely to clarify the owner's thinking and fill technical knowledge
   gaps. Even an agreed direction or a known change is not implementation authorization. SDK
   replacement, Tauri packaging, further runtime integrations, remote conversation import, and Host
   follow-up actions do not automatically enter v0.1 scope; implementation needs a separate request.
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

### Remote Migration Checklist

Repository-local Mabrid identity is complete; the hosting step is still the owner's action. The
recommended About text and current product positioning are recorded in
[ADR 0009](decisions/0009-mabrid-product-identity.md). This does not introduce a plugin implementation
or require a README.

1. Review and commit this preparation batch; record the baseline commit and confirm the worktree
   is clean before changing hosting settings. Keep local secrets/configuration and database files
   out of the commit. Do not create a new repository to simulate a rename.
2. Rename the existing GitHub repository to `mabrid` in its settings, retaining the owner and
   repository history. This is not an organization/ownership transfer. Check the target name's
   availability rather than assuming it is available.
3. Update About with the reviewed product description. Do not advertise published SDKs, plugins,
   or a completed frontend. Remote metadata is not changed by the preparation commit.
4. In the existing checkout, update the remote using the new repository URL from GitHub. Preserve
   the current SSH/HTTPS authentication style, then verify with fetch and branch inspection:

   ```sh
   git remote set-url origin <new-repository-url>
   git fetch origin
   git branch -vv
   ```

   Also inspect any explicitly configured push URL and update it when necessary. Do not rely on
   old-name redirects as the permanent remote configuration, force-push, or rewrite history.
5. Check external links, badges, webhooks, CI integrations, and any published site/package/image
   references that actually exist. Standard repository redirects do not cover every product URL
   or integration: GitHub Pages project-site URLs and workflow calls to an Action hosted in a renamed
   repository need explicit attention if present. Do not reuse the old repository name, which would
   invalidate GitHub's redirects. Do not invent distribution changes for unpublished artifacts.
6. Keep the local directory and VS Code session as they are. A later move, after the session is
   complete, should account for interpreter/virtual-environment paths, launch settings, and local
   tools; it is not part of this migration. Keep `agentHost.runtime.sessions.bindingId` stable when
   only repository hosting changes; changing it denotes another runtime deployment, not a rename.

After hosting migration, run the existing contract check and backend test gates, then begin the
owner's code review. No broad code refactor or expansion implementation is bundled into these steps.

GitHub's redirect limits and remote-update recommendation are documented in
[Renaming a Repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

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