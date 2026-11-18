"""The admin's Data page: what Muzix sends out, by day, week and month, by device and kind (traffic.py);
and the log naming who holds the database's connections when they run low (db.py)."""
import gc
import logging
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from muzix import db, traffic
from muzix.api import auth, stream
from muzix.asking import Asker, current
from muzix.models import Root, Track, Traffic, User
from muzix.security import hash_password


@pytest.fixture(autouse=True)
def nothing_counted():
    traffic.flush()
    with db.session() as s:
        s.execute(delete(Traffic))
    yield


@pytest.fixture
def song(tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"\xff\xfb" + b"\0" * 5000)
    with db.session() as s:
        s.execute(delete(User).where(User.username == "traffic-owner"))
        s.add(User(username="traffic-owner", password_hash=hash_password("secret1")))
        root = Root(path=str(tmp_path), kind="music")
        s.add(root)
        s.flush()
        t = Track(root_id=root.id, path=str(f), format="mp3", codec="mp3", title="Song", sample_rate=44100)
        s.add(t)
        s.flush()
        return t.id


def test_a_song_sent_counts_for_its_device_and_today(song):
    app = FastAPI()
    app.add_middleware(traffic.Counted)
    app.include_router(auth.router)
    app.include_router(stream.router)
    c = TestClient(app)
    token = c.post("/api/auth/token", json={"username": "traffic-owner", "password": "secret1", "device": "Pixel 8"}).json()["token"]
    assert c.get(f"/api/stream/{song}", headers={"authorization": f"Bearer {token}"}).content[:2] == b"\xff\xfb"

    today = date.today()
    got = traffic.devices(today, today)
    phone = next(r for r in got if r["device"] == "Pixel 8")
    assert phone["user"] == "traffic-owner" and phone["kinds"]["music"] == 5002
    now = {p["key"]: p for p in traffic.summary()["now"]}
    assert now["today"]["kinds"]["music"] == 5002 and now["yesterday"]["bytes"] == 0


def test_what_kind_an_answer_is():
    assert traffic.kind_of("/api/stream/12", "audio/flac") == "music"
    assert traffic.kind_of("/api/stream/12", "audio/ogg; codecs=opus") == "music"
    assert traffic.kind_of("/api/books/3/parts/1/stream", "audio/mpeg") == "audiobooks"
    assert traffic.kind_of("/api/network/books/3/parts/1/stream", "audio/mpeg") == "audiobooks"
    assert traffic.kind_of("/api/podcasts/episodes/9/stream", "audio/mpeg") == "podcasts"
    assert traffic.kind_of("/api/s/abc/episode/9", "audio/mpeg") == "podcasts"
    assert traffic.kind_of("/api/radio/play", "audio/aacp") == "radio"
    assert traffic.kind_of("/api/art/album/5", "image/webp") == "pictures"
    assert traffic.kind_of("/api/home", "application/json") == "other"
    assert traffic.kind_of("/assets/index.js", "text/javascript") == "other"


def test_days_weeks_and_months():
    tue = date(2026, 11, 17)                        # a Tuesday: the week began on Monday the 16th
    for day, kind, n in (("2026-11-17", "music", 100), ("2026-11-16", "pictures", 10), ("2026-11-15", "radio", 1000),
                         ("2026-11-01", "other", 7), ("2026-10-31", "podcasts", 5)):
        traffic.add(1, "Pixel 8", kind, n, day=day)
    got = traffic.summary("day", today=tue)
    now = {p["key"]: p["bytes"] for p in got["now"]}
    assert now == {"today": 100, "yesterday": 10, "week": 110, "last_week": 1000, "month": 1117, "last_month": 5}
    assert len(got["periods"]) == 14 and got["periods"][-1]["start"] == "2026-11-17" and got["periods"][-1]["bytes"] == 100

    weeks = traffic.summary("week", today=tue)["periods"]
    assert len(weeks) == 12 and (weeks[-1]["start"], weeks[-1]["end"], weeks[-1]["bytes"]) == ("2026-11-16", "2026-11-22", 110)
    assert weeks[-2]["bytes"] == 1000                     # Monday the 9th to Sunday the 15th: the radio
    months = traffic.summary("month", today=tue)["periods"]
    assert (months[-1]["start"], months[-1]["end"], months[-1]["bytes"]) == ("2026-11-01", "2026-11-30", 1117)
    assert (months[-2]["start"], months[-2]["kinds"]["podcasts"]) == ("2026-10-01", 5)
    assert months[0]["start"] == "2025-12-01"


def test_the_log_names_who_holds_the_connections(monkeypatch, caplog):
    monkeypatch.setattr(db, "WARN_AT", 1)
    monkeypatch.setattr(db, "_warned", float("-inf"))   # never: a runner booted under a minute ago has a monotonic clock under 60
    gc.collect()            # sessions earlier tests left for the collector give theirs back now, not in the middle of this
    before = set(db.holders)
    token = current.set(Asker("GET", "/api/stream/159135"))
    try:
        with caplog.at_level(logging.WARNING, logger="muzix.db"), db.session() as s:
            s.execute(text("select 1"))
    finally:
        current.reset(token)
    assert "1 × GET /api/stream/N" in caplog.text
    assert set(db.holders) <= before                      # given back
