# KaosSystemOperator Runbooks

Status: Phase 2 planning only; no executor is implemented or enabled.

## Purpose

This directory is the repository-controlled catalog for typed system-operation
plans. A catalog entry describes policy and expected evidence. It is not a
script, command alias, deployment manifest, or authorization to touch a host.

Every current entry is constrained by the schema to `dry-run-only` and
`productionWritesEnabled: false`. Nothing in this directory is wired to
KaosBrain, KaosGovernor, a host service, SSH, sudo, the Docker socket, or a
production secret.

## Directory Structure

```text
runbooks/
  README.md
  schema/
    runbook.schema.json
  catalog/
    service.restart.json
    system.disk_status.json
    system.git_status.json
    system.logs_tail.json
    system.status.json
```

`schema/runbook.schema.json` is the version 1 JSON Schema. `catalog/` contains
reviewable runbook definitions, one stable operation per file. Future trusted
implementations belong in a separately reviewed executor change and must not
be inferred from these definitions.

## Contract

Each runbook records:

- a stable operation name and contract version;
- the exact allowed host and target class;
- the exact action and whether the proposed action would mutate a system;
- bounded, typed parameters rather than free-form command arguments;
- preflight requirements;
- confirmation policy and normalized confirmation fields;
- verification evidence expected from a future trusted implementation;
- a rollback note, including when rollback is not applicable;
- the required durable operation-log fields.

The catalog is intentionally narrow. Host and target values are allowlisted
per entry. Additional properties fail schema validation. Free-form shell,
executable paths, environment variables, credentials, and implementation
details are outside this contract.

## Current Planning Semantics

The four `system.*` entries describe read-only observations. They require no
confirmation, but a future caller must still be authenticated and authorized
by Governor policy. `system.logs_tail` requires a bounded line count and never
requests an unbounded stream.

`service.restart` describes only the plan for a future allowlisted restart. It
requires exact, expiring confirmation bound to host, target, action, expected
interruption, and operation ID. Its catalog entry cannot execute a restart;
the schema explicitly disables production writes.

## Validation

From the repository root, validate JSON syntax and schema conformance without
executing any runbook:

```text
jq empty runbooks/schema/runbook.schema.json runbooks/catalog/*.json
python3 -m jsonschema \
  --instance runbooks/catalog/system.status.json \
  runbooks/schema/runbook.schema.json
```

Repeat the schema command for every file in `runbooks/catalog/`. Validation is
read-only and does not contact a managed host.

## Future Execution Gate

Enabling execution requires a later, separately reviewed phase that provides:

1. a restricted host-local executor with no arbitrary command interface;
2. a trusted, version-pinned implementation for each operation and target;
3. Governor authorization, normalized operation IDs, expiry, and audit;
4. preflight and verification evidence capture;
5. exact confirmation for restart, reboot, update, and deploy;
6. an operation-log receipt and a tested rollback path where applicable.

PACS, database, OS, package, firewall, security, and secrets maintenance stay
outside this catalog and require a separate hardened maintenance flow.
