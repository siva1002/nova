"""THE MVP PERMISSION RULE: what each workspace role may do. PURE.

This is the "role check" shortcut of sprint 1 (docs/adr/0002). It answers the same question as the full
engine of sprint 13 (rules R1 to R13, custom roles, per-node grants, own-only limits), behind the same
`checkPermissions` API, so callers do not change when the engine arrives.

Capability keys are exactly the rows of the `capabilities` table (tools/db-split/access.sql). The sets
below mirror the role templates that `seed_default_roles()` writes for every new workspace:
    owner  -> template boss_admin   (everything)
    admin  -> template super_admin  (everything except billing and ownership transfer)
    member -> template associate    (+ create_container, so members can add folders and lists)
    guest  -> template guest        (read and comment)

Not covered here on purpose: PRIVATE SPACES. Who may see a private space is decided by the hierarchy
service, which owns the space member lists (task S1-12).
"""

from __future__ import annotations

from access_service.domain.errors import MissingCapability
from access_service.domain.models import Member

NODE_CAPABILITIES = frozenset(
    {
        "view", "comment", "edit", "create", "delete", "manage_fields", "manage_views", "manage_access",
        "create_container", "track_time", "manage_automations", "manage_forms_templates", "approve",
        "export_data", "view_activity", "share_externally", "manage_dashboards",
        "view_costs", "manage_budgets", "approve_expenses", "use_ai",
    }
)  # fmt: skip
WORKSPACE_CAPABILITIES = frozenset(
    {
        "manage_workspace_settings", "manage_billing", "transfer_ownership", "manage_users", "manage_roles",
        "create_space", "view_audit", "manage_security", "manage_integrations", "manage_api_tokens",
        "manage_timesheets", "manage_ai_settings", "view_people_fields", "manage_people_fields",
    }
)  # fmt: skip
ALL_CAPABILITIES = NODE_CAPABILITIES | WORKSPACE_CAPABILITIES

_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": ALL_CAPABILITIES,
    "admin": ALL_CAPABILITIES - {"manage_billing", "transfer_ownership"},
    "member": frozenset(
        {"view", "comment", "edit", "create", "create_container", "track_time", "approve", "manage_views", "use_ai"}
    ),
    "guest": frozenset({"view", "comment"}),
}


def role_allows(role_kind: str, capability: str) -> bool:
    """Unknown role or unknown capability -> False. The check fails closed."""
    return capability in _ROLE_CAPABILITIES.get(role_kind, frozenset())


def member_allows(member: Member | None, capability: str) -> bool:
    """A missing or non-active membership allows nothing."""
    return member is not None and member.is_active and role_allows(member.role_kind, capability)


def require_capability(member: Member, capability: str) -> None:
    if not member_allows(member, capability):
        raise MissingCapability(f"Missing permission: {capability}")
