-- ===== NEW for the split: tasks in sprint lists, for capacity, burndown and close/rollover
CREATE TABLE sprint_task_copies (
  task_id         uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  list_id         uuid NOT NULL,                     -- the sprint list (home or extra membership)
  in_list_ids     uuid[] NOT NULL,                   -- every list the task is in
  status_category text NOT NULL,
  points          numeric(10,2),
  time_estimate_ms bigint,
  assignee_ids    uuid[] NOT NULL DEFAULT '{}',
  done_at         timestamptz,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);
CREATE INDEX sprint_task_copies_list_idx ON sprint_task_copies (workspace_id, list_id);
CREATE INDEX sprint_task_copies_in_list_gin ON sprint_task_copies USING gin (in_list_ids);
