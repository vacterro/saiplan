"""Timers (spec 11/19): deadline, stopwatch, pomodoro, ticket timers,
restart recovery, idempotent completion, sleep/wake, missing sound isolation.
"""

import json
import time
from datetime import UTC

import pytest

from saiplan.extras.timers import (
    Pomodoro,
    Stopwatch,
    TicketTimer,
    TimerEngine,
    TimerError,
    parse_iso,
)

SRC_SOUNDS = None


def _iso(seconds_from_now: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(time.time() + seconds_from_now, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def test_parse_iso_roundtrip():
    iso = _iso(60)
    ts = parse_iso(iso)
    assert ts is not None
    assert parse_iso("garbage") is None
    assert parse_iso("") is None
    assert parse_iso(None) is None


def test_deadline_fires_once_per_arm(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    fired = []
    engine.on_fire = lambda t: fired.append(t.label)
    engine.add_deadline(_iso(0.05), label="ding")
    # many ticks after expiry must not duplicate the event
    for _ in range(10):
        engine.tick(now=time.time() + 1)
    assert fired == ["ding"]
    assert engine.deadline == {}  # one-shot removed after firing


def test_deadline_persists_across_restart(tmp_path):
    p = tmp_path / "t.jsonl"
    e1 = TimerEngine(p)
    t = e1.add_deadline(_iso(3600), label="later")
    e2 = TimerEngine(p)  # "restart"
    assert t.tid in e2.deadline
    assert e2.deadline[t.tid].label == "later"


def test_overdue_deadline_arms_after_restart(tmp_path):
    p = tmp_path / "t.jsonl"
    e1 = TimerEngine(p)
    e1.add_deadline(_iso(0), label="was due")  # persisted, never ticked
    e2 = TimerEngine(p)  # restart; timer overdue -> arms once
    fired = []
    e2.on_fire = lambda t: fired.append(t.label)
    e2.tick(now=time.time())
    assert fired == ["was due"]


def test_deadline_repeat_advances_into_future(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    engine.add_deadline(_iso(0), label="every", repeat_every_s=10)
    now = time.time() + 25
    engine.tick(now=now)
    timer = next(iter(engine.deadline.values()))
    remaining = parse_iso(timer.target_at) - now
    # ISO timestamps are second-granular: next fire is one period away,
    # within a ±1s truncation window
    assert 4.0 <= remaining <= 11.0


def test_snooze_moves_target_later(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    engine.add_deadline(_iso(0), label="snoozable")
    engine.tick(now=time.time())
    assert engine.deadline == {}  # already fired and removed
    t2 = engine.add_deadline(_iso(0.05), label="s2")
    engine.snooze(t2.tid, 300)
    ts = parse_iso(engine.deadline[t2.tid].target_at)
    assert ts > time.time() + 240


def test_snooze_suppresses_fire_until_target(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    t = engine.add_deadline(_iso(0.05), label="s3")
    engine.snooze(t.tid, 3600)
    fired = []
    engine.on_fire = lambda x: fired.append(x.tid)
    engine.tick(now=time.time() + 600)
    assert fired == []
    engine.tick(now=time.time() + 3601)
    assert fired == [t.tid]


def test_corrupt_timer_entry_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"kind":"deadline","tid":"bad","target_at":"not a date"}\nnot json\n', encoding="utf-8"
    )
    engine = TimerEngine(p)
    assert engine.deadline == {}
    assert engine.tick() == []


def test_stopwatch_pause_resume_reset():
    sw = Stopwatch()
    sw.start()
    time.sleep(0.05)
    sw.pause()
    t1 = sw.elapsed()
    assert 0.03 < t1
    time.sleep(0.05)
    assert abs(sw.elapsed() - t1) < 0.01  # paused: no drift
    sw.resume()
    time.sleep(0.05)
    assert sw.elapsed() > t1 + 0.03
    sw.reset()
    assert sw.elapsed() == 0.0
    assert not sw.running


def test_pomodoro_phases_and_single_alarm():
    p = Pomodoro(work_s=0.03, short_s=0.02, long_s=0.02)
    p.start_work()
    time.sleep(0.05)
    # tick until finish; alarm must fire exactly once
    finished = [p.tick() for _ in range(5)]
    assert finished.count(True) == 1
    p.ack_alarm()
    assert p.phase == "short_break"
    time.sleep(0.05)
    assert p.tick() is True
    p.ack_alarm()
    assert p.phase == "work"


def test_pomodoro_long_break_every_four():
    p = Pomodoro(work_s=0.001, short_s=0.001, long_s=0.001)
    phases = []
    for i in range(8):
        p.start_work()
        p._advance_phase()
        phases.append(p.phase)
    assert phases[3] == "long_break"
    assert phases[7] == "long_break"


def test_pomodoro_pause_holds_remaining():
    p = Pomodoro(work_s=60)
    p.start_work()
    time.sleep(0.02)
    p.pause()
    rem1 = p.phase_remaining()
    time.sleep(0.05)
    rem2 = p.phase_remaining()
    assert abs(rem1 - rem2) < 0.01
    p.resume()
    time.sleep(0.02)
    assert p.phase_remaining() < rem1


def test_ticket_timer_records_sessions(tmp_path):
    tt = TicketTimer(tmp_path / "TIMELOG.jsonl")
    sid = tt.start("S-001")
    time.sleep(0.02)
    rec = tt.stop(sid)
    assert rec["ticket_id"] == "S-001"
    assert rec["ended_at"]
    assert rec["duration_s"] > 0
    assert tt.total_for("S-001") > 0
    assert len(tt.sessions_for("S-001")) == 1  # open/close collapsed to one


def test_ticket_timer_toggle(tmp_path):
    tt = TicketTimer(tmp_path / "TIMELOG.jsonl")
    assert tt.toggle("S-002") is True
    assert tt.is_running("S-002")
    assert tt.toggle("S-002") is False
    assert not tt.is_running("S-002")
    assert len(tt.sessions_for("S-002")) == 1


def test_ticket_timer_crash_recovery(tmp_path):
    p = tmp_path / "TIMELOG.jsonl"
    tt1 = TicketTimer(p)
    tt1.start("S-003")
    # crash: never stopped
    tt2 = TicketTimer(p)
    sessions = tt2.load()
    recovered = [s for s in sessions if s.get("recovered")]
    assert len(recovered) == 1
    assert recovered[0]["ticket_id"] == "S-003"
    # the recovered session is now closed: reload gives one clean session
    assert len(tt2.sessions_for("S-003")) == 1


def test_ticket_timer_persists_start_immediately(tmp_path):
    p = tmp_path / "TIMELOG.jsonl"
    tt = TicketTimer(p)
    tt.start("S-004")
    raw = p.read_text(encoding="utf-8")
    assert "S-004" in raw
    tt.stop_ticket("S-004")


def test_deadline_bad_target_refused(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    with pytest.raises(TimerError):
        engine.add_deadline("not-a-timestamp")


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf"), -float("inf"), True, "10"])
def test_repeat_invalid_rejected(tmp_path, bad):
    engine = TimerEngine(tmp_path / "t.jsonl")
    with pytest.raises(TimerError):
        engine.add_deadline(_iso(60), label="x", repeat_every_s=bad)


def test_repeat_zero_is_explicit_one_shot(tmp_path):
    engine = TimerEngine(tmp_path / "t.jsonl")
    with pytest.raises(TimerError):
        engine.add_deadline(_iso(60), label="x", repeat_every_s=0)


def test_malformed_persisted_repeat_skipped(tmp_path):
    """A corrupt persisted repeat must be skipped safely, never a hang."""
    p = tmp_path / "t.jsonl"
    good = _iso(60)
    p.write_text(
        json.dumps(
            {
                "kind": "deadline",
                "tid": "a",
                "label": "bad",
                "target_at": good,
                "repeat_every_s": -1,
            }
        )
        + "\n"
        + json.dumps(
            {
                "kind": "deadline",
                "tid": "b",
                "label": "bad2",
                "target_at": good,
                "repeat_every_s": 0,
            }
        )
        + "\n"
        + json.dumps(
            {"kind": "deadline", "tid": "c", "label": "ok", "target_at": good, "repeat_every_s": 10}
        )
        + "\n",
        encoding="utf-8",
    )
    engine = TimerEngine(p)
    assert "b" not in engine.deadline  # invalid repeats dropped
    assert "c" in engine.deadline
    # tick cannot hang on any loaded timer
    fired = engine.tick(now=time.time() + 3600)
    assert len(fired) == 1


def test_timer_save_is_atomic(tmp_path):
    p = tmp_path / "t.jsonl"
    engine = TimerEngine(p)
    engine.add_deadline(_iso(60), label="a")
    engine.add_deadline(_iso(120), label="b")
    engine.save()
    # no temp litter, file is coherent JSONL
    assert list(tmp_path.glob("*.tmp-*")) == []
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines if l.strip()]) == 2


def test_stopwatch_fractional_display():
    from saiplan.ui.dialogs import TimerPanel

    # 65.4s -> 00:01:05.4 (fraction preserved, not .0)
    assert TimerPanel._fmt(65.4, ms=True) == "00:01:05.4"
    assert TimerPanel._fmt(1.5, ms=True) == "00:00:01.5"
    assert TimerPanel._fmt(0.0, ms=True) == "00:00:00.0"
    # 65.4s without ms -> whole seconds only
    assert TimerPanel._fmt(65.4) == "00:01:05"


def test_ticket_timer_recovery_uses_wall_clock(tmp_path):
    """A crashed session's duration is estimated from the persisted wall clock,
    never silently zeroed."""
    from datetime import datetime, timedelta

    p = tmp_path / "TIMELOG.jsonl"
    tt = TicketTimer(p)
    tt.start("S-100")
    # simulate a crash 10 minutes later: rewrite the open marker's started_at
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    started = datetime.fromisoformat(rec["started_at"])  # 3.11 handles 'Z'
    rec["started_at"] = (started - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines[-1] = json.dumps(rec)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tt2 = TicketTimer(p)
    sessions = tt2.load()
    recovered = [s for s in sessions if s.get("recovered")]
    assert len(recovered) == 1
    assert recovered[0]["duration_s"] > 500  # ~10 minutes, not zero
    assert recovered[0]["duration_source"] == "wall_clock_estimate"


def test_missing_sound_does_not_break_timer(tmp_path):
    """A missing sound file is a no-op on fire — the timer still completes."""
    from saiplan.extras.sounds import SoundLibrary, SoundPlayer, SoundRegistry

    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    (sounds_dir / "ok.wav").write_bytes(b"RIFF fake")
    lib = SoundLibrary(sounds_dir)
    reg = SoundRegistry(
        lib, {"timer_finished": {"file": "missing.wav", "enabled": True, "volume": 1.0}}
    )
    player = SoundPlayer()
    engine = TimerEngine(tmp_path / "t.jsonl")
    fired = []

    def _fire(timer):
        fired.append(timer.label)
        path = reg.file_for("timer_finished")
        if path is not None:  # missing -> None -> nothing played, no crash
            player.play_file(path)

    engine.on_fire = _fire
    engine.add_deadline(_iso(0), label="x")
    engine.tick(now=time.time())
    assert fired == ["x"]
