"""Persistent local goals, milestones and focus-timer storage for Veltrix.

All timestamps are UTC Unix seconds. Calendar dates are interpreted in the
user's configured IANA timezone. Focus intervals are stored separately so
sessions that cross midnight are allocated correctly to each local day.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


class FocusError(ValueError):
    """Raised for invalid goal or timer operations."""


def format_duration(seconds: float | int) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class FocusStore:
    """SQLite-backed focus workspace repository with restart-safe timers."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        timezone_name: str = "Africa/Nairobi",
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.zone = ZoneInfo(timezone_name)
        except Exception as exc:
            raise FocusError(f"Unknown IANA timezone: {timezone_name}") from exc
        self._now_fn = now_fn or time.time
        self._initialize()

    def _now(self) -> float:
        return float(self._now_fn())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'Personal',
                    start_date TEXT NOT NULL,
                    deadline_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'not_started',
                    manual_progress REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_goals_deadline ON goals(deadline_date);

                CREATE TABLE IF NOT EXISTS milestones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_milestones_goal ON milestones(goal_id, sort_order, id);

                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL CHECK(mode IN ('stopwatch', 'countdown')),
                    label TEXT NOT NULL DEFAULT 'Focus session',
                    target_seconds INTEGER,
                    remaining_seconds INTEGER,
                    deadline_at REAL,
                    status TEXT NOT NULL CHECK(status IN ('running', 'paused', 'completed', 'stopped')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_focus_sessions_created ON focus_sessions(created_at DESC);

                CREATE TABLE IF NOT EXISTS focus_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
                    start_at REAL NOT NULL,
                    end_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_focus_segments_range ON focus_segments(start_at, end_at);

                CREATE TABLE IF NOT EXISTS focus_state (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    active_session_id INTEGER REFERENCES focus_sessions(id)
                );
                INSERT OR IGNORE INTO focus_state(singleton_id, active_session_id) VALUES (1, NULL);
                """
            )

    @staticmethod
    def _validate_iso_date(value: str, field_name: str) -> date:
        try:
            parsed = date.fromisoformat(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise FocusError(f"{field_name} must use YYYY-MM-DD format.") from exc
        return parsed

    def create_goal(
        self,
        title: str,
        *,
        description: str = "",
        category: str = "Personal",
        start_date: str,
        deadline_date: str,
        status: str = "not_started",
        progress: float = 0,
    ) -> int:
        title = str(title).strip()
        if not title:
            raise FocusError("Goal title cannot be empty.")
        start = self._validate_iso_date(start_date, "Start date")
        deadline = self._validate_iso_date(deadline_date, "Deadline")
        if deadline < start:
            raise FocusError("Deadline cannot be earlier than the start date.")
        if status not in {"not_started", "in_progress", "completed", "archived"}:
            raise FocusError("Invalid goal status.")
        progress_value = float(progress)
        if not 0 <= progress_value <= 100:
            raise FocusError("Progress must be between 0 and 100.")
        now = self._now()
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO goals(title, description, category, start_date, deadline_date,
                   status, manual_progress, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, str(description).strip(), str(category).strip() or "Personal", start.isoformat(),
                 deadline.isoformat(), status, progress_value, now, now),
            )
            return int(cursor.lastrowid)

    def update_goal(self, goal_id: int, **fields: Any) -> None:
        allowed = {"title", "description", "category", "start_date", "deadline_date", "status", "progress"}
        unknown = set(fields) - allowed
        if unknown:
            raise FocusError(f"Unsupported goal fields: {', '.join(sorted(unknown))}")
        if not fields:
            return
        current = self.get_goal(goal_id)
        if current is None:
            raise FocusError("Goal no longer exists.")
        merged = {
            "title": current["title"], "description": current["description"],
            "category": current["category"], "start_date": current["start_date"],
            "deadline_date": current["deadline_date"], "status": current["status"],
            "progress": current["manual_progress"],
        }
        merged.update(fields)
        title = str(merged["title"]).strip()
        if not title:
            raise FocusError("Goal title cannot be empty.")
        start = self._validate_iso_date(merged["start_date"], "Start date")
        deadline = self._validate_iso_date(merged["deadline_date"], "Deadline")
        if deadline < start:
            raise FocusError("Deadline cannot be earlier than the start date.")
        status = str(merged["status"])
        if status not in {"not_started", "in_progress", "completed", "archived"}:
            raise FocusError("Invalid goal status.")
        progress = float(merged["progress"])
        if not 0 <= progress <= 100:
            raise FocusError("Progress must be between 0 and 100.")
        with self._connection() as conn:
            conn.execute(
                """UPDATE goals SET title=?, description=?, category=?, start_date=?, deadline_date=?,
                   status=?, manual_progress=?, updated_at=? WHERE id=?""",
                (title, str(merged["description"]).strip(), str(merged["category"]).strip() or "Personal",
                 start.isoformat(), deadline.isoformat(), status, progress, self._now(), int(goal_id)),
            )

    def delete_goal(self, goal_id: int) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM goals WHERE id=?", (int(goal_id),))

    def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM goals WHERE id=?", (int(goal_id),)).fetchone()
            return dict(row) if row else None

    def list_goals(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE g.status != 'archived'"
        today = datetime.fromtimestamp(self._now(), timezone.utc).astimezone(self.zone).date()
        with self._connection() as conn:
            rows = conn.execute(
                f"""SELECT g.*, COUNT(m.id) AS milestone_count,
                    COALESCE(SUM(CASE WHEN m.completed=1 THEN 1 ELSE 0 END), 0) AS completed_milestones
                    FROM goals g LEFT JOIN milestones m ON m.goal_id=g.id
                    {where} GROUP BY g.id ORDER BY
                    CASE g.status WHEN 'in_progress' THEN 0 WHEN 'not_started' THEN 1
                         WHEN 'completed' THEN 2 ELSE 3 END,
                    g.deadline_date ASC, g.created_at DESC"""
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            count = int(item["milestone_count"] or 0)
            completed = int(item["completed_milestones"] or 0)
            item["progress"] = round(completed * 100 / count) if count else round(float(item["manual_progress"]))
            deadline = date.fromisoformat(item["deadline_date"])
            item["days_remaining"] = (deadline - today).days
            item["overdue"] = item["days_remaining"] < 0 and item["status"] not in {"completed", "archived"}
            result.append(item)
        return result

    def add_milestone(self, goal_id: int, title: str) -> int:
        title = str(title).strip()
        if not title:
            raise FocusError("Milestone title cannot be empty.")
        with self._connection() as conn:
            exists = conn.execute("SELECT 1 FROM goals WHERE id=?", (int(goal_id),)).fetchone()
            if not exists:
                raise FocusError("Select an existing goal first.")
            order = conn.execute("SELECT COALESCE(MAX(sort_order), -1)+1 FROM milestones WHERE goal_id=?",
                                 (int(goal_id),)).fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO milestones(goal_id, title, created_at, sort_order) VALUES (?, ?, ?, ?)",
                (int(goal_id), title, self._now(), int(order)),
            )
            return int(cursor.lastrowid)

    def list_milestones(self, goal_id: int) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE goal_id=? ORDER BY sort_order, id", (int(goal_id),)
            ).fetchall()
        return [dict(row) for row in rows]

    def toggle_milestone(self, milestone_id: int) -> None:
        now = self._now()
        with self._connection() as conn:
            row = conn.execute("SELECT completed FROM milestones WHERE id=?", (int(milestone_id),)).fetchone()
            if row is None:
                raise FocusError("Milestone no longer exists.")
            completed = 0 if int(row["completed"]) else 1
            conn.execute("UPDATE milestones SET completed=?, completed_at=? WHERE id=?",
                         (completed, now if completed else None, int(milestone_id)))

    def delete_milestone(self, milestone_id: int) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM milestones WHERE id=?", (int(milestone_id),))

    def start_timer(self, mode: str, *, label: str = "Focus session", duration_seconds: int | None = None) -> int:
        mode = str(mode).strip().lower()
        if mode not in {"stopwatch", "countdown"}:
            raise FocusError("Choose Stopwatch or Countdown.")
        if mode == "countdown":
            try:
                duration_seconds = int(duration_seconds or 0)
            except (TypeError, ValueError) as exc:
                raise FocusError("Enter a valid countdown duration.") from exc
            if not 1 <= duration_seconds <= 24 * 60 * 60:
                raise FocusError("Countdown must be between 1 second and 24 hours.")
        else:
            duration_seconds = None
        label = str(label).strip() or "Focus session"
        now = self._now()
        deadline = now + duration_seconds if mode == "countdown" else None
        with self._connection() as conn:
            state = conn.execute("SELECT active_session_id FROM focus_state WHERE singleton_id=1").fetchone()
            if state and state["active_session_id"] is not None:
                active = conn.execute("SELECT status FROM focus_sessions WHERE id=?",
                                      (state["active_session_id"],)).fetchone()
                if active and active["status"] in {"running", "paused"}:
                    raise FocusError("A focus timer is already active. Stop it before starting another.")
            cursor = conn.execute(
                """INSERT INTO focus_sessions(mode,label,target_seconds,remaining_seconds,deadline_at,
                   status,created_at,updated_at) VALUES (?,?,?,?,?,'running',?,?)""",
                (mode, label, duration_seconds, duration_seconds, deadline, now, now),
            )
            session_id = int(cursor.lastrowid)
            conn.execute("INSERT INTO focus_segments(session_id,start_at) VALUES (?,?)", (session_id, now))
            conn.execute("UPDATE focus_state SET active_session_id=? WHERE singleton_id=1", (session_id,))
            return session_id

    def _close_open_segment(self, conn: sqlite3.Connection, session_id: int, end_at: float) -> None:
        row = conn.execute(
            "SELECT id,start_at FROM focus_segments WHERE session_id=? AND end_at IS NULL ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            conn.execute("UPDATE focus_segments SET end_at=? WHERE id=?", (max(float(row["start_at"]), end_at), row["id"]))

    def _complete_expired_countdown(self, conn: sqlite3.Connection, session: sqlite3.Row, now: float) -> None:
        deadline = float(session["deadline_at"] or now)
        self._close_open_segment(conn, int(session["id"]), deadline)
        conn.execute(
            """UPDATE focus_sessions SET status='completed', remaining_seconds=0, deadline_at=NULL,
               updated_at=?, completed_at=? WHERE id=?""",
            (now, deadline, int(session["id"])),
        )

    def get_active_timer(self, *, now: float | None = None) -> dict[str, Any] | None:
        current = self._now() if now is None else float(now)
        with self._connection() as conn:
            state = conn.execute("SELECT active_session_id FROM focus_state WHERE singleton_id=1").fetchone()
            session_id = state["active_session_id"] if state else None
            if session_id is None:
                return None
            session = conn.execute("SELECT * FROM focus_sessions WHERE id=?", (session_id,)).fetchone()
            if session is None:
                conn.execute("UPDATE focus_state SET active_session_id=NULL WHERE singleton_id=1")
                return None
            if session["status"] == "running" and session["mode"] == "countdown":
                if float(session["deadline_at"] or 0) <= current:
                    self._complete_expired_countdown(conn, session, current)
                    session = conn.execute("SELECT * FROM focus_sessions WHERE id=?", (session_id,)).fetchone()
            segments = conn.execute(
                "SELECT start_at,end_at FROM focus_segments WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
            elapsed = 0.0
            for segment in segments:
                end = float(segment["end_at"]) if segment["end_at"] is not None else current
                elapsed += max(0.0, end - float(segment["start_at"]))
            result = dict(session)
            result["elapsed_seconds"] = int(elapsed)
            if session["mode"] == "countdown":
                if session["status"] == "running":
                    remaining = max(0, int(float(session["deadline_at"] or current) - current + 0.999999))
                elif session["status"] == "paused":
                    remaining = max(0, int(session["remaining_seconds"] or 0))
                else:
                    remaining = 0 if session["status"] == "completed" else max(0, int(session["remaining_seconds"] or 0))
                result["remaining_seconds"] = remaining
                result["display_seconds"] = remaining
            else:
                result["remaining_seconds"] = None
                result["display_seconds"] = int(elapsed)
            return result

    def pause_timer(self, *, now: float | None = None) -> dict[str, Any] | None:
        current = self._now() if now is None else float(now)
        snapshot = self.get_active_timer(now=current)
        if not snapshot or snapshot["status"] != "running":
            return snapshot
        session_id = int(snapshot["id"])
        with self._connection() as conn:
            session = conn.execute("SELECT * FROM focus_sessions WHERE id=?", (session_id,)).fetchone()
            if session is None or session["status"] != "running":
                return self.get_active_timer(now=current)
            self._close_open_segment(conn, session_id, current)
            remaining = max(0, int(float(session["deadline_at"] or current) - current + 0.999999)) if session["mode"] == "countdown" else None
            conn.execute(
                "UPDATE focus_sessions SET status='paused', remaining_seconds=?, deadline_at=NULL, updated_at=? WHERE id=?",
                (remaining, current, session_id),
            )
        return self.get_active_timer(now=current)

    def resume_timer(self, *, now: float | None = None) -> dict[str, Any] | None:
        current = self._now() if now is None else float(now)
        snapshot = self.get_active_timer(now=current)
        if not snapshot or snapshot["status"] != "paused":
            return snapshot
        session_id = int(snapshot["id"])
        remaining = snapshot.get("remaining_seconds")
        if snapshot["mode"] == "countdown" and not remaining:
            return self.stop_timer(now=current)
        deadline = current + int(remaining) if snapshot["mode"] == "countdown" else None
        with self._connection() as conn:
            conn.execute("INSERT INTO focus_segments(session_id,start_at) VALUES (?,?)", (session_id, current))
            conn.execute(
                "UPDATE focus_sessions SET status='running', deadline_at=?, updated_at=? WHERE id=?",
                (deadline, current, session_id),
            )
        return self.get_active_timer(now=current)

    def stop_timer(self, *, now: float | None = None) -> dict[str, Any] | None:
        current = self._now() if now is None else float(now)
        snapshot = self.get_active_timer(now=current)
        if not snapshot:
            return None
        if snapshot["status"] in {"completed", "stopped"}:
            return snapshot
        session_id = int(snapshot["id"])
        with self._connection() as conn:
            session = conn.execute("SELECT * FROM focus_sessions WHERE id=?", (session_id,)).fetchone()
            if session is None:
                return None
            remaining = session["remaining_seconds"]
            if session["status"] == "running":
                self._close_open_segment(conn, session_id, current)
                if session["mode"] == "countdown":
                    remaining = max(0, int(float(session["deadline_at"] or current) - current + 0.999999))
            conn.execute(
                "UPDATE focus_sessions SET status='stopped', remaining_seconds=?, deadline_at=NULL, updated_at=?, completed_at=? WHERE id=?",
                (remaining, current, current, session_id),
            )
        return self.get_active_timer(now=current)

    def get_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        now = self._now()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM focus_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                segments = conn.execute(
                    "SELECT start_at,end_at FROM focus_segments WHERE session_id=?", (row["id"],)
                ).fetchall()
                item["duration_seconds"] = int(sum(
                    max(0.0, (float(s["end_at"]) if s["end_at"] is not None else now) - float(s["start_at"]))
                    for s in segments
                ))
                result.append(item)
        return result

    def get_daily_focus_seconds(self, day: date | None = None, *, now: float | None = None) -> int:
        current = self._now() if now is None else float(now)
        local_day = day or datetime.fromtimestamp(current, timezone.utc).astimezone(self.zone).date()
        start_local = datetime.combine(local_day, datetime_time.min, tzinfo=self.zone)
        end_local = datetime.combine(local_day + timedelta(days=1), datetime_time.min, tzinfo=self.zone)
        start_utc = start_local.astimezone(timezone.utc).timestamp()
        end_utc = end_local.astimezone(timezone.utc).timestamp()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT start_at,end_at FROM focus_segments WHERE start_at < ? AND COALESCE(end_at, ?) > ?",
                (end_utc, current, start_utc),
            ).fetchall()
        total = 0.0
        for row in rows:
            seg_start = max(float(row["start_at"]), start_utc)
            seg_end = min(float(row["end_at"]) if row["end_at"] is not None else current, end_utc, current)
            total += max(0.0, seg_end - seg_start)
        return int(total)

    def close(self) -> None:
        """Connections are scoped per operation; retained for clean app shutdown API."""
        return None
