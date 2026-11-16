"""Errors of the identity domain. Each maps to one HTTP status and one stable machine `code`
(see common.errors). Messages stay vague on purpose: they must not reveal whether an account exists."""

from common.errors import Forbidden, TooManyRequests, Unauthorized, Unprocessable


class InvalidCredentials(Unauthorized):
    # Same error for "no such email" and "wrong password": no account probing.
    code, slug, title = "auth.invalid_credentials", "invalid-credentials", "Email or password is incorrect"


class InvalidRefreshToken(Unauthorized):
    # Unknown, expired, already used, or its session ended. The client must sign in again.
    code, slug, title = "auth.invalid_refresh_token", "invalid-refresh-token", "Session expired, sign in again"


class AccountLocked(TooManyRequests):
    code, slug, title = "auth.account_locked", "account-locked", "Too many failed attempts, try again later"


class RateLimited(TooManyRequests):
    code, slug, title = "auth.rate_limited", "rate-limited", "Too many requests, slow down"


class AccountSuspended(Forbidden):
    code, slug, title = "auth.account_suspended", "account-suspended", "This account is suspended"


class InvalidEmail(Unprocessable):
    code, slug, title = "auth.invalid_email", "invalid-email", "Enter a valid email address"


class WeakPassword(Unprocessable):
    code, slug, title = "auth.weak_password", "weak-password", "Password does not meet the rules"


class InvalidDisplayName(Unprocessable):
    code, slug, title = "auth.invalid_display_name", "invalid-display-name", "Enter a name of 1 to 120 characters"
