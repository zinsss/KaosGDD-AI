-- Governor durable operation foundation.
-- This schema is intentionally independent from domain-owned service data.

CREATE TABLE IF NOT EXISTS governor_operations (
    operation_id text PRIMARY KEY,
    idempotency_key text NOT NULL,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    scope text NOT NULL,
    tool_name text NOT NULL,
    operation_type text NOT NULL,
    request_hash text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text NOT NULL DEFAULT '',
    CHECK (actor_type IN ('user', 'family_user', 'service', 'system')),
    CHECK (scope IN ('personal', 'family', 'clinic', 'system')),
    CHECK (status IN ('pending', 'requires_confirmation', 'confirmed', 'completed', 'failed', 'expired', 'cancelled')),
    CHECK (idempotency_key <> ''),
    CHECK (actor_id <> ''),
    CHECK (tool_name <> ''),
    CHECK (operation_type <> ''),
    CHECK (request_hash ~ '^[a-f0-9]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS governor_operations_actor_idempotency_idx
    ON governor_operations (actor_type, actor_id, scope, idempotency_key);

CREATE INDEX IF NOT EXISTS governor_operations_status_idx
    ON governor_operations (status, updated_at);

CREATE TABLE IF NOT EXISTS governor_confirmations (
    confirmation_id text PRIMARY KEY,
    operation_id text NOT NULL REFERENCES governor_operations(operation_id) ON DELETE CASCADE,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    scope text NOT NULL,
    normalized_operation_hash text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CHECK (actor_type IN ('user', 'family_user', 'service', 'system')),
    CHECK (scope IN ('personal', 'family', 'clinic', 'system')),
    CHECK (status IN ('pending', 'approved', 'expired', 'cancelled')),
    CHECK (normalized_operation_hash ~ '^[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS governor_confirmations_operation_idx
    ON governor_confirmations (operation_id, status);

CREATE INDEX IF NOT EXISTS governor_confirmations_expiry_idx
    ON governor_confirmations (status, expires_at);

CREATE TABLE IF NOT EXISTS governor_audit_records (
    audit_id text PRIMARY KEY,
    operation_id text REFERENCES governor_operations(operation_id) ON DELETE SET NULL,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    scope text NOT NULL,
    event_type text NOT NULL,
    tool_name text NOT NULL DEFAULT '',
    idempotency_key text NOT NULL DEFAULT '',
    request_hash text NOT NULL DEFAULT '',
    outcome text NOT NULL,
    reason text NOT NULL DEFAULT '',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (actor_type IN ('user', 'family_user', 'service', 'system')),
    CHECK (scope IN ('personal', 'family', 'clinic', 'system')),
    CHECK (event_type <> ''),
    CHECK (outcome IN ('accepted', 'rejected', 'requires_confirmation', 'approved', 'completed', 'failed', 'expired', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS governor_audit_records_operation_idx
    ON governor_audit_records (operation_id, created_at);

CREATE INDEX IF NOT EXISTS governor_audit_records_actor_idx
    ON governor_audit_records (actor_type, actor_id, scope, created_at);
