"""Where an audiobook's details come from (audiobook/sources.py) and what its folder and tags say (group.py), with no
network: Bonnier Audio's book page read, every source's books alike, a Swedish book known by Bonnier when Audible
doesn't know it, and "Pick the right book" asking any source."""
import pytest

from muzix.audiobook import group, make, place, sources

PAGE = """<html><head><meta property="og:image" content="https://img.test/bokbilder/g/9789100000001.jpg" /></head><body>
<header class="book__content__intro"><h1>Isprinsessan</h1>
<div class="book__content__intro__author"><strong class="author-label">Författare:</strong>
  <a href="https://www.bonnieraudio.se/forfattare/9601/camilla-lackberg/">Camilla Läckberg</a></div></header>
<section class="book__content__facts"><div><p><strong>Utgivningsdag:</strong> 2007-09-21<br/><strong>Recensionsdag:</strong> 2007-09-21</p></div>
  <div><p><strong>Uppläsare:</strong> Katarina Ewerlöf</p></div><div><p><strong>Speltid:</strong> 13 h 19 min</p></div></section>
<section class="book__content__excerpt"><p>Det första stycket. <br/>
<br/>Det andra &amp; sista.</p></section>
<section class="book__content__details"><h2>Detaljerad fakta</h2><p><strong>Genre:</strong> Skönlitteratur och relaterande ämnen
  <strong>Originalutgåvans utgivningsår:</strong> 2003 <strong>Serie:</strong> Fjällbacka-serien <strong>Thema-kod:</strong> Polisromaner
  <strong>Speltid:</strong> 13 h 19 min</p></section>
<section class="book__content__books author__content__books"><h2>Boken ingår i serien <i>Fjällbacka-serien</i></h2><div>
  <a href="https://www.bonnieraudio.se/bocker/100/forsta/">Den första</a>
  <a href="https://www.bonnieraudio.se/bocker/153850/isprinsessan/">Isprinsessan</a></div></section>
<section class="book__content__facts"><p><strong>Uppläsare:</strong> The narrow screen's copy</p></section>
</body></html>"""


def test_a_bonnier_audio_book_page_read():
    p = sources.bonnier_book(PAGE, "https://www.bonnieraudio.se/bocker/153850/isprinsessan/")
    assert (p["source"], p["id"], p["title"], p["authors"], p["narrators"]) == \
        ("bonnier", "153850", "Isprinsessan", ["Camilla Läckberg"], ["Katarina Ewerlöf"])
    assert (p["runtime"], p["year"], p["release"], p["series"]) == (13 * 3600 + 19 * 60, "2003", "2007-09-21", [("Fjällbacka-serien", "2")])
    assert p["categories"] == [["Skönlitteratur och relaterande ämnen"], ["Polisromaner"]] and p["language"] == "swedish"
    assert p["summary"] == "Det första stycket.\n\nDet andra & sista." and p["image"].endswith("/g/9789100000001.jpg")


def test_bonnier_audios_search(monkeypatch):
    answers = {"Mordets praktik": {"success": True, "data": {"total": 1, "items": [
        {"id": 155255, "title": "Mordets praktik", "bookPath": "/bocker/155255/mordets-praktik/", "publishingDate": "2009-09-04",
         "coverImage": "https://img.test/bokbilder/b/9789173483100.jpg", "authors": [{"name": "Kerstin Ekman"}]}]}}}
    monkeypatch.setattr(sources, "_get", lambda source, url, params=None, page=False: answers.get((params or {}).get("s"),
                                                                                                    {"success": True, "data": []}))
    [h] = sources.bonnier_search("Mordets praktik")
    assert (h["id"], h["url"], h["authors"]) == ("155255", "https://www.bonnieraudio.se/bocker/155255/mordets-praktik/", ["Kerstin Ekman"])
    assert h["image"] == "https://img.test/bokbilder/g/9789173483100.jpg"          # the large one
    assert sources.bonnier_search("Mordets praktik av Kerstin Ekman") == []


def test_title_by_author():
    assert sources.split_by("Mordets praktik av Kerstin Ekman") == ("Mordets praktik", "Kerstin Ekman")
    assert sources.split_by("Mrs Dalloway by Virginia Woolf") == ("Mrs Dalloway", "Virginia Woolf")
    assert sources.split_by("Stand by Me") == ("", "")
    assert sources.split_by("Death by Black Hole") == ("Death", "Black Hole")      # so a guess trusts it only when backed up


def parts(album, author, n=3, seconds=24060):
    return [group.Part(path=f"/w/x/Mordets_praktik_{i:02d}.mp3", duration=seconds / n, album=album, author=author,
                       title=f"Mordets_praktik_{i:02d}") for i in range(1, n + 1)]


def test_what_a_watch_folders_name_and_the_tags_say():
    assert group.from_folder("Kerstin Ekman - Mordets praktik - Svensk") == \
        {"language": "swedish", "author": "Kerstin Ekman", "title": "Mordets praktik"}
    assert group.from_folder("2011 - The Martian (English)") == {"language": "english", "year": "2011", "title": "The Martian"}
    # the files loose in a folder put in the watch folder: its name says what they are
    b = group.Found(files=parts("Mordets praktik av Kerstin Ekman", "Krister Henriksson"), home=None, unit="/w/x")
    g = group.guess(b, "/w/Kerstin Ekman - Mordets praktik - Svensk", named_root=True)
    assert (g.title, g.authors, g.language) == ("Mordets praktik", ["Kerstin Ekman", "Krister Henriksson"], "swedish")
    # without it, the tags: "... av Kerstin Ekman" with the narrator as the artist is one more way to put it
    g = group.guess(b, "/up/batch", named_root=False)
    assert (g.title, g.titles, g.authors) == ("Mordets praktik av Kerstin Ekman", ["Mordets praktik"],
                                              ["Krister Henriksson", "Kerstin Ekman"])
    # ... and with the author's name in the tags too, it's the title
    g = group.guess(group.Found(files=parts("Mordets praktik av Kerstin Ekman", "Kerstin Ekman"), home=None, unit="/w/x"), "/up/b")
    assert g.title == "Mordets praktik" and g.authors == ["Kerstin Ekman"]


def test_chapters_named_after_the_book_with_underscores():
    assert make.chapter_name({"path": "/x/Mordets_praktik_07.mp3", "title": "Mordets_praktik_07"}, 7, "Mordets praktik") == "Part 7"


MORDETS = sources.book("bonnier", "155255", url="https://www.bonnieraudio.se/bocker/155255/mordets-praktik/",
                       title="Mordets praktik", authors=["Kerstin Ekman"], narrators=["Krister Henriksson"], runtime=24060,
                       year="2009", publisher="Bonnier Audio", language="swedish", image="https://img.test/g/1.jpg",
                       categories=[["Skönlitteratur och relaterande ämnen"], ["Skönlitteratur: allmänt"]], summary="Doktor Glas.")


@pytest.fixture
def offline(monkeypatch):
    """No source knows anything, but what a test says."""
    for name in ("audible_search", "apple_list", "wiki_list", "bonnier_search"):
        monkeypatch.setattr(sources, name, lambda *a, **k: [])
    for name in ("audible_get", "apple_search", "wiki_lookup", "bonnier_get", "apple_get", "wiki_get"):
        monkeypatch.setattr(sources, name, lambda *a, **k: None)
    monkeypatch.setattr(sources, "first_published", lambda *a: "")
    monkeypatch.setattr(sources, "audible_chapters", lambda *a: None)
    return monkeypatch


def test_a_swedish_book_audible_doesnt_know_is_bonnier_audios(offline):
    asked = []
    offline.setattr(sources, "bonnier_find", lambda titles, authors=(), most=5: asked.append(titles) or [MORDETS])
    g = sources.Guess(title="Mordets praktik av Kerstin Ekman", titles=["Mordets praktik"],
                      authors=["Krister Henriksson", "Kerstin Ekman"], duration=24093.9)
    f = sources.identify(g)
    assert (f.title, f.authors, f.narrators, f.year, f.sources, f.sure) == \
        ("Mordets praktik", ["Kerstin Ekman"], ["Krister Henriksson"], "2009", ["bonnier"], True)
    assert place.genre_of(f) == "Fiction" and place.language_code(f.language) == "sv" and f.images == ["https://img.test/g/1.jpg"]
    assert place.target("/ab", f, "Fiction") == "/ab/Fiction/Kerstin Ekman/2009 - Mordets praktik"
    # a book said to be in another language isn't looked for there
    asked.clear()
    f = sources.identify(sources.Guess(title="Mordets praktik", authors=["Kerstin Ekman"], language="english", duration=24060))
    assert asked == [] and f.sources == [] and not f.sure
    # nor is one Audible is sure of
    offline.setattr(sources, "audible_search", lambda *a, **k: [sources.book(
        "audible", "B0SURESURE", asin="B0SURESURE", title="Mordets praktik", authors=["Kerstin Ekman"], runtime=24060, language="swedish")])
    f = sources.identify(sources.Guess(title="Mordets praktik", authors=["Kerstin Ekman"], duration=24060))
    assert asked == [] and f.sources == ["audible"] and f.asin == "B0SURESURE"


def test_a_book_picked_from_any_source_is_taken(offline):
    f = sources.identify(sources.Guess(title="Mordets praktik", authors=["Kerstin Ekman"], duration=24093.9), chosen=MORDETS)
    assert f.sure and f.sources == ["bonnier"] and f.description == "Doktor Glas."


def test_links_go_to_their_source_only(offline):
    called = []
    offline.setattr(sources, "_get", lambda *a, **k: called.append(a) or None)
    offline.setattr(sources, "bonnier_get", lambda url: MORDETS if "bonnieraudio" in url else None)
    link = "https://www.bonnieraudio.se/bocker/155255/mordets-praktik/"
    assert sources.search("bonnier", link) == [MORDETS]
    assert [sources.search(s, link) for s in ("audible", "apple", "wiki")] == [[], [], []]
    assert [sources.search(s, "B003ZWFO7E") for s in ("apple", "wiki")] == [[], []]           # an ASIN is Audible's
    assert called == []
