# Runbook Planning Boundary Security Review

Review date: 2026-09-02

Status: planning and Governor API read boundary implemented locally;
production mount/deployment and all execution remain unapproved.

## Scope

This review covers the version 1 runbook schema, pinned catalog manifest,
local planner, non-networked mock lifecycle, and a proposed adapter for the
existing H3 maintenance report. It does not approve a host executor,
confirmation endpoint, package update, image pull, container recreation,
restart, deployment, or production rollout.

## Findings

- Catalog selection is fixed in code; callers cannot provide a catalog path.
- Schema and catalog bytes are pinned by an unsigned SHA-256 manifest, and the
  digests are bound into normalized operation IDs.
- Every catalog entry is structurally dry-run-only with production writes
  disabled.
- The mock adapter exactly re-derives input plans and returns only deterministic
  fake evidence in memory.
- The planner package has source tests rejecting process, shell, Docker,
  network, dynamic-code, and related execution imports.
- Git review and branch controls are currently the provenance authority. The
  manifest does not defend against an attacker who can change both catalog and
  manifest in an approved commit.
- No durable Governor authorization, confirmation consumption, audit store,
  backup verifier, rollback dispatcher, or restricted host process exists.

## Approved Read Boundary

The next local-only adapter may read exactly:

```text
/data/discord-system/maintenance.json
```

That file is already generated host-side by the existing guarded
`kaos-h3 maintenance-report` workflow. The adapter must:

- accept no caller-supplied path;
- cap input size before JSON parsing;
- select exactly one `kaosgdd` target and return no other host record;
- reject failed, missing, malformed, duplicate, future-dated, or stale data;
- expose typed counts, reboot state, container health counts, report time, and
  the explicit fact that container images were not checked;
- perform no collection, package-index refresh, image pull, command,
  subprocess, network request, or write;
- remain unwired from production until a separate deployment review.

## Data and Trust Notes

Maintenance report content is untrusted operational data. It may describe
conditions but cannot alter policy, select a runbook, add a target, construct a
command, or authorize an action. Error output must be stable and must not echo
arbitrary report content.

The existing report provides cached package counts and Docker Engine package
counts. It does not reliably determine application container-image updates,
because that requires an explicit registry/image interaction. The adapter must
state that limitation rather than infer image availability.

## Unapproved Boundaries

- Any configurable filesystem path in a production request
- SSH, sudo, shell, subprocess, Docker socket, Docker API, or systemd access
- Package index refresh or package-manager invocation
- Registry access or image pull
- Secrets, environment dumps, service credentials, or raw report passthrough
- Persistent audit writes outside Governor ownership
- Confirmation acceptance or state transition
- Restart, update, deploy, rollback, reboot, PACS, database, OS-security, or
  firewall execution

## Required Review Before Production Wiring

1. Verify the deployment mount is the single expected file and read-only.
2. Define the Governor-owned API response and actor/profile authorization.
3. Add data-redaction and response-size tests at the API boundary.
4. Define freshness monitoring and the host-side report generation schedule.
5. Confirm that the adapter process has no Docker socket, SSH key, sudo,
   package-manager authority, or unrelated host filesystem mount.
6. Complete local integration tests, then request a separately normalized
   deployment confirmation with verification and rollback notes.

## Local API Implementation

The reviewed parser now lives in the Governor package and backs protected
`GET /api/system/updates`. The handler requires the existing personal
Cloudflare Access verification and main host profile, returns only normalized
bounded fields, and maps parser failures to stable error codes. Tests cover
identity rejection, normalization, response size, redaction, freshness, target
uniqueness, host match, counts, and prohibited imports.

The endpoint is source code only. No Compose mount, proxy route, Brain intent,
PWA control, service recreation, or production deployment is included. The
runtime therefore cannot read the host report until the separately reviewed
read-only mount and deployment are approved.
