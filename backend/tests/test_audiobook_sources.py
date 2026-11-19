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


def test_a_title_with_the_author_and_series_around_it_is_the_sources():
    names = ["Anne Rice", "The Vampire Chronicles"]
    assert sources.around("Anne Rice - Vampire Chronicles 11 - Prince Lestat", "Prince Lestat", names)
    assert sources.around("Carl Sagan The Demon Haunted World", "The Demon-Haunted World", ["Carl Sagan"])
    assert not sources.around("The Lord of the Rings: The Two Towers", "The Lord of the Rings", ["J. R. R. Tolkien"])
    assert not sources.around("Wind and Truth", "Wind and Truth", ["Brandon Sanderson"])


def test_found_with_the_sources_title(offline):
    offline.setattr(sources, "audible_search", lambda *a, **k: [sources.book(
        "audible", "B0LESTATXX", asin="B0LESTATXX", title="Prince Lestat", authors=["Anne Rice"], runtime=3600,
        series=[("The Vampire Chronicles", "11")], language="english")])
    f = sources.identify(sources.Guess(title="Anne Rice - Vampire Chronicles 11 - Prince Lestat", authors=["Anne Rice"], duration=3600))
    assert (f.title, f.series, f.vol) == ("Prince Lestat", "The Vampire Chronicles", "11")


def test_the_year_first_published(monkeypatch):
    asked = []

    def answer(source, url, params=None, page=False):
        asked.append(source)
        if source == "wikidata":
            rows = {"Interview with the Vampire": [("Interview with the Vampire", "Anne Rice", "1976-04-12"),
                                                   ("Interview with the Vampire", "Anne Rice", "1977-01-01"),
                                                   ("Interview with the Vampire: Claudia's Story", "Anne Rice", "2012-11-20")]}
            hit = next((v for k, v in rows.items() if f'"{k}"' in params["query"]), [])
            return {"results": {"bindings": [{"label": {"value": t}, "author": {"value": a}, "date": {"value": d + "T00:00:00Z"}}
                                             for t, a, d in hit]}}
        return {"docs": [{"title": "Blood Canticle", "first_publish_year": 1998, "author_name": ["Someone Else"]},
                         {"title": "Blood Canticle", "first_publish_year": 1672, "author_name": ["Anne Rice"]},
                         {"title": "Blood Canticle", "first_publish_year": 2003, "author_name": ["Anne Rice"]}]}

    monkeypatch.setattr(sources, "_get", answer)
    assert sources.first_published("Interview with the Vampire", "Anne Rice") == "1976"
    assert asked == ["wikidata"]
    # Wikidata hasn't it: Open Library's, the same author's and a year that can be
    assert sources.first_published("Blood Canticle", "Anne Rice") == "2003"


def test_science_and_philosophy():
    def genre(*ladders):
        return place.genre_of(sources.Found(title="x", authors=[], narrators=[], categories=list(ladders)))
    assert genre(["Science & Engineering", "Science", "Astronomy & Space Science", "Astronomy"],
                 ["Science & Engineering", "Science", "History & Philosophy", "Philosophy"]) == "Science & Philosophy"
    assert genre(["Politics & Social Sciences", "Philosophy"]) == "Science & Philosophy"
    assert genre(["Science & Nature"]) == "Science & Philosophy"           # Apple's
    assert genre(["Science Fiction & Fantasy", "Science Fiction"]) == "Science Fiction"
    assert genre(["History", "World"]) == "History" and genre(["Politics & Social Sciences", "Sociology"]) == "Non-fiction"


FRY = dict(title="Harry Potter and the Philosopher's Stone (Narrated by Stephen Fry)", authors=["J.K. Rowling"],
           narrators=["Stephen Fry"], runtime=505 * 60, series=[("Harry Potter (Narrated by Stephen Fry)", "1")], language="english")
FULL_CAST = dict(title="Harry Potter and the Philosopher's Stone (Full-Cast Edition)", authors=["J.K. Rowling"],
                 narrators=["Hugh Laurie", "Matthew Macfadyen"], runtime=521 * 60,
                 series=[("Harry Potter (Full-Cast Editions)", "1")], language="english")


def test_an_edition_the_us_store_has_by_another_title_is_found_in_the_uk_one(offline):
    """Audible's US store has the Full-Cast Edition as "Sorcerer's Stone": when none of its books is as long as ours,
    the UK store is asked too, and the one as long as ours is it (its chapters from the UK store's)."""
    asked, chapters = [], []

    def search(title, author="", keywords="", store="us"):
        asked.append(store)
        if store == "us":
            return [sources.book("audible", "B0D1CSXB3Z", asin="B0D1CSXB3Z", store="us", **FRY)]
        return [sources.book("audible", "uk:B017V568SY", asin="B017V568SY", store="uk", **FRY),
                sources.book("audible", "uk:B0F14RFHS6", asin="B0F14RFHS6", store="uk", **FULL_CAST)]
    offline.setattr(sources, "audible_search", search)
    offline.setattr(sources, "audible_chapters", lambda asin, store="us": chapters.append((asin, store)))
    title = "Harry Potter and the Philosopher’s Stone"
    f = sources.identify(sources.Guess(title=title, authors=["J.K. Rowling"], duration=521 * 60 + 25))
    assert (f.asin, f.narrators, f.series, f.vol, f.title, f.sure) == \
        ("B0F14RFHS6", ["Hugh Laurie", "Matthew Macfadyen"], "Harry Potter (Full-Cast Editions)", "1", title, True)
    assert chapters == [("B0F14RFHS6", "uk")] and "uk" in asked
    # Stephen Fry's, as long as his: the US store's, and the UK store isn't asked
    asked.clear()
    f = sources.identify(sources.Guess(title=title, authors=["J.K. Rowling"], duration=505 * 60 + 10))
    assert (f.asin, f.narrators, f.title) == ("B0D1CSXB3Z", ["Stephen Fry"], title) and set(asked) == {"us"}
    # a book in another language isn't looked for there
    asked.clear()
    sources.identify(sources.Guess(title=title, authors=["J.K. Rowling"], duration=521 * 60, language="swedish"))
    assert "uk" not in asked


def test_an_audible_link_or_asin_from_any_store(offline):
    got = []
    offline.setattr(sources, "audible_get", lambda asin, store="us": got.append((asin, store)))
    for id in ("https://www.audible.co.uk/pd/Harry-Potter-Audiobook/B0F14RFHS6", "https://www.audible.com/pd/B0F14RPXHR?ref=x",
               "uk:B0F14RFHS6", "B0D1CSXB3Z", "1234567890", "https://www.audible.de/pd/B0F14XXXXX", "not one"):
        sources.get("audible", id)
    assert got == [("B0F14RFHS6", "uk"), ("B0F14RPXHR", "us"), ("B0F14RFHS6", "uk"), ("B0D1CSXB3Z", "us"),
                   ("1234567890", "us"), ("B0F14XXXXX", "de")]
    p = sources._audible_slim({"asin": "B0F14RFHS6", "title": "X"}, "uk")
    assert (p["id"], p["url"], p["store"]) == ("uk:B0F14RFHS6", "https://www.audible.co.uk/pd/B0F14RFHS6", "uk")


def test_which_edition_it_is_isnt_part_of_the_title():
    assert sources.bare_title("Harry Potter and the Philosopher's Stone (Narrated by Stephen Fry)") == \
        "Harry Potter and the Philosopher's Stone"
    assert sources.bare_title("Harry Potter and the Sorcerer’s Stone (Full-Cast Edition)") == "Harry Potter and the Sorcerer’s Stone"


def test_tags_written_in_the_wrong_encoding_read_as_meant():
    assert group.unmangle("Harry Potter and the Philosopher\x92s Stone") == "Harry Potter and the Philosopher’s Stone"
    assert group.unmangle("Harry Potter and the Philosopher\u00e2\x80\x99s Stone") == "Harry Potter and the Philosopher’s Stone"
    assert group.unmangle("Café ’") == "Café ’" and group.unmangle("") == ""


def test_the_book_a_loose_file_is_part_of():
    for name, book in [("01. J.K. Rowling - Harry Potter and the Philosopher’s Stone.mp3", "J.K. Rowling - Harry Potter and the Philosopher’s Stone"),
                       ("10 - Dune.mp3", "Dune"), ("Dune - Part 02.mp3", "Dune"), ("Dune (3 of 17).m4b", "Dune"),
                       ("Track 05 - Dune.mp3", "Dune"), ("Stormlight 1.mp3", ""), ("1984.mp3", ""), ("Mistborn.m4b", "")]:
        assert group.book_of(name) == book, name
    assert group.one_book(["01.mp3", "02.mp3"]) and group.one_book(["x/01. Dune.mp3", "x/02. Dune.mp3"])
    assert not group.one_book(["Dune.mp3", "Emma.mp3"]) and not group.one_book(["01.mp3"])


def test_a_named_folders_untagged_parts_are_one_book(tmp_path):
    """A folder put in the watch folder (its name says what's in it) with numbered files and no tags: one book;
    loose untagged files with names of their own stay each a book of its own."""
    book = tmp_path / "J.K. Rowling - Harry Potter and the Philosopher’s Stone"
    book.mkdir()
    for n in ("01. J.K. Rowling - Harry Potter and the Philosopher’s Stone.mp3", "02. J.K. Rowling - Harry Potter and the Philosopher’s Stone.mp3"):
        (book / n).write_bytes(b"\xff\xfb" + b"0" * 400)
    found = group.scan(str(book), named_root=True)
    assert len(found) == 1 and len(found[0].files) == 2
    assert (found[0].guess.title, found[0].guess.authors) == ("Harry Potter and the Philosopher’s Stone", ["J.K. Rowling"])
    other = tmp_path / "Some books"
    other.mkdir()
    for n in ("Dune.mp3", "Emma.mp3"):
        (other / n).write_bytes(b"\xff\xfb" + b"0" * 400)
    assert len(group.scan(str(other), named_root=True)) == 2


def test_a_parts_chapter_name_is_its_own_chapters_not_the_books_title():
    """Parts of a book made before (one chapter each, the book's title in their title tag): the chapter's name."""
    part = {"path": "/x/02 Chapter One.m4b", "title": "Harry Potter and the Philosopher’s Stone",
            "chapters": [{"start": 0, "end": 1907, "title": "Chapter One - The Boy Who Lived"}]}
    assert make.chapter_name(part, 2, "Harry Potter and the Philosopher's Stone") == "Chapter One - The Boy Who Lived"
    part = {"path": "/x/05.mp3", "title": "Harry Potter and the Philosopher’s Stone", "chapters": []}
    assert make.chapter_name(part, 5, "Harry Potter and the Philosopher's Stone") == "Part 5"
    assert make.chapter_name({"path": "/x/03.mp3", "title": "Harry’s Birthday"}, 3, "Harry Potter") == "Harry’s Birthday"


# ---------------------------------------------------------------- collections: Star Wars, H.P. Lovecraft (2026-11-19)

@pytest.fixture
def tagged(monkeypatch):
    """Files made under a folder, with the tags (album, length, artist) group.py reads from them stood in for."""
    def make_files(root, spec):
        tags = {}
        for rel, (album, seconds, *artist) in spec.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfb" + b"0" * 400)
            tags[str(p)] = group.Part(path=str(p), duration=seconds, album=album, author=artist[0] if artist else "")
        monkeypatch.setattr(group, "_read", lambda path: tags[path])
    return make_files


def test_a_collections_loose_stories_are_books_by_their_names(tmp_path, tagged):
    """Files lying beside other books' folders are books by their names, not one 46-hour book of everything the
    collection tagged alike; a part's number doesn't count, a reader's name does. A folder other books lie in is no
    book's home: making the book lying loose in it must not take the others along."""
    c = "H.P. Lovecraft Collection"
    tagged(tmp_path, {
        f"{c}/1920 - Nyarlathotep (Broken Sea).mp3": ("Broken Sea Audio Productions", 400, "H.P. Lovecraft"),
        f"{c}/1920 - Nyarlathotep (McGrenery).mp3": ("Broken Sea Audio Productions", 420, "H.P. Lovecraft"),
        f"{c}/1921 - Ex Oblivione (Broken Sea).mp3": ("Broken Sea Audio Productions", 300),
        f"{c}/The Hound 1 of 2.mp3": ("Dagon & Other Macabre Tales", 900),
        f"{c}/The Hound 2 of 2.mp3": ("Dagon & Other Macabre Tales", 800),
        f"{c}/The Dream-Quest of Unknown Kadath - Part 01 (Read by Maureen O'Brien) (64kbps).mp3": ("Kadath", 1500),
        f"{c}/The Dream-Quest of Unknown Kadath - Part 02 (Read by Maureen O'Brien) (64kbps).mp3": ("Kadath", 1500),
        f"{c}/Dark Worlds/1920 - The Statement of Randolph Carter (June).mp3": ("The Dark Worlds of H.P. Lovecraft", 1000),
        f"{c}/Dark Worlds/Dark Worlds Volume 1/01.mp3": ("Dark Worlds Volume 1", 3000),
        f"{c}/Dark Worlds/Dark Worlds Volume 1/02.mp3": ("Dark Worlds Volume 1", 3000),
    })
    found = {b.guess.title: b for b in group.scan(str(tmp_path))}
    assert sorted(found) == ["Dark Worlds Volume 1", "Ex Oblivione (Broken Sea)", "Nyarlathotep (Broken Sea)",
                             "Nyarlathotep (McGrenery)", "The Dream-Quest of Unknown Kadath", "The Hound",
                             "The Statement of Randolph Carter (June)"]
    assert len(found["The Hound"].files) == 2 and found["Nyarlathotep (Broken Sea)"].guess.year == "1920"
    assert found["The Dream-Quest of Unknown Kadath"].guess.narrator == "Maureen O'Brien"
    assert all(b.home is None for t, b in found.items() if t != "Dark Worlds Volume 1")
    assert found["Dark Worlds Volume 1"].home == str(tmp_path / c / "Dark Worlds" / "Dark Worlds Volume 1")


def test_a_book_in_two_formats_is_two_copies_not_one_book_twice_as_long(tmp_path, tagged):
    tagged(tmp_path, {"02 - Maul Lockdown/m4b/Maul Lockdown.m4b": ("Maul Lockdown", 44000),
                      "02 - Maul Lockdown/mp3/01.mp3": ("Maul Lockdown", 22000), "02 - Maul Lockdown/mp3/02.mp3": ("Maul Lockdown", 22000)})
    found = group.scan(str(tmp_path))
    assert sorted(len(b.files) for b in found) == [1, 2] and {b.guess.title for b in found} == {"Maul Lockdown"}


def test_a_folders_place_in_a_list_isnt_part_of_the_books_name(tmp_path, tagged):
    assert group.from_folder("15 - Kenobi") == {"title": "Kenobi"}
    assert group.from_folder("01. Star Wars Heir to the Empire") == {"title": "Star Wars Heir to the Empire"}
    assert group.from_folder("02 - Dark Tide I - Onslaught") == {"title": "Dark Tide I - Onslaught", "alt": "Onslaught"}
    assert group.from_folder("1 - 1979 - The Book") == {"year": "1979", "title": "The Book"}
    # an "Unknown Album (date)" tag says nothing
    tagged(tmp_path, {"Legends/02 - Deceived/Disc 1/01.mp3": ("Unknown Album (3/25/2011 4:36:17 PM)", 2000),
                      "Legends/02 - Deceived/Disc 2/01.mp3": ("Unknown Album (3/25/2011 4:36:17 PM)", 2000)})
    (b,) = group.scan(str(tmp_path))
    assert (b.guess.title, b.guess.titles, len(b.files)) == ("Deceived", [], 2)


def test_the_people_in_an_artist_tag():
    assert group.names("Aaron Allston, Marc Thompson") == ["Aaron Allston", "Marc Thompson"]
    assert group.names("Rowling, J.K.") == ["Rowling, J.K."]
    assert group.names("James Luceno / Anthony Heald") == ["James Luceno", "Anthony Heald"]
    assert group.names("Christie Golden, Katie Lucas (Foreword)") == ["Christie Golden", "Katie Lucas"]


def test_a_length_its_size_cant_be_is_asked_of_ffprobe(tmp_path, monkeypatch):
    """A broken VBR header said 21 minutes of a 6-hour Legacy of the Force book: 2 Mbit/s for an mp3."""
    f = tmp_path / "Tempest 1.mp3"
    with open(f, "wb") as out:
        out.truncate(72_600_000)
    monkeypatch.setattr(group, "probed", lambda path: 4530.0)
    assert group._length(str(f), 260) == 4530.0
    assert group._length(str(f), 4500) == 4500        # 129 kbit/s: as said


def test_an_estimated_mp3_length_is_heard_out(monkeypatch):
    """ffprobe guesses an mp3 without a VBR header from its bitrate (2200 s); decoding it says 2086 s, as long as the
    .m4b made of it came out."""
    class Done:
        def __init__(self, stdout="", stderr=""):
            self.stdout, self.stderr, self.returncode = stdout, stderr, 0
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[0])
        if cmd[0] == "ffprobe":
            return Done('{"format": {"duration": "2200.1"}, "streams": [{"codec_type": "audio", "codec_name": "mp3"}]}',
                        "[mp3 @ 0x1] Estimating duration from bitrate, this may be inaccurate")
        return Done(stderr="size=N/A time=00:21:07.61 bitrate=N/A\rsize=N/A time=00:34:46.16 bitrate=N/A speed=2.5e+03x")
    monkeypatch.setattr(make.subprocess, "run", run)
    assert make.probe("/x/At the Mountains of Madness.mp3")["duration"] == pytest.approx(2086.16)
    assert calls == ["ffprobe", "ffmpeg"]


def _sure(title, series):
    return sources.Found(title=title, authors=["x"], narrators=[], sure=True, context=[title, "", series])


def test_what_most_of_an_uploads_books_are():
    found = [_sure("Kenobi", "Star Wars: Legends"), _sure("Heir to the Empire", "Star Wars: The Thrawn Trilogy - Legends"),
             _sure("X-Wing: Rogue Squadron", "Star Wars: X-Wing - Legends (abridged)"),
             sources.Found(title="Crucible", authors=[], narrators=[], context=["Crucible", "", "The World of Reforged"])]
    assert sources.theme_of(found) == "star wars"
    assert sources.theme_of(found[:2]) == ""          # two aren't enough to go by
    assert sources.in_theme(["Crucible: Star Wars Legends"], "star wars") and not sources.in_theme(["Crucible"], "star wars")


def test_a_book_no_tag_names_the_author_of_is_looked_for_as_what_the_others_are(offline):
    """"Crucible" alone is somebody else's (2026); with the upload's Star Wars books around it, Troy Denning's."""
    other = sources.book("audible", "B0GP91PV99", asin="B0GP91PV99", title="Crucible", authors=["Seth Haddon"],
                         runtime=12 * 3600, series=[("The World of Reforged", "0.5")])
    denning = sources.book("audible", "B00KGLEH3U", asin="B00KGLEH3U", title="Crucible: Star Wars Legends",
                           authors=["Troy Denning"], runtime=int(12.1 * 3600), series=[("Star Wars: Legends", "")])
    offline.setattr(sources, "audible_search", lambda title, author="", keywords="", store="us":
                    [other, denning] if "star wars" in keywords else [other])
    g = sources.Guess(title="Crucible", duration=12.1 * 3600)
    assert sources.identify(g).authors == ["Seth Haddon"]
    g.keywords = "star wars"
    f = sources.identify(g)
    assert (f.title, f.authors, f.sure) == ("Crucible", ["Troy Denning"], True)


def test_the_books_not_found_for_sure_are_looked_up_again_as_what_the_others_are(monkeypatch):
    from muzix.audiobook import pipeline
    asked = []

    def identify(g):
        asked.append((g.title, g.keywords))
        if g.title == "Crucible":
            return (sources.Found(title="Crucible", authors=["Troy Denning"], narrators=[], sure=True, sources=["audible"],
                                  context=["Crucible: Star Wars Legends"]) if g.keywords else
                    sources.Found(title="Crucible", authors=["Seth Haddon"], narrators=[], sources=["audible"],
                                  context=["Crucible", "", "The World of Reforged"]))
        return _sure(g.title, "Star Wars: Legends")
    monkeypatch.setattr(sources, "identify", identify)
    books = [group.Found(files=[], home=None, unit="/u", guess=sources.Guess(title=t))
             for t in ("Kenobi", "Tarkin", "Revan", "Crucible")]

    class Ctx:
        def check(self): pass
        def update(self, *a): pass
        def log(self, line): asked.append(line)
    ids = pipeline.identify_all(Ctx(), books, ["Kenobi", "Tarkin", "Revan", "Crucible"])
    assert ids[3].authors == ["Troy Denning"] and ("Crucible", "star wars") in asked
    assert [k for t, k in asked[:4]] == ["", "", "", ""] and len([a for a in asked if a == ("Kenobi", "star wars")]) == 0


def test_a_shops_title_without_its_series_and_franchise_around_it():
    for title, series, bare in [("The New Jedi Order: Dark Tide 1: Onslaught", ["Star Wars: The New Jedi Order: Dark Tide"], "Onslaught"),
                                ("The Thrawn Trilogy, Book 3: The Last Command", ["Star Wars: The Thrawn Trilogy - Legends"], "The Last Command"),
                                ("X-Wing: Starfighters of Adumar", ["Star Wars: X-Wing - Legends (abridged)"], "Starfighters of Adumar"),
                                ("Stealth: Star Wars (Clone Wars Gambit)", [], "Stealth"),
                                ("Siege: Star Wars Legends (Clone Wars Gambit)", [], "Siege"),
                                ("Dune: House Atreides", ["Prelude to Dune"], "Dune: House Atreides")]:
        assert sources.without_series(sources.bare_title(title), series) == bare, title
    assert group.clean("Isard's Revenge (X-Wing Saga, Book 8)") == "Isard's Revenge"
    assert group.clean("Nyarlathotep (Broken Sea)") == "Nyarlathotep (Broken Sea)"


def test_files_named_alike_but_for_their_numbers_are_one_book_however_tagged(tmp_path, tagged):
    tagged(tmp_path, {"01 - Vector Prime/1 - Vector Prime.mp3": ("Star Wars-The New Jedi Order-Vector Prime", 2747),
                      **{f"01 - Vector Prime/{i} - Vector Prime.mp3": ("The New Jedi Order - Vector Prime", 2700) for i in (2, 3, 4)}})
    (b,) = group.scan(str(tmp_path))
    assert len(b.files) == 4 and b.guess.title == "Vector Prime"


def test_what_the_others_are_doesnt_make_a_book_of_another_length_ours(offline):
    """Rebel Agent (2 h, a radio drama) isn't Dark Force Rising (14 h) for being Star Wars too."""
    dfr = sources.book("audible", "B005IHAT1A", asin="B005IHAT1A", title="Dark Force Rising", authors=["Timothy Zahn"],
                       runtime=14 * 3600, series=[("Star Wars: The Thrawn Trilogy - Legends", "2")])
    offline.setattr(sources, "audible_search", lambda title, author="", keywords="", store="us": [dfr])
    f = sources.identify(sources.Guess(title="Dark Forces Rebel", duration=2 * 3600, keywords="star wars"))
    assert not f.sources


def test_stories_side_by_side_tagged_with_their_collections_are_books_of_their_own(tmp_path, tagged):
    """Librivox Audio: 46 stories tagged "LibriVox" or "Public Domain Works of H. P. Lovecraft" aren't one 13-hour book."""
    spec = {f"Librivox Audio/19{17 + i} - {t} (Librivox - {r}).mp3": ("LibriVox" if i % 2 else "Public Domain Works of H. P. Lovecraft", 900)
            for i, (t, r) in enumerate([("Dagon", "Sample"), ("The Tomb", "Wittkower"), ("Polaris", "Nelson"), ("Celephais", "Halket"),
                                        ("The Street", "Carpenter"), ("The Tree", "Worrell"), ("Hypnos", "BroBry"), ("He", "Bohnhoff"),
                                        ("The Hound", "Margarite"), ("Azathoth", "Woodworth")])}
    tagged(tmp_path, spec)
    found = group.scan(str(tmp_path))
    assert len(found) == 10 and {b.guess.title for b in found} >= {"Dagon (Librivox - Sample)", "The Hound (Librivox - Margarite)"}
