"""Housekeeping jobs."""

import os
import time

from . import env, jobs
from .scanner import finish_scan

RENDER_CACHE_LIMIT = 20 * 1024**3   # rendered chiptunes are small; this is a safety net


@jobs.job("cleanup")
def cleanup(ctx: jobs.JobContext):
    finish_scan(ctx)


@jobs.job("prune_cache")
def prune_cache(ctx: jobs.JobContext):
    """Drop the least recently used renders once the cache passes its limit."""
    files = []
    for r, _, fs in os.walk(env.CACHE_DIR / "render"):
        for f in fs:
            p = os.path.join(r, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if f.endswith(".part") and time.time() - st.st_mtime > 3600:
                os.remove(p)
                continue
            files.append((st.st_atime, st.st_size, p))
    total = sum(s for _, s, _ in files)
    removed = 0
    for _, size, p in sorted(files):
        if total <= RENDER_CACHE_LIMIT:
            break
        os.remove(p)
        total -= size
        removed += 1
    ctx.log(f"render cache: {len(files)} files, removed {removed}")
    return {"removed": removed}
