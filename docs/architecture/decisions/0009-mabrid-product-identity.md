# ADR 0009: Mabrid Product Identity

- Status: Accepted; code migration timing amended by ADR 0013; hosting sequence updated 2026-10-10
- Date: 2026-08-21
- Supersedes: the Cembrid brand decision in ADR 0007

ADR 0013 completed the coordinated Python and deployment-code identity migration during the
backend semantic refactor. ADR 0016 has now completed backend frontend-contract readiness. The
owner has selected repository-hosting migration next, with the local checkout directory retained
until the current editor session is finished. The original timing below is historical; the current
sequence and implementation status are recorded at the end of this ADR. The product identity and
deployment-shell decisions are unchanged.

## Context

ADR 0007 selected Cembrid as a future product identity and separately fixed two deployment shells:
the v0.1 Web/OCI service and a post-v0.1 Tauri desktop application. The Cembrid name has not been
adopted across repository, package, executable, configuration, or protocol interfaces.

The product owner no longer considers Cembrid a suitable long-term name and prefers Mabrid. The
architecture migration is complete, while first-release product contracts and behavior are still
being built. Renaming implementation surfaces now would create churn without advancing those
release gates.

## Decision

The timing statements in this original decision were amended by ADR 0013 and the 2026-10-10
hosting sequence below; they are not instructions to repeat the completed code migration.

The future product brand is **Mabrid**.

This ADR supersedes only the Cembrid identity selected by ADR 0007. ADR 0007's deployment-shell
decision remains accepted: Web/OCI is the v0.1 release shell, and Tauri is the post-v0.1 personal
desktop shell.

The current repository name, Python packages, JavaScript packages, executable names, HTTP paths,
configuration keys, database identifiers, and protocol-facing identities are not renamed as part
of the current v0.1 feature work. A later coordinated migration will adopt Mabrid after backend and
frontend contracts have stabilized. Until then, existing technical names remain working names and
must not be changed piecemeal.

Package, registry, executable, and domain availability must be checked before the coordinated
migration. This decision does not claim ownership or availability on PyPI, npm, crates.io, GitHub,
or the public DNS namespace.

## Consequences

- New architecture decisions refer to Mabrid when a future product name is required.
- Existing source and external interfaces avoid a mixed Cembrid/Mabrid partial rename.
- The rename remains separate from the v0.1 Gateway, Agent Host, UI, and OCI release gates.
- Deployment architecture from ADR 0007 is unchanged.

## Implementation Status

As of 2026-10-10:

- **Internal identity complete:** Python namespaces, distributions and descriptions, executable,
  Web title, configuration/database defaults, and backend development commands use Mabrid. The
  debug entry point's configuration examples use the current file name; its intentional overrides
  are unchanged. Identity regression checks do not depend on the checkout directory's name.
- **Frontend contract complete:** ADR 0016 establishes the frozen first-party backend baseline;
  it does not mark the frontend or v0.1 distribution complete.
- **Owner action pending:** rename the existing GitHub repository to `mabrid`, then update its
  About description and the existing checkout's remote URL. Preserve the existing history rather
  than creating a replacement repository. No hosting or remote change is performed in this batch.
- **Local checkout intentionally retained:** the root directory remains `mcpapps-bridge` for the
  current editor/session context. The directory is not the product identity, package namespace,
  executable, or runtime deployment binding. A later directory move is optional and separate.
- **Legacy frontend untouched:** adopt Mabrid frontend identity when the owner explicitly starts
  the rewrite, not through a rename-only pass over disposable frontend code.

## Product Positioning and About

Mabrid is an **MCP Apps gateway and agent host**, not only a protocol bridge. Its current backend
combines MCP management and inspection with native Agent Sessions, runtime-owned history, composed
Run presentation, and MCP Apps widget payloads. The reusable bridge remains a protocol component,
not the whole product. These two product pillars remain useful independently when Agent Host is
disabled for a deployment.

Recommended GitHub About description:

> An extensible MCP Apps gateway and agent host for MCP management, native sessions, and interactive apps.

"Extensible" describes the adapter-driven, typed composition boundaries and room for future
integrations. It does not advertise a released plugin SDK, dynamic plugin loader, marketplace,
finished frontend, or implemented Host follow-up actions. Particular expansion points are reviewed
in a separate discussion after code review, not implemented as part of identity migration.

The owner controls the remote About field. This text is a positioning recommendation, not a
completed GitHub update or a new v0.1 feature commitment. A project README remains deferred until
the project is complete.

## Migration Sequence

1. Commit repository-local migration preparation and retain the commit as a review baseline.
2. Rename the existing remote repository and update its About description.
3. Update and verify the remote URL in the existing checkout; retain the local directory and editor
   session, local configuration/secrets, SQLite state, and the stable runtime deployment binding.
4. Review the code with the owner before starting frontend implementation. Required corrections
   remain separate from identity changes and need focused validation.
5. Discuss expansion points to clarify the owner's mental model and relevant technical knowledge.
   Even an agreed direction or identified change is not authorization to implement it; a later
   explicit request is required.
6. Start the explicitly requested frontend rewrite against the frozen contract. Real integration
   and OCI/static-serving release gates remain separate work.

See [Frontend Readiness and Migration Handoff](../frontend-readiness.md) for verification commands,
review priorities, and remaining release gates. Remote hosting, local directory movement, code
identity, and runtime deployment identity are distinct changes and must not be conflated.
