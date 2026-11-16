-- ===== NEW for the split: local copies kept from events (plan/tech/03-events.md section 6)
-- Rule: a copy is read-only for this service, has source_version, and an older event never overwrites a newer row.

CREATE TABLE list_copies (
  list_id         uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  space_id        uuid NOT NULL,
  folder_id       uuid,
  status_set_id   uuid NOT NULL,
  archived        boolean NOT NULL DEFAULT false,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);
CREATE INDEX list_copies_ws_idx ON list_copies (workspace_id);

CREATE TABLE status_copies (
  status_id       uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  status_set_id   uuid NOT NULL,
  name            text NOT NULL,
  category        text NOT NULL CHECK (category IN ('open','custom','done','closed')),
  position        text NOT NULL COLLATE "C",
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);
CREATE INDEX status_copies_set_idx ON status_copies (workspace_id, status_set_id);

-- fields that must be filled before a task may enter a status (hierarchy.status_required_fields)
CREATE TABLE status_required_field_copies (
  workspace_id    uuid NOT NULL,
  status_id       uuid NOT NULL,
  field_id        uuid NOT NULL,
  PRIMARY KEY (workspace_id, status_id, field_id)
);

CREATE TABLE task_type_copies (
  task_type_id    uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  name            text NOT NULL,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);

CREATE TABLE member_copies (
  workspace_id    uuid NOT NULL,
  user_id         uuid NOT NULL,
  role_kind       text NOT NULL,
  status          text NOT NULL,
  source_version  integer NOT NULL,
  PRIMARY KEY (workspace_id, user_id)
);

-- number and money people-field values that formulas may read (rate per person)
CREATE TABLE people_value_copies (
  workspace_id    uuid NOT NULL,
  user_id         uuid NOT NULL,
  field_id        uuid NOT NULL,
  number_value    numeric(20,6),
  money_cents     bigint,
  money_currency  char(3),
  source_version  integer NOT NULL,
  PRIMARY KEY (workspace_id, user_id, field_id)
);

-- Time per task, from time entry.* events. Kept per entry so a repeat or a late event can never double count.
CREATE TABLE time_entry_copies (
  entry_id        uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  task_id         uuid NOT NULL,
  user_id         uuid NOT NULL,
  duration_ms     bigint NOT NULL,
  billable        boolean NOT NULL,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);
CREATE INDEX time_entry_copies_task_idx ON time_entry_copies (workspace_id, task_id);

-- Totals the formula engine and views read ("time logged"; "rolled up" = task plus all subtasks).
-- Updated in the same transaction as time_entry_copies by adding the difference.
CREATE TABLE task_time_totals (
  workspace_id    uuid NOT NULL,
  task_id         uuid NOT NULL,
  tracked_ms      bigint NOT NULL DEFAULT 0,
  billable_ms     bigint NOT NULL DEFAULT 0,
  rolled_up_ms    bigint NOT NULL DEFAULT 0,         -- self + descendants, maintained up the parent chain
  rolled_up_billable_ms bigint NOT NULL DEFAULT 0,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, task_id)
);

-- Human task numbers (#123) without a hot row: each pod reserves a block of 100 numbers at a time.
-- Numbers stay unique per workspace; gaps are allowed.
CREATE TABLE task_number_blocks (
  workspace_id    uuid PRIMARY KEY,
  next_free       bigint NOT NULL DEFAULT 1
);

-- Decision D18 (plan/tech/12-decisions.md): the rich task description uses the same rich-text JSON as collab.comments.body.
-- description stays as the plain/markdown projection for search, events and email.
ALTER TABLE tasks ADD COLUMN description_doc jsonb;
