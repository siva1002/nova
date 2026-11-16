"""Use cases with fakes. These are the demo-script rules (step 6) tested in milliseconds."""

from datetime import timedelta

import pytest
from time_fakes import NOW, TASK, USER_A, USER_B, FakeClock, FakePerms, FakeTasks, make_ctx

from common.errors import Forbidden, NotFound, VersionConflict
from time_service.domain.entry_rules import EntryInFuture
from time_service.domain.models import EntryChanges, NewEntry
from time_service.usecases.create_entry import create_entry
from time_service.usecases.update_entry import update_entry

HOUR = 3_600_000


def new(duration_ms=2 * HOUR + HOUR // 2, **kw):
    return NewEntry(task_id=kw.pop("task_id", TASK), started_at=NOW - timedelta(hours=4), duration_ms=duration_ms, **kw)


async def log(repo, events, user=USER_B, cmd=None, tasks=None):
    return await create_entry(
        make_ctx(user),
        cmd or new(),
        repo=repo,
        tasks=tasks or FakeTasks(),
        perms=FakePerms(),
        events=events,
        clock=FakeClock(),
    )


async def test_member_logs_2h30_and_it_is_stored_with_an_event(repo, events):
    e = await log(repo, events)
    assert e.duration_ms == 9_000_000 and e.source == "manual" and e.version == 1
    assert e.ended_at == e.started_at + timedelta(hours=2, minutes=30)
    assert e.user_id == USER_B and repo.rows[e.id] == e
    assert events.added == [("time.entry.created", e.id, 1)]


async def test_cannot_log_in_the_future(repo, events):
    cmd = NewEntry(task_id=TASK, started_at=NOW, duration_ms=HOUR)
    with pytest.raises(EntryInFuture):
        await log(repo, events, cmd=cmd)
    assert repo.rows == {} and events.added == []  # nothing written


async def test_cannot_log_on_a_task_you_cannot_see(repo, events):
    with pytest.raises(NotFound):
        await log(repo, events, tasks=FakeTasks(visible=False))
    assert repo.rows == {}


async def edit(repo, events, entry, user, changes, admins=None):
    return await update_entry(
        make_ctx(user), entry.id, changes, repo=repo, perms=FakePerms(admins), events=events, clock=FakeClock()
    )


async def test_owner_of_entry_edits_it_2h30_to_3h(repo, events):
    e = await log(repo, events)
    out = await edit(repo, events, e, USER_B, EntryChanges(version=1, duration_ms=3 * HOUR))
    assert out.duration_ms == 3 * HOUR and out.version == 2
    assert events.added[-1][0] == "time.entry.updated"


async def test_member_cannot_edit_someone_elses_entry(repo, events):
    e = await log(repo, events, user=USER_A)
    with pytest.raises(Forbidden):
        await edit(repo, events, e, USER_B, EntryChanges(version=1, duration_ms=HOUR))


async def test_admin_can_edit_someone_elses_entry(repo, events):
    e = await log(repo, events, user=USER_B)
    out = await edit(repo, events, e, USER_A, EntryChanges(version=1, billable=True), admins={USER_A})
    assert out.billable is True


async def test_stale_version_gets_409_with_current_version(repo, events):
    e = await log(repo, events)
    await edit(repo, events, e, USER_B, EntryChanges(version=1, description="first"))
    with pytest.raises(VersionConflict) as err:
        await edit(repo, events, e, USER_B, EntryChanges(version=1, description="second"))  # still sends v1
    assert err.value.extra["current_version"] == 2
