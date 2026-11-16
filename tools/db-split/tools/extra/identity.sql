-- ===== NEW for the split (plan/tech/02-data-and-cells.md)

-- "My workspaces" and sign-in routing without asking every cell. Copy kept from access member.* events.
CREATE TABLE user_workspaces (
  user_id         uuid NOT NULL REFERENCES users(id),
  workspace_id    uuid NOT NULL,                     -- id -> access.workspaces (in some cell)
  cell_id         text NOT NULL,                     -- id -> routing.cells
  workspace_name  text NOT NULL,
  role_kind       text NOT NULL CHECK (role_kind IN ('owner','admin','member','guest')),
  status          text NOT NULL CHECK (status IN ('active','pending','deactivated')),
  source_version  integer NOT NULL,                  -- member row version; older events are ignored
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, workspace_id)
);

-- One-time tokens: email verification, password reset. Hashed, single use, short life.
CREATE TABLE auth_tokens (
  token_hash      bytea PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES users(id),
  kind            text NOT NULL CHECK (kind IN ('verify_email','reset_password')),
  expires_at      timestamptz NOT NULL,
  used_at         timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_tokens_user_idx ON auth_tokens (user_id, kind);

-- Token signing keys. Private key material stays in the cloud key service (KMS); only a reference here.
-- Published as JWKS; rotate every 90 days, keep the old key until all its tokens expired.
CREATE TABLE signing_keys (
  kid             text PRIMARY KEY,
  algorithm       text NOT NULL DEFAULT 'EdDSA',
  public_jwk      jsonb NOT NULL,
  kms_key_ref     text NOT NULL,
  status          text NOT NULL CHECK (status IN ('next','active','retiring','retired')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  retire_after    timestamptz
);
CREATE UNIQUE INDEX signing_keys_one_active_uk ON signing_keys (status) WHERE status = 'active';

-- Global service: rows are per user, not per workspace; the service filters by the signed-in user.
COMMENT ON TABLE user_workspaces IS 'rls:exempt global, filtered by user';
COMMENT ON TABLE idempotency_keys IS 'rls:exempt global service';
