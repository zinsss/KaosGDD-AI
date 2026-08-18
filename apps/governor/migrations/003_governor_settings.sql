-- Governor settings foundation.
-- These records store user/system preferences, not service-owned data.

CREATE TABLE IF NOT EXISTS governor_settings (
    settings_key text PRIMARY KEY,
    settings_scope text NOT NULL DEFAULT 'system' CHECK (settings_scope IN ('personal', 'family', 'clinic', 'system')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (settings_key <> '')
);

CREATE INDEX IF NOT EXISTS governor_settings_scope_idx
    ON governor_settings (settings_scope, updated_at DESC);

COMMENT ON TABLE governor_settings IS
    'KaosGovernor configuration preferences such as weather location and imported public holiday source. Service data remains authoritative in its owning backend.';
