-- ===== NEW for the cell design (plan/tech/02-data-and-cells.md). Global, one per region, tiny and read-heavy:
-- the gateway caches workspace -> cell for 60 s and is told of changes by the routing.workspace.changed event.

CREATE TABLE cells (
  id              text PRIMARY KEY,                  -- 'aps1-c01': region code + number, also the DNS label
  region          text NOT NULL,                     -- cloud region code
  status          text NOT NULL DEFAULT 'building' CHECK (status IN ('building','active','full','draining','retired')),
  max_workspaces  integer NOT NULL DEFAULT 5000,     -- planning limit (scale-guide D); new tenants go to the emptiest active cell
  is_dedicated    boolean NOT NULL DEFAULT false,    -- one big tenant only
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  version         integer NOT NULL DEFAULT 1
);

CREATE TABLE workspace_directory (
  workspace_id    uuid PRIMARY KEY,
  tenant_id       uuid REFERENCES tenants(id),
  cell_id         text NOT NULL REFERENCES cells(id),
  slug            text NOT NULL,                     -- URL name, unique across the product
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('provisioning','active','moving','read_only','suspended','deleted')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX workspace_directory_slug_uk ON workspace_directory (lower(slug));
CREATE INDEX workspace_directory_cell_idx ON workspace_directory (cell_id);

-- Moving a workspace between cells (plan/tech/02 section 5). One active move per workspace.
CREATE TABLE cell_moves (
  id              uuid PRIMARY KEY,
  workspace_id    uuid NOT NULL REFERENCES workspace_directory(workspace_id),
  from_cell_id    text NOT NULL REFERENCES cells(id),
  to_cell_id      text NOT NULL REFERENCES cells(id),
  state           text NOT NULL DEFAULT 'planned' CHECK (state IN ('planned','copying','catching_up','frozen','switched','cleaning','done','failed','rolled_back')),
  reason          text,
  started_at      timestamptz,
  finished_at     timestamptz,
  error           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  version         integer NOT NULL DEFAULT 1,
  CHECK (from_cell_id <> to_cell_id)
);
CREATE UNIQUE INDEX cell_moves_one_active_uk ON cell_moves (workspace_id) WHERE state NOT IN ('done','failed','rolled_back');

-- An invite link does not say which cell it belongs to; this maps the hashed token to the workspace.
CREATE TABLE invite_routes (
  token_hash      bytea PRIMARY KEY,                 -- sha256 of the token, never the token
  workspace_id    uuid NOT NULL REFERENCES workspace_directory(workspace_id),
  expires_at      timestamptz NOT NULL
);
CREATE INDEX invite_routes_expiry_idx ON invite_routes (expires_at);

-- Global service: these tables are looked up across workspaces (routing), so no workspace row security.
COMMENT ON TABLE workspace_directory IS 'rls:exempt global routing';
COMMENT ON TABLE cell_moves IS 'rls:exempt global routing';
COMMENT ON TABLE invite_routes IS 'rls:exempt global routing';
COMMENT ON TABLE idempotency_keys IS 'rls:exempt global service';
