ALTER TABLE governor_recurring_task_definitions
    DROP CONSTRAINT IF EXISTS governor_recurring_task_definitions_frequency_check;

ALTER TABLE governor_recurring_task_definitions
    ADD CONSTRAINT governor_recurring_task_definitions_frequency_check
    CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly', 'claim_day'));
