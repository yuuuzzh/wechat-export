"""In-memory async job store for long-running backup tasks.

Why this exists
---------------
`/api/backup/run` used to stream progress only over a single SSE connection.
Leaving the page aborts the fetch; the worker then blocks on a full
``queue.Queue(maxsize=100)`` and the backup effectively stalls.

This store keeps job state in process memory so:
1. The worker never blocks on a disconnected client (non-blocking fan-out).
2. Navigating away and back can resume the same progress UI.
3. Other pages can show a lightweight "backup running" chip.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from queue import Empty, Full, Queue
from typing import Any, Optional


def _now() -> float:
    return time.time()


class ProgressJob:
    """One long-running task with fan-out SSE subscribers."""

    __slots__ = (
        'id', 'kind', 'status', 'stage', 'detail', 'progress',
        'logs', 'result', 'error', 'created_at', 'updated_at',
        '_lock', '_subscribers',
    )

    def __init__(self, kind: str = 'backup'):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = 'pending'  # pending | running | select | done | error
        self.stage = ''
        self.detail = ''
        self.progress = 0.0
        self.logs: deque[dict[str, Any]] = deque(maxlen=200)
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.updated_at = self.created_at
        self._lock = threading.Lock()
        self._subscribers: list[Queue] = []

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                'id': self.id,
                'kind': self.kind,
                'status': self.status,
                'stage': self.stage,
                'detail': self.detail,
                'progress': self.progress,
                'logs': list(self.logs),
                'result': self.result,
                'error': self.error,
                'created_at': self.created_at,
                'updated_at': self.updated_at,
                'running': self.status in ('pending', 'running'),
            }

    def subscribe(self, *, replay_logs: bool = True) -> Queue:
        """Attach a non-blocking subscriber queue; optionally replay recent logs."""
        q: Queue = Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
            # Immediate snapshot so reconnecting clients catch up.
            snap = {
                'stage': self.stage or 'progress',
                'detail': self.detail,
                'progress': self.progress,
                'job_id': self.id,
                'status': self.status,
            }
            if self.status == 'done':
                snap = {
                    'stage': 'done',
                    'detail': self.detail or '',
                    'progress': 1.0,
                    'result': self.result,
                    'job_id': self.id,
                    'status': self.status,
                }
            elif self.status == 'error':
                snap = {
                    'stage': 'error',
                    'message': self.error or 'Unknown error',
                    'progress': self.progress,
                    'job_id': self.id,
                    'status': self.status,
                }
            elif self.status == 'select' and self.result is not None:
                snap = {
                    'stage': 'select',
                    'detail': '',
                    'progress': self.progress or 0.15,
                    'matches': self.result,
                    'job_id': self.id,
                    'status': self.status,
                }
            self._put_nowait(q, snap)
            if replay_logs and self.status == 'running':
                for line in self.logs:
                    self._put_nowait(q, {
                        'stage': line.get('stage') or 'progress',
                        'detail': line.get('detail') or '',
                        'progress': line.get('progress') or self.progress,
                        'job_id': self.id,
                        'status': self.status,
                        'replay': True,
                    })
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    @staticmethod
    def _put_nowait(q: Queue, item: Any) -> None:
        """Never block the worker: drop oldest if the subscriber is slow/gone."""
        try:
            q.put_nowait(item)
        except Full:
            try:
                q.get_nowait()
            except Empty:
                pass
            try:
                q.put_nowait(item)
            except Full:
                pass

    def _broadcast(self, item: dict[str, Any]) -> None:
        dead: list[Queue] = []
        for q in self._subscribers:
            try:
                self._put_nowait(q, item)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def progress_event(self, stage: str, detail: str = '', progress: float = 0.0) -> None:
        with self._lock:
            self.status = 'running'
            self.stage = stage or self.stage
            self.detail = detail or ''
            self.progress = float(progress or 0.0)
            self.updated_at = _now()
            self.logs.append({
                'stage': self.stage,
                'detail': self.detail,
                'progress': self.progress,
                'ts': self.updated_at,
            })
            item = {
                'stage': self.stage,
                'detail': self.detail,
                'progress': self.progress,
                'job_id': self.id,
                'status': self.status,
            }
            self._broadcast(item)

    def mark_select(self, matches: list) -> None:
        with self._lock:
            self.status = 'select'
            self.stage = 'select'
            self.detail = '请选择要备份的账号'
            self.progress = 0.15
            self.result = matches
            self.updated_at = _now()
            item = {
                'stage': 'select',
                'detail': '',
                'progress': 0.15,
                'matches': matches,
                'job_id': self.id,
                'status': self.status,
            }
            self._broadcast(item)
            # Close live streams after select (same semantics as old SSE).
            self._broadcast(None)  # type: ignore[arg-type]
            self._subscribers.clear()

    def mark_done(self, result: Any = None) -> None:
        with self._lock:
            self.status = 'done'
            self.stage = 'done'
            self.detail = '完成'
            self.progress = 1.0
            self.result = result
            self.error = None
            self.updated_at = _now()
            item = {
                'stage': 'done',
                'detail': '',
                'progress': 1.0,
                'result': result,
                'job_id': self.id,
                'status': self.status,
            }
            self._broadcast(item)
            self._broadcast(None)  # type: ignore[arg-type]
            self._subscribers.clear()

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.status = 'error'
            self.stage = 'error'
            self.detail = message or 'Unknown error'
            self.error = message
            self.updated_at = _now()
            item = {
                'stage': 'error',
                'message': message,
                'progress': self.progress,
                'job_id': self.id,
                'status': self.status,
            }
            self._broadcast(item)
            self._broadcast(None)  # type: ignore[arg-type]
            self._subscribers.clear()


class JobStore:
    """Process-wide registry; keeps a few recent jobs for reconnect."""

    def __init__(self, *, keep: int = 8):
        self._lock = threading.Lock()
        self._jobs: dict[str, ProgressJob] = {}
        self._order: deque[str] = deque(maxlen=keep)
        self._current_id: Optional[str] = None

    def create(self, kind: str = 'backup') -> ProgressJob:
        job = ProgressJob(kind=kind)
        with self._lock:
            # Only one active backup at a time — reject overlaps at API layer;
            # still register cleanly if previous finished.
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._current_id = job.id
            # Prune oldest beyond maxlen of _order
            alive = set(self._order)
            for jid in list(self._jobs.keys()):
                if jid not in alive:
                    self._jobs.pop(jid, None)
        return job

    def get(self, job_id: str) -> Optional[ProgressJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def current(self, kind: str = 'backup') -> Optional[ProgressJob]:
        with self._lock:
            if self._current_id:
                job = self._jobs.get(self._current_id)
                if job and job.kind == kind:
                    return job
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if job and job.kind == kind:
                    return job
            return None

    def active(self, kind: str = 'backup') -> Optional[ProgressJob]:
        job = self.current(kind)
        if job and job.status in ('pending', 'running'):
            return job
        return None


# Singleton used by backup routes / global progress chip.
backup_jobs = JobStore()
