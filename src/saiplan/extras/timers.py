"""Timer engine (extras, spec 11). Qt-free — the UI only feeds it `tick()`
periodically; the engine never depends on the timers tab being visible.

Two kinds (audited FastPrompter split, adapted):

- DEADLINE timer: absolute wall-clock target persisted as ISO UTC. Survives
  restart, sleep, wake, clock-aware. Repeat advances into the future; snooze
  only ever moves the target later.
- ELAPSED timer (stopwatch + Pomodoro): driven by monotonic time during the
  process lifetime; run state does NOT survive restart (restoring a "running"
  stopwatch across a crash would be a lie). On restart they come back idle,
  with accumulated elapsed kept.

A completion fires exactly once per arm: the engine remembers in-memory that a
timer already fired, so any number of UI refresh ticks never duplicate the
event. After a restart an overdue deadline timer re-arms once — the user may
not have seen the notification yet.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_logger = logging.getLogger("saiplan.timers")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str):
    """Parse ISO-8601 UTC -> epoch seconds. Returns None for anything unusable
    (corrupt entries are skipped, never fatal)."""
    try:
        # Python 3.11's fromisoformat accepts a trailing 'Z' directly
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def _monotonic() -> float:
    return time.monotonic()


class TimerError(Exception):
    pass


@dataclass
class DeadlineTimer:
    target_at: str  # ISO UTC, absolute wall clock
    label: str = "timer"
    repeat_every_s: float | None = None
    snoozed_until: str | None = None
    tid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_record(self) -> dict:
        rec = {
            "kind": "deadline",
            "tid": self.tid,
            "label": self.label,
            "target_at": self.target_at,
        }
        if self.repeat_every_s:
            rec["repeat_every_s"] = self.repeat_every_s
        if self.snoozed_until:
            rec["snoozed_until"] = self.snoozed_until
        return rec

    @staticmethod
    def from_record(rec: dict) -> DeadlineTimer | None:
        if rec.get("kind") != "deadline" or not rec.get("target_at"):
            return None
        if parse_iso(rec["target_at"]) is None:
            return None
        return DeadlineTimer(
            tid=rec.get("tid") or uuid.uuid4().hex[:12],
            label=rec.get("label", "timer"),
            target_at=rec["target_at"],
            repeat_every_s=rec.get("repeat_every_s"),
            snoozed_until=rec.get("snoozed_until"),
        )


class Stopwatch:
    """Elapsed-time stopwatch. Pause accumulates; restart -> idle (truthful)."""

    def __init__(self):
        self.accumulated_s = 0.0
        self._started_mono: float | None = None
        self._pause_started: float | None = None

    @property
    def running(self) -> bool:
        return self._started_mono is not None

    def start(self) -> None:
        if self._started_mono is not None:
            return
        self._started_mono = _monotonic()
        self._pause_started = None

    def pause(self) -> None:
        if self._started_mono is None:
            return
        self.accumulated_s += _monotonic() - self._started_mono
        self._started_mono = None
        self._pause_started = _monotonic()

    def resume(self) -> None:
        self.start()

    def reset(self) -> None:
        self.accumulated_s = 0.0
        self._started_mono = None
        self._pause_started = None

    def elapsed(self) -> float:
        base = self.accumulated_s
        if self._started_mono is not None:
            base += _monotonic() - self._started_mono
        return base


POMODORO_PHASES = ("work", "short_break", "long_break")


class Pomodoro:
    """work -> short_break -> work -> ... ; every 4th break is long.
    Elapsed-driven; run state does not survive restart (idle)."""

    WORK_S = 25 * 60
    SHORT_BREAK_S = 5 * 60
    LONG_BREAK_S = 15 * 60
    LONG_EVERY = 4

    def __init__(
        self, work_s: float = WORK_S, short_s: float = SHORT_BREAK_S, long_s: float = LONG_BREAK_S
    ):
        self.work_s, self.short_s, self.long_s = work_s, short_s, long_s
        self.phase = "idle"
        self.completed_work = 0
        self._started_mono: float | None = None
        self._paused_at: float | None = None
        self.alarm_pending = False
        self._phase_duration = self.work_s

    @property
    def running(self) -> bool:
        return self._started_mono is not None and self.phase != "idle"

    def start_work(self) -> None:
        self.phase = "work"
        self._phase_duration = self.work_s
        self._started_mono = _monotonic()
        self.alarm_pending = False

    def pause(self) -> None:
        if self.running and self._paused_at is None:
            self._paused_at = _monotonic()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._started_mono += _monotonic() - self._paused_at
            self._paused_at = None

    def skip(self) -> None:
        self._advance_phase()

    def phase_remaining(self) -> float:
        if self._started_mono is None or self.phase == "idle":
            return self._phase_duration
        elapsed = _monotonic() - self._started_mono
        if self._paused_at is not None:
            elapsed -= _monotonic() - self._paused_at
        return max(0.0, self._phase_duration - elapsed)

    def tick(self) -> bool:
        """Returns True when the current phase finished (once per finish)."""
        if self.phase == "idle" or self._started_mono is None:
            return False
        if self.phase_remaining() > 0:
            return False
        if self.alarm_pending:
            return False
        self.alarm_pending = True
        return True

    def ack_alarm(self) -> None:
        """User acknowledged the phase-end -> advance to the next phase."""
        self._advance_phase()

    def _advance_phase(self) -> None:
        if self.phase == "work":
            self.completed_work += 1
            if self.completed_work % self.LONG_EVERY == 0:
                self.phase = "long_break"
                self._phase_duration = self.long_s
            else:
                self.phase = "short_break"
                self._phase_duration = self.short_s
        elif self.phase in ("short_break", "long_break"):
            self.phase = "work"
            self._phase_duration = self.work_s
        self._started_mono = _monotonic()
        self.alarm_pending = False


class TicketTimer:
    """Records focused work sessions on a ticket into TIMELOG.jsonl.

    Authority is persisted wall-clock UTC; monotonic is only used for live
    duration while the process runs.

    A session is persisted IMMEDIATELY on start (crash marker) as an open
    record carrying a session_id. On stop a closed record with the same
    session_id is appended; on load the pair is collapsed into one session.
    A session left open by a crash is closed at the next load with a
    `recovered` flag — nothing is silently lost, nothing is double-counted.
    """

    def __init__(self, timelog_path: Path):
        self.path = Path(timelog_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._open: dict[str, dict] = {}

    def start(self, ticket_id: str) -> str:
        rec = {
            "kind": "ticket",
            "session_id": uuid.uuid4().hex[:12],
            "ticket_id": ticket_id,
            "started_at": _now_iso(),
        }
        self._open[rec["session_id"]] = {**rec, "started_mono": _monotonic()}
        self._append(rec)
        return rec["session_id"]

    def stop(self, session_id: str) -> dict | None:
        live = self._open.pop(session_id, None)
        if live is None:
            return None
        rec = {
            "session_id": session_id,
            "ticket_id": live["ticket_id"],
            "started_at": live["started_at"],
            "ended_at": _now_iso(),
            "duration_s": round(max(0.0, _monotonic() - live["started_mono"]), 2),
            "kind": "ticket",
        }
        self._append(rec)
        return rec

    def stop_ticket(self, ticket_id: str) -> dict | None:
        """Stop the running session for a ticket (if any)."""
        for session_id, live in list(self._open.items()):
            if live["ticket_id"] == ticket_id:
                return self.stop(session_id)
        return None

    def toggle(self, ticket_id: str) -> bool:
        """Start if idle, stop if running. Returns True when now running."""
        if self.is_running(ticket_id):
            self.stop_ticket(ticket_id)
            return False
        self.start(ticket_id)
        return True

    def running(self) -> list[str]:
        return [live["ticket_id"] for live in self._open.values()]

    def is_running(self, ticket_id: str) -> bool:
        return any(live["ticket_id"] == ticket_id for live in self._open.values())

    def started_at(self, ticket_id: str) -> str | None:
        for live in self._open.values():
            if live["ticket_id"] == ticket_id:
                return live["started_at"]
        return None

    def load(self) -> list[dict]:
        """Read TIMELOG.jsonl, collapsing open/closed pairs into sessions and
        recovering sessions left open by a crash."""
        sessions: list[dict] = []
        closed_ids: set[str] = set()
        opens: dict[str, dict] = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = rec.get("session_id")
            if not sid or rec.get("kind") != "ticket":
                continue
            if rec.get("ended_at"):
                sessions.append(rec)
                closed_ids.add(sid)
            else:
                opens[sid] = rec
        for sid, rec in opens.items():
            if sid in closed_ids:
                continue  # already closed; the open marker is just history
            rec = dict(rec)
            rec["ended_at"] = _now_iso()
            rec["duration_s"] = 0.0
            rec["recovered"] = True
            self._append(rec)
            sessions.append(rec)
        sessions.sort(key=lambda r: r.get("started_at", ""))
        return sessions

    def sessions_for(self, ticket_id: str) -> list[dict]:
        return [s for s in self.load() if s.get("ticket_id") == ticket_id]

    def total_for(self, ticket_id: str) -> float:
        return sum(float(s.get("duration_s", 0)) for s in self.sessions_for(ticket_id))

    def _append(self, rec: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class TimerEngine:
    """Owns deadline timers + stopwatch + pomodoro + ticket timers.

    `on_fire` callback receives the DeadlineTimer that finished. `tick()` is
    cheap and safe to call from any number of UI timers.
    """

    def __init__(self, timers_path: Path | None = None, on_fire=None, on_pomodoro_phase=None):
        self.path = Path(timers_path) if timers_path else None
        self.on_fire = on_fire
        self.on_pomodoro_phase = on_pomodoro_phase
        self.deadline: dict[str, DeadlineTimer] = {}
        self.stopwatch = Stopwatch()
        self.pomodoro = Pomodoro()
        self._fired: set[str] = set()
        if self.path is not None:
            self.load()

    def load(self) -> None:
        """Load persisted deadline timers; corrupt entries skipped."""
        if self.path is None or not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            timer = DeadlineTimer.from_record(rec)
            if timer is not None:
                self.deadline[timer.tid] = timer

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(t.to_record()) + "\n" for t in self.deadline.values())
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def add_deadline(
        self, target_iso: str, label: str = "timer", repeat_every_s: float | None = None
    ) -> DeadlineTimer:
        if parse_iso(target_iso) is None:
            raise TimerError(f"bad target timestamp {target_iso!r}")
        timer = DeadlineTimer(target_at=target_iso, label=label, repeat_every_s=repeat_every_s)
        self.deadline[timer.tid] = timer
        self.save()
        return timer

    def snooze(self, tid: str, seconds: float) -> None:
        timer = self.deadline.get(tid)
        if timer is None:
            return
        base = parse_iso(timer.target_at) or time.time()
        target = max(time.time(), base) + max(1.0, seconds)
        timer.snoozed_until = datetime.fromtimestamp(target, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        timer.target_at = timer.snoozed_until
        self._fired.discard(tid)
        self.save()

    def cancel(self, tid: str) -> None:
        self.deadline.pop(tid, None)
        self.save()

    def tick(self, now: float | None = None) -> list[DeadlineTimer]:
        """Advance all timers. Returns timers that finished NOW (once each)."""
        now = now if now is not None else time.time()
        fired: list[DeadlineTimer] = []
        for tid, timer in list(self.deadline.items()):
            target = parse_iso(timer.target_at)
            if target is None:
                continue
            if now >= target and tid not in self._fired:
                self._fired.add(tid)
                fired.append(timer)
                if timer.repeat_every_s:
                    next_target = target + timer.repeat_every_s
                    while next_target <= now:
                        next_target += timer.repeat_every_s
                    timer.target_at = datetime.fromtimestamp(next_target, tz=UTC).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    timer.snoozed_until = None
                else:
                    self.deadline.pop(tid)
                self.save()
        for timer in fired:
            if self.on_fire is not None:
                try:
                    self.on_fire(timer)
                except Exception as e:  # noqa: BLE001
                    _logger.warning("on_fire callback failed: %s", e)
        return fired

    def tick_pomodoro(self) -> bool:
        """Advance the pomodoro; returns True when a phase just finished."""
        finished = self.pomodoro.tick()
        if finished and self.on_pomodoro_phase is not None:
            try:
                self.on_pomodoro_phase(self.pomodoro.phase)
            except Exception as e:  # noqa: BLE001
                _logger.warning("on_pomodoro_phase callback failed: %s", e)
        return finished
