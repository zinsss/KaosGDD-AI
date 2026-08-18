-- Governor recurring task definition metadata.
-- Radicale remains authoritative for generated VTODO task records.

CREATE TABLE IF NOT EXISTS governor_recurring_task_definitions (
    definition_id text PRIMARY KEY,
    owner text NOT NULL CHECK (owner IN ('zin', 'wife', 'family')),
    scope text NOT NULL CHECK (scope IN ('personal', 'family')),
    adapter_profile text NOT NULL CHECK (adapter_profile IN ('main', 'family')),
    collection_id text NOT NULL,
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    memo text NOT NULL DEFAULT '',
    first_due_date date NOT NULL,
    due_time time without time zone NOT NULL DEFAULT '10:00',
    priority text NOT NULL DEFAULT '' CHECK (priority IN ('', '1', '5', '9')),
    frequency text NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    creation_policy text NOT NULL DEFAULT 'on_schedule' CHECK (creation_policy IN ('on_schedule', 'on_completion')),
    enabled boolean NOT NULL DEFAULT true,
    active_uid text,
    active_collection_id text,
    active_due_date date,
    next_due_date date,
    last_completed_uid text,
    last_completed_at timestamptz,
    last_error text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE governor_recurring_task_definitions
    ADD COLUMN IF NOT EXISTS creation_policy text NOT NULL DEFAULT 'on_schedule'
    CHECK (creation_policy IN ('on_schedule', 'on_completion'));

CREATE INDEX IF NOT EXISTS governor_recurring_task_definitions_enabled_idx
    ON governor_recurring_task_definitions (enabled, adapter_profile, updated_at);

CREATE INDEX IF NOT EXISTS governor_recurring_task_definitions_owner_idx
    ON governor_recurring_task_definitions (owner, scope, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS governor_recurring_task_definitions_active_uid_idx
    ON governor_recurring_task_definitions (active_collection_id, active_uid)
    WHERE active_uid IS NOT NULL;

COMMENT ON TABLE governor_recurring_task_definitions IS
    'KaosGovernor recurrence definitions and generated VTODO UID mappings. Actual task data remains authoritative in Radicale.';
