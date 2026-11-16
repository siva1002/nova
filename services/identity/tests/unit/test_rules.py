"""Domain rules of identity: pure functions, no fakes needed."""

from uuid import uuid4

import pytest

from identity_service.domain.errors import InvalidDisplayName, InvalidEmail, WeakPassword
from identity_service.domain.rules import (
    clean_display_name,
    color_for,
    hash_refresh_token,
    initials_of,
    normalize_email,
    username_from,
    validate_password,
)


def test_email_is_trimmed_and_lowercased():
    assert normalize_email("  Asha.Rao@Example.COM ") == "asha.rao@example.com"


@pytest.mark.parametrize(
    "bad", ["", "asha", "asha@", "@example.com", "a b@example.com", "asha@example", "a@" + "x" * 260 + ".com"]
)
def test_malformed_email_is_rejected(bad):
    with pytest.raises(InvalidEmail):
        normalize_email(bad)


def test_password_length_bounds():
    validate_password("a" * 12, "asha@example.com")
    validate_password("a" * 128, "asha@example.com")
    for bad in ("a" * 11, "a" * 129, " " * 14):
        with pytest.raises(WeakPassword):
            validate_password(bad, "asha@example.com")


def test_password_may_not_be_the_email():
    with pytest.raises(WeakPassword):
        validate_password("Asha.Rao.Long@example.com", "asha.rao.long@example.com")
    with pytest.raises(WeakPassword):
        validate_password("ashaisverylong", "ashaisverylong@example.com")


def test_display_name_is_cleaned_and_bounded():
    assert clean_display_name("  Asha   Rao ") == "Asha Rao"
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(InvalidDisplayName):
            clean_display_name(bad)


def test_initials():
    assert initials_of("Asha Rao") == "AR"
    assert initials_of("asha") == "A"
    assert initials_of("Asha Devi Rao") == "AR"


def test_color_is_stable_per_user_and_username_comes_from_email():
    uid = uuid4()
    assert color_for(uid) == color_for(uid) and color_for(uid).startswith("#")
    assert username_from("asha.rao@example.com") == "asha.rao"


def test_refresh_token_hash_is_sha256_and_deterministic():
    assert hash_refresh_token("abc") == hash_refresh_token("abc") != hash_refresh_token("abd")
    assert len(hash_refresh_token("abc")) == 32
