"""Where podcasts are found to browse (podcast_directory.py): Apple's charts and categories, Podcast Index's
trending and Listen Notes' best with their keys, national or international, kept a while on disk."""
import hashlib

import httpx
import pytest

from muzix import podcast_directory as d


class Answer:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("no", request=None, response=None)


@pytest.fixture
def web(monkeypatch, tmp_path):
    """The sources, as answers by address; what was asked is kept in `asked`."""
    values = {"radio_country": "SE", "podcastindex_key": "", "podcastindex_secret": "", "listennotes_key": ""}
    monkeypatch.setattr(d.settings, "get", lambda k: values[k])
    monkeypatch.setattr(d.env, "CACHE_DIR", tmp_path)
    answers, asked = {}, []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, params=None, headers=None):
            asked.append((url, params or {}, headers or {}))
            for start, answer in answers.items():
                if url.startswith(start):
                    return answer(url, params or {}) if callable(answer) else answer
            raise httpx.ConnectError("nothing there")

    monkeypatch.setattr(d, "_client", Client)
    return values, answers, asked


def lookup(*ids):
    return Answer({"results": [{"collectionId": i, "collectionName": f"Pod {i}", "artistName": "Someone",
                                "feedUrl": f"https://feeds.example/{i}", "artworkUrl600": None,
                                "primaryGenreName": "Video Games"} for i in ids]})


def test_categories_and_their_subcategories(web):
    values, _, _ = web
    leisure = next(c for c in d.tree() if c["name"] == "Leisure")
    assert {"id": 1509, "name": "Video Games"} in leisure["subs"]
    assert not any(isinstance(s["id"], str) for s in leisure["subs"])       # Podcast Index's own: with its key
    values.update(podcastindex_key="k", podcastindex_secret="s")
    leisure = next(c for c in d.tree() if c["name"] == "Leisure")
    assert {"id": "pi-110", "name": "Tabletop"} in leisure["subs"]
    assert len(d.tree()) == 19 and sum(len(c["subs"]) for c in d.tree()) == 96


def test_apples_chart_national_and_international(web):
    _, answers, asked = web
    answers["https://itunes.apple.com/se/rss/toppodcasts/limit=100/genre=1509/json"] = Answer(
        {"feed": {"entry": [{"id": {"attributes": {"im:id": "2"}}}, {"id": {"attributes": {"im:id": "1"}}}]}})
    answers["https://itunes.apple.com/lookup"] = lookup(1, 2)
    got = d.browse("1509", "national")
    assert got["country"] == "se" and got["missing"] == ["podcastindex", "listennotes"]
    assert [h["title"] for h in got["sections"][0]["items"]] == ["Pod 2", "Pod 1"]    # in the chart's order
    assert d.browse("1509", "national")["sections"][0]["items"]        # kept: Apple not asked again
    assert sum("rss/toppodcasts" in u for u, _, _ in asked) == 1
    assert d.place("international") == ("us", "en") and d.place("national") == ("se", "sv,sv-se")


def test_podcast_index_trending_by_language_and_category(web):
    values, answers, asked = web
    values.update(podcastindex_key="KEY", podcastindex_secret="SECRET")
    answers["https://itunes.apple.com/se/rss"] = Answer({"feed": {"entry": []}})
    answers[d.PI + "/podcasts/trending"] = Answer({"feeds": [
        {"url": "https://feeds.example/games", "title": "Speljuntan", "author": "A", "artwork": "https://img/x.jpg",
         "categories": {"52": "Video Games"}}]})
    got = d.browse("1509", "national")
    trending = next(s for s in got["sections"] if s["source"] == "podcastindex")
    assert trending["items"][0] == {"title": "Speljuntan", "author": "A", "url": "https://feeds.example/games",
                                    "image": "https://img/x.jpg", "genre": "Video Games", "source": "podcastindex"}
    url, params, headers = next(a for a in asked if a[0].startswith(d.PI))
    assert {k: params[k] for k in ("max", "lang", "cat")} == {"max": 60, "lang": "sv,sv-se", "cat": "52"}   # its ids
    assert params["since"] < __import__("time").time() - 29 * 86400                                       # the month
    assert headers["Authorization"] == hashlib.sha1(("KEY" + "SECRET" + headers["X-Auth-Date"]).encode()).hexdigest()


def test_podcast_indexs_own_categories_by_search(web):
    values, answers, asked = web
    values.update(podcastindex_key="KEY", podcastindex_secret="SECRET")
    answers[d.PI + "/search/byterm"] = Answer({"feeds": [{"url": "https://feeds.example/rpg", "title": "Dice Talk"}]})
    got = d.browse("pi-111", "national")
    assert got["sections"] == [{"source": "podcastindex", "about": "Role-Playing", "items": [
        {"title": "Dice Talk", "author": "", "url": "https://feeds.example/rpg", "image": None, "genre": "", "source": "podcastindex"}]}]
    assert next(p for u, p, _ in asked if u.endswith("/search/byterm")) == {"q": "Role Playing", "max": 60}


def test_listen_notes_best_with_apples_feeds_when_its_own_are_left_out(web):
    values, answers, asked = web
    values.update(listennotes_key="LN")
    answers["https://itunes.apple.com/us/rss"] = Answer({"feed": {"entry": []}})
    answers[d.LN + "/genres"] = Answer({"genres": [{"id": 143, "name": "Video Games", "parent_id": 82}]})
    answers[d.LN + "/best_podcasts"] = Answer({"podcasts": [
        {"title": "Own feed", "publisher": "P", "rss": "https://feeds.example/own", "image": "i"},
        {"title": "Free plan", "rss": "Please upgrade to PRO or ENTERPRISE plan to see this field", "itunes_id": 7}]})
    answers["https://itunes.apple.com/lookup"] = lookup(7)
    got = d.browse("1509", "international")
    best = next(s for s in got["sections"] if s["source"] == "listennotes")["items"]
    assert [h["url"] for h in best] == ["https://feeds.example/own", "https://feeds.example/7"]
    assert all(h["source"] == "listennotes" for h in best)
    _, params, headers = next(a for a in asked if a[0] == d.LN + "/best_podcasts")
    assert params["genre_id"] == 143 and params["region"] == "us" and headers == {"X-ListenAPI-Key": "LN"}


def test_an_older_answer_stands_while_a_source_is_down(web, monkeypatch):
    _, answers, _ = web
    answers["https://itunes.apple.com/se/rss/toppodcasts/limit=100/json"] = Answer({"feed": {"entry": {"id": {"attributes": {"im:id": "3"}}}}})
    answers["https://itunes.apple.com/lookup"] = lookup(3)
    assert d.browse("", "national")["sections"][0]["items"][0]["title"] == "Pod 3"
    answers.clear()                                      # Apple away
    monkeypatch.setattr(d, "APPLE_TTL", -1)              # and the hour is up
    assert d.browse("", "national")["sections"][0]["items"][0]["title"] == "Pod 3"
