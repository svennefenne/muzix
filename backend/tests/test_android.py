"""The Android app's newest version, from the repository's android-v* releases."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from muzix.api import android
from muzix.security import current_user


def release(tag, apk=True, **kw):
    assets = [{"name": "muzix-android.apk", "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/muzix-android.apk"}]
    return {"tag_name": tag, "assets": assets if apk else [], **kw}


def test_the_highest_version_with_the_apk():
    got = android.newest([
        release("android-v0.9.0"),
        release("android-v0.10.0"),                    # 10 > 9, not "1" < "9"
        release("android-v0.11.0", apk=False),         # still building
        release("android-v0.12.0", draft=True),
        release("android-v0.13.0", prerelease=True),
        release("v1.0.0"),                             # the server's, not the app's
    ])
    assert got == {"version": "0.10.0", "url": "https://github.com/o/r/releases/download/android-v0.10.0/muzix-android.apk"}
    assert android.newest([release("v1.0.0")]) is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(android, "_latest", None)
    monkeypatch.setattr(android, "_next", 0.0)
    app = FastAPI()
    app.include_router(android.router)
    app.dependency_overrides[current_user] = lambda: object()
    return TestClient(app)


def test_asked_once_and_kept_while_github_fails(client, monkeypatch):
    asked = []

    def releases():
        asked.append(1)
        if len(asked) > 1:
            raise httpx.ConnectError("no network")
        return [release("android-v0.8.0")]

    monkeypatch.setattr(android, "_releases", releases)
    assert client.get("/api/android/latest").json()["version"] == "0.8.0"
    assert client.get("/api/android/latest").json()["version"] == "0.8.0"
    assert len(asked) == 1                             # kept for an hour

    monkeypatch.setattr(android, "_next", 0.0)         # the hour is up, and GitHub is away
    assert client.get("/api/android/latest").json()["version"] == "0.8.0"
    assert len(asked) == 2
    assert android._next > 0


def test_nothing_published_yet(client, monkeypatch):
    monkeypatch.setattr(android, "_releases", lambda: [])
    assert client.get("/api/android/latest").json() == {"version": None, "url": None}
