"""Tests for SocialEventLog."""

from datetime import UTC, datetime, timedelta

import pytest

from annie.social_graph.event_log import SocialEventLog
from annie.social_graph.models import EventVisibility, SocialEvent


@pytest.fixture
def log() -> SocialEventLog:
    return SocialEventLog()


@pytest.fixture
def seeded_log() -> SocialEventLog:
    log = SocialEventLog()
    now = datetime.now(UTC)
    log.load_preset_events([
        SocialEvent(
            actor="Gareth", target="Carpenter", action="accused",
            description="Gareth accused carpenter of stealing customers",
            witnesses=["Elder"], visibility=EventVisibility.WITNESSED,
            timestamp=now - timedelta(days=7),
        ),
        SocialEvent(
            actor="Lina", action="discovered",
            description="Lina discovered tampered trade goods",
            visibility=EventVisibility.PRIVATE,
            timestamp=now - timedelta(days=3),
        ),
        SocialEvent(
            actor="Merchant", action="announced",
            description="Traveling merchant announced praise and tampering rumors",
            visibility=EventVisibility.PUBLIC,
            timestamp=now,
        ),
    ])
    return log


class TestAppend:
    def test_append_returns_id(self, log):
        evt = SocialEvent(actor="A", action="x", description="x")
        eid = log.append(evt)
        assert eid == evt.id

    def test_len(self, log):
        assert len(log) == 0
        log.append(SocialEvent(actor="A", action="x", description="x"))
        assert len(log) == 1

    def test_load_preset(self, seeded_log):
        assert len(seeded_log) == 3


class TestGet:
    def test_get_by_id(self, seeded_log):
        events = seeded_log.all_events()
        found = seeded_log.get(events[0].id)
        assert found is not None
        assert found.actor == "Gareth"

    def test_get_missing(self, log):
        assert log.get("nonexistent") is None


class TestQueryByActor:
    def test_by_actor(self, seeded_log):
        results = seeded_log.get_by_actor("Gareth")
        assert len(results) == 1
        assert results[0].action == "accused"

    def test_by_actor_empty(self, seeded_log):
        assert seeded_log.get_by_actor("Nobody") == []


class TestQueryByTarget:
    def test_by_target(self, seeded_log):
        results = seeded_log.get_by_target("Carpenter")
        assert len(results) == 1

    def test_by_target_empty(self, seeded_log):
        assert seeded_log.get_by_target("Nobody") == []


class TestQueryByTimerange:
    def test_timerange(self, seeded_log):
        now = datetime.now(UTC)
        results = seeded_log.get_by_timerange(
            now - timedelta(days=5), now - timedelta(days=1),
        )
        assert len(results) == 1
        assert results[0].actor == "Lina"

    def test_timerange_all(self, seeded_log):
        results = seeded_log.get_by_timerange(
            datetime.min.replace(tzinfo=UTC), datetime.max.replace(tzinfo=UTC),
        )
        assert len(results) == 3


class TestGetRecent:
    def test_recent(self, seeded_log):
        results = seeded_log.get_recent(2)
        assert len(results) == 2
        assert results[-1].actor == "Merchant"

    def test_recent_more_than_available(self, seeded_log):
        results = seeded_log.get_recent(100)
        assert len(results) == 3


class TestQueryByVisibility:
    def test_public(self, seeded_log):
        results = seeded_log.get_by_visibility(EventVisibility.PUBLIC)
        assert len(results) == 1
        assert results[0].actor == "Merchant"

    def test_private(self, seeded_log):
        results = seeded_log.get_by_visibility(EventVisibility.PRIVATE)
        assert len(results) == 1
        assert results[0].actor == "Lina"

    def test_witnessed(self, seeded_log):
        results = seeded_log.get_by_visibility(EventVisibility.WITNESSED)
        assert len(results) == 1

    def test_secret_empty(self, seeded_log):
        assert seeded_log.get_by_visibility(EventVisibility.SECRET) == []


class TestAllEvents:
    def test_insertion_order(self, seeded_log):
        events = seeded_log.all_events()
        assert events[0].actor == "Gareth"
        assert events[1].actor == "Lina"
        assert events[2].actor == "Merchant"

    def test_returns_copy(self, seeded_log):
        events = seeded_log.all_events()
        events.clear()
        assert len(seeded_log) == 3
