-- ===== NEW for the split: copy of tasks so a time entry can be checked and reported by list
CREATE TABLE task_copies (
  task_id         uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL,
  home_list_id    uuid NOT NULL,
  parent_task_id  uuid,
  title           text NOT NULL,
  archived        boolean NOT NULL DEFAULT false,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL
);
CREATE INDEX task_copies_list_idx ON task_copies (workspace_id, home_list_id);
