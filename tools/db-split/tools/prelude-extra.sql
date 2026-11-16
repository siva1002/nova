-- ============================================================================
-- Messaging tables every service has (plan/tech/03-events.md)
-- ============================================================================

-- OUTBOX: written in the same transaction as the business change. Debezium reads the INSERT from the
-- write-ahead log (outbox event router) and publishes to Kafka; a job deletes rows older than 1 hour.
-- Never read by the application. Kafka message key = workspace_id, so one workspace stays in order.
CREATE TABLE outbox (
  id              uuid PRIMARY KEY,                 -- event id (uuidv7), consumers dedupe on it
  workspace_id    uuid NOT NULL,                    -- Kafka key and partition
  aggregate_type  text NOT NULL,                    -- 'task', 'list', 'member' ... -> topic <service>.<aggregate_type>
  aggregate_id    uuid NOT NULL,
  aggregate_version integer,                        -- version of the row after the change, for ordering checks
  event_type      text NOT NULL,                    -- 'task.updated' (catalogue in 03-events.md)
  schema_version  smallint NOT NULL DEFAULT 1,
  payload         jsonb NOT NULL,                   -- the event body (JSON Schema in contracts/events)
  actor_user_id   uuid,                             -- NULL for system and automation
  origin          text NOT NULL DEFAULT 'user' CHECK (origin IN ('user','automation','import','system','api')),
  causation_id    uuid,                             -- event that caused this one (automation chains)
  depth           smallint NOT NULL DEFAULT 0,      -- automation loop guard, stop at 5
  trace_parent    text,                             -- W3C traceparent, carried into Kafka headers
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_created_idx ON outbox (created_at);

-- INBOX: events this service has handled. Insert first, ON CONFLICT DO NOTHING; if no row was inserted
-- the event is a repeat and is skipped. Same transaction as the effect. Rows older than 14 days deleted
-- (Kafka retention is 7 days, so a repeat older than that cannot arrive).
CREATE TABLE inbox (
  consumer        text NOT NULL,                    -- consumer group name
  event_id        uuid NOT NULL,
  workspace_id    uuid NOT NULL,
  handled_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);
CREATE INDEX inbox_handled_idx ON inbox (handled_at);

-- IDEMPOTENCY: every POST/PATCH accepts an Idempotency-Key header. Same key + same body within 24 h
-- returns the stored response; same key + different body returns 422.
CREATE TABLE idempotency_keys (
  workspace_id    uuid NOT NULL,
  user_id         uuid NOT NULL,
  key             text NOT NULL,
  request_hash    bytea NOT NULL,                   -- sha256 of method + path + body
  status_code     smallint,
  response_body   jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id, key)
);
CREATE INDEX idempotency_keys_created_idx ON idempotency_keys (created_at);

-- Workspace of the current transaction, set by the app per transaction (see _epilogue.sql).
CREATE OR REPLACE FUNCTION current_workspace() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.workspace_id', true), '')::uuid $$;
