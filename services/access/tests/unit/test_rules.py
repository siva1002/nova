"""Domain rules of access: the role table, workspace names and slugs, invite tokens. Pure functions."""

from uuid import uuid4

import pytest

from access_service.domain.errors import InvalidWorkspace, InviteGone
from access_service.domain.roles import ALL_CAPABILITIES, role_allows
from access_service.domain.rules import (
    clean_slug,
    clean_workspace_name,
    decode_invite_token,
    encode_invite_token,
    hash_invite_token,
    normalize_email,
)


# --------------------------------------------------------------------------------------------- role table
def test_owner_can_do_everything():
    assert all(role_allows("owner", cap) for cap in ALL_CAPABILITIES)


def test_admin_can_do_everything_except_billing_and_ownership_transfer():
    denied = {cap for cap in ALL_CAPABILITIES if not role_allows("admin", cap)}
    assert denied == {"manage_billing", "transfer_ownership"}


@pytest.mark.parametrize("cap", ["view", "comment", "edit", "create", "create_container", "track_time"])
def test_member_can_do_everyday_work(cap):
    assert role_allows("member", cap)


@pytest.mark.parametrize(
    "cap", ["manage_users", "manage_workspace_settings", "manage_roles", "delete", "manage_timesheets", "create_space"]
)
def test_member_cannot_administer(cap):
    assert not role_allows("member", cap)


def test_guest_reads_and_comments_only():
    assert {cap for cap in ALL_CAPABILITIES if role_allows("guest", cap)} == {"view", "comment"}


@pytest.mark.parametrize(("role", "cap"), [("owner", "fly"), ("superuser", "view"), ("", "view"), ("member", "")])
def test_unknown_role_or_capability_is_denied(role, cap):
    assert not role_allows(role, cap)  # fails closed


# ------------------------------------------------------------------------------------- names, slugs, email
def test_workspace_name_is_cleaned_and_bounded():
    assert clean_workspace_name("  Pilot   Team ") == "Pilot Team"
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(InvalidWorkspace):
            clean_workspace_name(bad)


def test_slug_rules():
    assert clean_slug(" Pilot-2026 ") == "pilot-2026"
    for bad in ("ab", "has space", "under_score", "x" * 41, "ünï"):
        with pytest.raises(InvalidWorkspace):
            clean_slug(bad)


def test_email_normalisation():
    assert normalize_email("  Ben@Example.COM ") == "ben@example.com"
    assert normalize_email("not-an-email") is None


# ------------------------------------------------------------------------------------------- invite tokens
def test_invite_token_round_trips_the_workspace_id():
    ws = uuid4()
    token = encode_invite_token(ws, bytes(range(32)))
    assert decode_invite_token(token) == ws
    assert "=" not in token and "/" not in token and "+" not in token  # safe inside a URL


def test_only_the_hash_of_a_token_is_comparable():
    ws = uuid4()
    a, b = encode_invite_token(ws, bytes(32)), encode_invite_token(ws, bytes([1] * 32))
    assert hash_invite_token(a) == hash_invite_token(a) != hash_invite_token(b)
    assert len(hash_invite_token(a)) == 64 and a not in hash_invite_token(a)


@pytest.mark.parametrize("bad", ["", "abc", "!!!!", "A" * 10, "A" * 200, "ünïcödé"])
def test_malformed_tokens_are_dead_links(bad):
    with pytest.raises(InviteGone):
        decode_invite_token(bad)


def test_invite_secret_must_be_32_bytes():
    with pytest.raises(ValueError, match="32 bytes"):
        encode_invite_token(uuid4(), b"short")
