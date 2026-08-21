# ADR 0009: Mabrid Product Identity

- Status: Accepted
- Date: 2026-08-21
- Supersedes: the Cembrid brand decision in ADR 0007

## Context

ADR 0007 selected Cembrid as a future product identity and separately fixed two deployment shells:
the v0.1 Web/OCI service and a post-v0.1 Tauri desktop application. The Cembrid name has not been
adopted across repository, package, executable, configuration, or protocol interfaces.

The product owner no longer considers Cembrid a suitable long-term name and prefers Mabrid. The
architecture migration is complete, while first-release product contracts and behavior are still
being built. Renaming implementation surfaces now would create churn without advancing those
release gates.

## Decision

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

As of 2026-08-21:

- **Decision complete:** Mabrid replaces Cembrid as the intended future brand.
- **Deferred:** coordinated repository, package, executable, configuration, UI, and
  protocol-identity migration.
