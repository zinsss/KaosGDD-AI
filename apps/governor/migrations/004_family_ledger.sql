CREATE TABLE IF NOT EXISTS family_ledger_entries (
    id text PRIMARY KEY,
    sort_order bigint NOT NULL UNIQUE,
    entry_date date NOT NULL,
    category text NOT NULL CHECK (length(btrim(category)) > 0),
    amount bigint CHECK (amount IS NULL OR amount >= 0),
    details text NOT NULL DEFAULT '',
    account_delta bigint NOT NULL DEFAULT 0,
    cash_delta bigint NOT NULL DEFAULT 0,
    gift_delta bigint NOT NULL DEFAULT 0,
    source_row integer,
    source_checksum text NOT NULL DEFAULT '',
    locked boolean NOT NULL DEFAULT false,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_by text NOT NULL DEFAULT 'family',
    updated_by text NOT NULL DEFAULT 'family',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE INDEX IF NOT EXISTS family_ledger_active_order_idx
    ON family_ledger_entries(sort_order)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS family_ledger_audit (
    id bigserial PRIMARY KEY,
    entry_id text NOT NULL,
    action text NOT NULL CHECK (action IN ('import', 'create', 'update', 'delete')),
    actor text NOT NULL,
    before_data jsonb,
    after_data jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS family_ledger_audit_created_idx
    ON family_ledger_audit(created_at DESC, id DESC);
