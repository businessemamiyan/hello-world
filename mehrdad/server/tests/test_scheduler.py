import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.config import Config
from app.memory import Memory
from app.scheduler import Scheduler


class FakeBot:
    def __init__(self):
        self.prompted = []

    async def prompt_habit_checkin(self, chat_id, habit):
        self.prompted.append((chat_id, habit["id"]))


@pytest.fixture
def setup(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    bot = FakeBot()
    cfg = Config(habit_checkin_time="21:00")
    sched = Scheduler(bot, mem, cfg)
    return mem, bot, cfg, sched


@pytest.mark.asyncio
async def test_no_fire_without_owner(setup, monkeypatch):
    mem, bot, cfg, sched = setup
    import app.scheduler as sch_mod

    class FakeNow:
        def strftime(self, fmt):
            return "21:00"

        def date(self):
            class D:
                def isoformat(self):
                    return "2026-01-01"
            return D()

    monkeypatch.setattr(sch_mod, "now_tehran", lambda: FakeNow())
    await mem.add_habit("مطالعه")
    await sched.maybe_fire()
    assert bot.prompted == []


@pytest.mark.asyncio
async def test_fires_for_pending_habits_at_configured_time(setup, monkeypatch):
    mem, bot, cfg, sched = setup
    import app.scheduler as sch_mod

    class FakeNow:
        def strftime(self, fmt):
            return "21:00"

        def date(self):
            class D:
                def isoformat(self):
                    return "2026-01-01"
            return D()

    monkeypatch.setattr(sch_mod, "now_tehran", lambda: FakeNow())
    await mem.set_owner(42)
    hid = await mem.add_habit("مطالعه")
    await sched.maybe_fire()
    assert bot.prompted == [(42, hid)]


@pytest.mark.asyncio
async def test_does_not_fire_at_wrong_time(setup, monkeypatch):
    mem, bot, cfg, sched = setup
    import app.scheduler as sch_mod

    class FakeNow:
        def strftime(self, fmt):
            return "10:00"

        def date(self):
            class D:
                def isoformat(self):
                    return "2026-01-01"
            return D()

    monkeypatch.setattr(sch_mod, "now_tehran", lambda: FakeNow())
    await mem.set_owner(42)
    await mem.add_habit("مطالعه")
    await sched.maybe_fire()
    assert bot.prompted == []


@pytest.mark.asyncio
async def test_does_not_fire_twice_same_day(setup, monkeypatch):
    mem, bot, cfg, sched = setup
    import app.scheduler as sch_mod

    class FakeNow:
        def strftime(self, fmt):
            return "21:00"

        def date(self):
            class D:
                def isoformat(self):
                    return "2026-01-01"
            return D()

    monkeypatch.setattr(sch_mod, "now_tehran", lambda: FakeNow())
    await mem.set_owner(42)
    await mem.add_habit("مطالعه")
    await sched.maybe_fire()
    await sched.maybe_fire()
    assert len(bot.prompted) == 1


@pytest.mark.asyncio
async def test_skips_habits_already_checked_in_today(setup, monkeypatch):
    mem, bot, cfg, sched = setup
    import app.scheduler as sch_mod
    from app.memory import today_str

    class FakeNow:
        def strftime(self, fmt):
            return "21:00"

        def date(self):
            class D:
                def isoformat(self):
                    return today_str()
            return D()

    monkeypatch.setattr(sch_mod, "now_tehran", lambda: FakeNow())
    await mem.set_owner(42)
    hid = await mem.add_habit("مطالعه")
    await mem.checkin_habit(hid, True, date=today_str())
    await sched.maybe_fire()
    assert bot.prompted == []
