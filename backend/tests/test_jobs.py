import threading
import time

from muzix import db, jobs
from muzix.models import Job

runs: list[tuple[str, float, float]] = []
gate = threading.Event()


@jobs.job("t_scan")
def fake_scan(ctx, root_id=None):
    start = time.monotonic()
    if root_id == "first":
        gate.wait(5)
    runs.append((root_id, start, time.monotonic()))


def status(job_id):
    with db.session() as s:
        return s.get(Job, job_id).status


def wait_done(*ids, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if all(status(i) == "done" for i in ids):
            return
        time.sleep(0.05)
    raise AssertionError([status(i) for i in ids])


def test_folder_added_mid_scan_gets_its_own_run():
    first = jobs.submit("t_scan", root_id="first")
    while status(first) != "running":
        time.sleep(0.02)
    second = jobs.submit("t_scan", root_id="second")      # e.g. a folder added while the first scan runs
    third = jobs.submit("t_scan", root_id="second")       # the same request again merges into the waiting one
    assert second != first and third == second
    assert status(second) == "queued"
    gate.set()
    wait_done(first, second)
    (r1, _, end1), (r2, start2, _) = runs
    assert (r1, r2) == ("first", "second")
    assert start2 >= end1                                   # one after the other, never two at once
