"""Background jobs (scans, uploads, feed refreshes) with progress and logs.

Jobs run in worker threads. Each job type runs at most once at a time; asking
for a job that is already queued or running returns the existing one.
"""

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select, update

from . import db
from .models import Job

log = logging.getLogger("muzix.jobs")
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job")
_registry: dict[str, callable] = {}
_cancel: set[int] = set()
_lock = threading.Lock()


class Cancelled(Exception):
    pass


class JobContext:
    """Handed to job functions for reporting progress."""

    def __init__(self, job_id: int):
        self.id = job_id
        self._log: list[str] = []
        self._last_flush = 0.0
        self.progress = 0.0
        self.message = ""

    def log(self, line: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"[{stamp}] {line}")
        log.info("job %s: %s", self.id, line)
        self._flush()

    def update(self, progress: float | None = None, message: str | None = None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        self._flush()

    def check(self):
        if self.id in _cancel:
            raise Cancelled()

    def _flush(self, force=False):
        nowt = time.monotonic()
        if not force and nowt - self._last_flush < 1.0:
            return
        self._last_flush = nowt
        with db.session() as s:
            s.execute(update(Job).where(Job.id == self.id).values(
                progress=self.progress, message=self.message[:2000],
                log="\n".join(self._log[-2000:])))


def job(type_: str):
    """Decorator registering a job function: fn(ctx, **params) -> dict | None."""
    def deco(fn):
        _registry[type_] = fn
        return fn
    return deco


def submit(type_: str, title: str = "", **params) -> int:
    with _lock, db.session() as s:
        existing = s.scalar(select(Job).where(Job.type == type_, Job.status.in_(("queued", "running"))))
        if existing is not None and not params.get("_allow_parallel"):
            return existing.id
        row = Job(type=type_, title=title or type_, params={k: v for k, v in params.items() if k != "_allow_parallel"})
        s.add(row)
        s.flush()
        job_id = row.id
    _pool.submit(_run, job_id)
    return job_id


def cancel(job_id: int):
    _cancel.add(job_id)


def _run(job_id: int):
    with db.session() as s:
        row = s.get(Job, job_id)
        row.status, row.started_at = "running", datetime.now(timezone.utc)
        type_, params = row.type, dict(row.params or {})
    ctx = JobContext(job_id)
    status, result = "done", {}
    try:
        result = _registry[type_](ctx, **params) or {}
    except Cancelled:
        status = "cancelled"
        ctx.log("cancelled")
    except Exception as e:  # keep the worker alive, record the failure
        status = "failed"
        ctx.log(f"failed: {e}")
        ctx.log(traceback.format_exc())
    finally:
        _cancel.discard(job_id)
        ctx._flush(force=True)
        with db.session() as s:
            row = s.get(Job, job_id)
            row.status, row.result = status, result
            row.finished_at = datetime.now(timezone.utc)
            if status == "done":
                row.progress = 1.0


def recover():
    """Mark jobs interrupted by a restart."""
    with db.session() as s:
        s.execute(update(Job).where(Job.status.in_(("queued", "running")))
                  .values(status="failed", message="interrupted by restart"))


# ---------------------------------------------------------------- scheduler

_periodic: list[tuple[str, callable, callable]] = []   # (type, interval_fn -> seconds, params_fn)


def every(type_: str, interval_seconds, params=lambda: {}):
    _periodic.append((type_, interval_seconds, params))


def start_scheduler():
    def loop():
        last: dict[str, float] = {}
        time.sleep(20)  # let the app finish starting
        while True:
            for type_, interval_fn, params_fn in _periodic:
                try:
                    interval = interval_fn()
                    if interval and time.time() - last.get(type_, 0) >= interval:
                        last[type_] = time.time()
                        submit(type_, **params_fn())
                except Exception:
                    log.exception("scheduler: %s", type_)
            time.sleep(30)

    threading.Thread(target=loop, name="scheduler", daemon=True).start()
