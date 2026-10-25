"""Cast links: a speaker without the browser's cookie can stream with a signed link, and
nothing else gets through."""
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from muzix import db, render, security
from muzix.models import User


def request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode(), "headers": []})


@pytest.fixture
def user():
    with db.session() as s:
        u = User(username=f"caster{time.monotonic_ns()}", password_hash="x")
        s.add(u)
        s.commit()
        yield u, s


def test_a_signed_link_streams_without_a_cookie(user):
    u, s = user
    token, expires = security.cast_token(u)
    assert expires > time.time() + 23 * 3600
    assert security.stream_user(request(f"ct={token}"), s, None).id == u.id


@pytest.mark.parametrize("bad", ["", "ct=", "ct=junk", "ct=1.2.3"])
def test_no_or_malformed_link_is_refused(user, bad):
    _, s = user
    with pytest.raises(HTTPException) as e:
        security.stream_user(request(bad), s, None)
    assert e.value.status_code == 401


def test_a_tampered_or_expired_link_is_refused(user):
    u, s = user
    token, _ = security.cast_token(u)
    uid, exp, mac = token.split(".")
    for forged in (f"{uid}.{int(exp) + 3600}.{mac}",            # stretched expiry
                   f"{int(uid) + 1}.{exp}.{mac}",               # someone else's account
                   f"{uid}.{int(time.time()) - 5}.{security._cast_mac(int(uid), int(time.time()) - 5)}"):  # expired
        with pytest.raises(HTTPException):
            security.stream_user(request(f"ct={forged}"), s, None)


def test_cast_quality_keeps_what_speakers_play_and_converts_the_rest():
    assert not render.needs_transcode("flac", "flac", 96000, "cast")
    assert not render.needs_transcode("mp3", "mp3", 44100, "cast")
    assert not render.needs_transcode("m4a", "aac", 44100, "cast")
    assert render.needs_transcode("flac", "flac", 192000, "cast")       # above the speakers' 96 kHz
    assert render.needs_transcode("m4a", "alac", 44100, "cast")         # Apple Lossless
    assert render.needs_transcode("wv", "wavpack", 44100, "cast")       # WavPack
    assert not render.needs_transcode("nsf", "", 0, "cast")             # chiptunes arrive rendered to FLAC
