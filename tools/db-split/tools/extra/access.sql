-- ===== NEW for the split (plan/tech/04-permissions-spec.md)

-- Copy of the container tree, kept from hierarchy container.* events. The permission engine walks it.
CREATE TABLE container_tree (
  container_id    uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL REFERENCES workspaces(id),
  kind            text NOT NULL CHECK (kind IN ('space','folder','list')),
  parent_id       uuid,
  ancestor_ids    uuid[] NOT NULL,                   -- root first, including self
  is_restricted   boolean NOT NULL DEFAULT false,
  archived        boolean NOT NULL DEFAULT false,
  deleted         boolean NOT NULL DEFAULT false,
  source_version  integer NOT NULL,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX container_tree_ws_idx ON container_tree (workspace_id);

-- One counter per workspace, bumped by every change that can alter an answer (grant, role, member, group,
-- tree). It is part of every permission cache key, so a bump makes all cached answers of that workspace stale.
CREATE TABLE access_epochs (
  workspace_id    uuid PRIMARY KEY REFERENCES workspaces(id),
  epoch           bigint NOT NULL DEFAULT 1,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
