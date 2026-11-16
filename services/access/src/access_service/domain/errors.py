"""Errors of the access domain. Each maps to one HTTP status and one stable machine `code`."""

from common.errors import Conflict, Forbidden, Gone, NotFound, Unprocessable


class WorkspaceNotFound(NotFound):
    # Also the answer for "it exists but you are not a member": never confirm a workspace to outsiders.
    code, slug, title = "workspace.not_found", "workspace-not-found", "Workspace not found"


class WorkspaceIdTaken(Conflict):
    code, slug, title = "workspace.id_taken", "workspace-id-taken", "A workspace with this id already exists"


class WorkspaceSlugTaken(Conflict):
    code, slug, title = "workspace.slug_taken", "workspace-slug-taken", "This workspace address is already in use"


class InvalidWorkspace(Unprocessable):
    code, slug, title = "workspace.invalid", "workspace-invalid", "Workspace name or address is not valid"


class MissingCapability(Forbidden):
    code, slug, title = "access.missing_capability", "missing-capability", "Your role does not allow this"


class InviteGone(Gone):
    # One answer for unknown, expired, revoked and already-used links: the link tells an outsider nothing.
    code, slug, title = "invite.gone", "invite-gone", "This invite link is no longer valid"


class InviteEmailMismatch(Forbidden):
    code, slug, title = (
        "invite.email_mismatch",
        "invite-email-mismatch",
        "This invite was sent to a different email address",
    )
