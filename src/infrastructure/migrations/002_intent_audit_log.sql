-- Intent audit log for debugging "why did the bot do that?"
-- Append-only, monthly partitions, 90-day retention

CREATE TABLE IF NOT EXISTS intent_audit_log (
    id              BIGSERIAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Message context
    channel_id      TEXT NOT NULL,
    thread_ts       TEXT,
    message_ts      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    message_text    TEXT NOT NULL,

    -- PreGate stage
    pregate_result  TEXT,
    pregate_data    JSONB,

    -- LLM classification stage
    raw_mode        TEXT,
    raw_confidence  FLOAT,
    classified_mode TEXT NOT NULL,
    classified_confidence FLOAT NOT NULL,
    entity_type     TEXT,
    target_entity_id TEXT,
    entities_mentioned JSONB,
    reasoning       TEXT,

    -- Performance
    classification_ms INTEGER,

    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Create partitions for current and next 2 months
-- (In production, a cron job would create future partitions)
CREATE TABLE IF NOT EXISTS intent_audit_log_default PARTITION OF intent_audit_log DEFAULT;
