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
  catalog-manifest.json
  schema/
    runbook.schema.json
  catalog/
    containers.apply_update.json
    containers.check_updates.json
    containers.plan_update.json
    service.restart.json
    system.apply_updates.json
    system.check_updates.json
    system.disk_status.json
    system.git_status.json
    system.logs_tail.json
    system.plan_updates.json
    system.status.json
  planner/
    pyproject.toml
    src/kaos_runbook_planner/
    tests/
```

`schema/runbook.schema.json` is the version 1 JSON Schema. `catalog/` contains
reviewable runbook definitions, one stable operation per file. Future trusted
implementations belong in a separately reviewed executor change and must not
be inferred from these definitions.

`catalog-manifest.json` records the exact SHA-256 digest of the schema and
every allowlisted catalog file. The planner requires the on-disk catalog set
to match the manifest exactly and rejects changed, missing, or additional
files. This is an unsigned repository-integrity baseline: Git review and
branch controls provide provenance. No signing key or secret is used.

`planner/` is a repository-local, dry-run-only catalog validator and plan
renderer. It has no host adapter, subprocess use, network client, command
mapping, or execution method.

The planner package also contains `MockLifecycleAdapter`, a non-networked test
adapter. It re-derives and exactly compares a normalized plan before returning
deterministic in-memory lifecycle and audit receipts. It never reads host data
or writes an audit file. Read operations end as `simulated-complete`;
`service.restart` and both update-apply operations stop at
`confirmation-required` with no action taken.

`StoredMaintenanceReportAdapter` is the first real read boundary, but it is not
wired to an API or deployment. It reads only the fixed existing path
`/data/discord-system/maintenance.json`, caps the file at 256 KiB, selects the
unique `kaosgdd` record, requires a timezone-aware report no older than 48
hours, and returns normalized counts. It rejects missing, malformed, failed,
duplicate, future-dated, stale, mismatched-host, or invalid-count data. It
never invokes the host collector or echoes arbitrary report text.

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

The status, Git, disk, logs, and update-check entries describe read-only
observations. They require no confirmation, but a future caller must still be
authenticated and authorized by Governor policy. `system.logs_tail` requires a
bounded line count and never requests an unbounded stream.

`service.restart` describes only the plan for a future allowlisted restart. It
requires exact, expiring confirmation bound to host, target, action, expected
interruption, and operation ID. Its catalog entry cannot execute a restart;
the schema explicitly disables production writes.

System and container update planning is split into check, freeze-plan, and
apply-plan contracts. Apply plans accept only a required immutable
`sha256:<64 lowercase hexadecimal characters>` plan digest. They require an
exact, expiring confirmation bound to the host, target, action, plan digest,
backup status, rollback target, reboot requirement, expected interruption, and
operation ID. The current mock adapter stops at that confirmation boundary.

`system.*_updates` covers only a future allowlisted routine-package track on
H3. Kernel, security-policy, Docker Engine, database, and PACS maintenance are
excluded. `containers.*_update*` covers pinned application image digests for
the H3 Kaos backend stack; it is not Docker Engine maintenance and does not
permit arbitrary Compose arguments.

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

Run the planner tests and render an inert normalized plan from the repository
checkout:

```text
PYTHONPATH=runbooks/planner/src \
  python3 -m unittest discover -s runbooks/planner/tests -v
PYTHONPATH=runbooks/planner/src \
  python3 -m kaos_runbook_planner.cli system.status
PYTHONPATH=runbooks/planner/src \
  python3 -m kaos_runbook_planner.cli system.logs_tail \
    --parameters-json '{"lineCount": 25}'
```

The CLI selects from a fixed operation-to-catalog mapping. It does not accept
a catalog path. Output always records `mode: dry-run-only`,
`productionWritesEnabled: false`, and `executed: false`, plus a deterministic
plan ID, manifest digest, and selected catalog digest. Both digests are bound
into the plan ID. Output is a plan receipt, not evidence that a host
observation or action occurred.

Any reviewed change to the schema or catalog must update
`catalog-manifest.json` in the same commit. Reviewers should independently
compare its values with:

```text
sha256sum runbooks/schema/runbook.schema.json runbooks/catalog/*.json
```

The mock lifecycle adapter is available only as a Python test interface:

```python
from pathlib import Path

from kaos_runbook_planner import MockLifecycleAdapter, RunbookPlanner

planner = RunbookPlanner(Path.cwd())
receipt = MockLifecycleAdapter(planner).simulate(planner.plan("system.status"))
assert receipt["simulated"] is True
assert receipt["executed"] is False
```

This receipt is deterministic mock data. It must never be represented as a
real preflight, observation, verification, confirmation, or operation-log
record.

The stored-report adapter boundary and remaining production prerequisites are
reviewed in
[`docs/operator/runbook-planner-security-review.md`](../docs/operator/runbook-planner-security-review.md).

## Future Execution Gate

Enabling execution requires a later, separately reviewed phase that provides:

1. a restricted host-local executor with no arbitrary command interface;
2. a trusted, version-pinned implementation for each operation and target;
3. Governor authorization, normalized operation IDs, expiry, and audit;
4. preflight and verification evidence capture;
5. exact confirmation for restart, reboot, update, and deploy;
6. an operation-log receipt and a tested rollback path where applicable.

PACS, database, kernel, Docker Engine, firewall, security-policy, and secrets
maintenance stay outside this catalog and require a separate hardened
maintenance flow. Routine package and pinned container-image entries remain
planning-only until that execution gate is separately completed.
