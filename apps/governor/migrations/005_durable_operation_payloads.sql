-- Persist normalized operation parameters and short-lived execution payloads.
-- Payload rows contain JSON metadata only; binaries and credentials are rejected
-- by the Governor store before insertion and rows are removed at terminal state.

ALTER TABLE governor_operations
    ADD COLUMN IF NOT EXISTS parameters jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE governor_operations
    DROP CONSTRAINT IF EXISTS governor_operations_parameters_object;

ALTER TABLE governor_operations
    ADD CONSTRAINT governor_operations_parameters_object
    CHECK (jsonb_typeof(parameters) = 'object');

CREATE TABLE IF NOT EXISTS governor_operation_payloads (
    operation_id text PRIMARY KEY REFERENCES governor_operations(operation_id) ON DELETE CASCADE,
    payload_kind text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (payload_kind ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$'),
    CHECK (schema_version BETWEEN 1 AND 1000),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS governor_operation_payloads_updated_idx
    ON governor_operation_payloads (updated_at);
