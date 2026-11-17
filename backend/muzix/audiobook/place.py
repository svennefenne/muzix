"""Where a book goes: Genre/Author/Series/Vol N - Year - Title (or Genre/Author/Year - Title) in the audiobook
folder; what genre (Audible's categories put into a short list, one per author as the library has it, Warhammer
for Black Library's), what language, and whether the library has the book already."""

import os
import re

from sqlalchemy import select

from .. import db
from ..models import Book
from .make import safe
from .sources import Found, norm, sim

GENRES = ["Fantasy", "Science Fiction", "Warhammer", "Horror", "Thriller & Crime", "Fiction", "Non-fiction", "Biography",
          "History", "Children's", "Humor", "Uncategorized"]
DUPLICATES = "_Duplicates"
# Audible's categories (and Bonnier Audio's Swedish ones, Apple's genre) → ours, the more telling first
CATEGORY = [
    (r"Science Fiction & Fantasy > Science Fiction|^Science Fiction(?! &)|(?i:science fiction$|: science fiction)", "Science Fiction"),
    (r"Science Fiction & Fantasy > Fantasy|> Fantasy|^Fantasy|(?i:: fantasy|^sci-fi (&|och) fantasy)", "Fantasy"),
    (r"Horror|(?i:skräck)", "Horror"),
    (r"Mystery|Myster|Thriller|Crime|Suspense|Detective|(?i:krim|deckare|polisroman|spänning|thriller)", "Thriller & Crime"),
    (r"Biographies|Memoir|(?i:biografi|memoar)", "Biography"),
    (r"^History|> History|(?i:^historia)", "History"),
    (r"Children|Teen & Young Adult|Young Adult|(?i:^barn|ungdom|^kids)", "Children's"),
    (r"Comedy|Humor", "Humor"),
    (r"Literature & Fiction|Romance|Classics|Erotica|(?i:^skönlitteratur|^fiction|roman$)", "Fiction"),
    (r"Business|Health|Science|Politics|Religion|Self|Education|Money|Relationships|Computers|Travel|Arts|Sports|"
     r"Home|Psychology|Philosophy|Language|(?i:^fakta|facklitteratur|samhälle|hälsa|ekonomi|psykologi|filosofi)",
     "Non-fiction"),
]
LANGUAGES = {"english": "en", "swedish": "sv", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
             "dutch": "nl", "danish": "da", "norwegian": "no", "finnish": "fi", "polish": "pl", "russian": "ru",
             "portuguese": "pt", "japanese": "ja", "chinese": "zh", "mandarin_chinese": "zh"}
NAMES = {"en": "English", "sv": "Svenska", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano",
         "nl": "Nederlands", "da": "Dansk", "no": "Norsk", "fi": "Suomi", "pl": "Polski", "ru": "Русский",
         "pt": "Português", "ja": "日本語", "zh": "中文"}


def language_code(v: str) -> str:
    v = (v or "").strip().lower()
    if v in NAMES:
        return v
    if v in LANGUAGES:
        return LANGUAGES[v]
    for code, name in NAMES.items():
        if v == name.lower():
            return code
    return ""


def genre_of(f: Found) -> str:
    if f.warhammer:
        return "Warhammer"
    ladders = [" > ".join(lad) for lad in f.categories]
    for pattern, genre in CATEGORY:
        if any(re.search(pattern, lad) for lad in ladders):
            return genre
    return "Uncategorized"


def author_genre(root: str, author: str) -> str:
    """The genre folder this author already has in the library, if any (all their books share one, as for music)."""
    a = safe(author)
    for g in GENRES:
        if g != "Warhammer" and os.path.isdir(os.path.join(root, g, a)):
            return g
    return ""


def name_of(f: Found, narrator_too: bool = False) -> str:
    name = (f"Vol {f.vol} - " if f.series and f.vol else "") + (f"{f.year} - " if f.year else "") + safe(f.title)
    if narrator_too and f.narrators:
        name += " {" + safe(", ".join(f.narrators[:2])) + "}"
    return name


def target(root: str, f: Found, genre: str) -> str:
    """Where in ``root`` the book goes; another edition of one already there gets its narrator added."""
    author = safe(f.authors[0]) if f.authors else "Unknown Author"
    base = os.path.join(root, genre, author, *([safe(f.series)] if f.series else []))
    folder = os.path.join(base, name_of(f))
    if os.path.exists(folder):
        folder = os.path.join(base, name_of(f, narrator_too=True))
    return folder


def duplicate_of(f: Found, seconds: float) -> Book | None:
    """The library's copy of this book: the same Audible title, or the same title and author and narrator (and so about
    as long). Another narrator's reading isn't one."""
    with db.session() as s:
        books = s.scalars(select(Book).where(Book.peer_id.is_(None))).all()
        for b in books:
            if f.asin and getattr(b, "asin", "") == f.asin:
                return b
            if norm(b.title) == norm(f.title) or sim(b.title, f.title) > 0.92:
                same_author = not f.authors or sim(b.author or "", f.authors[0]) > 0.8
                narr = {norm(n) for n in re.split(r",|&", b.narrator or "") if n.strip()}
                theirs = {norm(n) for n in f.narrators}
                same_narrator = not narr or not theirs or bool(narr & theirs)
                if same_author and same_narrator and (not b.duration or abs(b.duration - seconds) < 0.05 * max(seconds, 1)):
                    return b
    return None


def aside(root: str, f: Found) -> str:
    """Where a duplicate waits for the admin: _Duplicates/<Author> - <Title>, numbered if taken."""
    base = os.path.join(root, DUPLICATES, safe(f"{f.authors[0] if f.authors else 'Unknown'} - {f.title}"))
    folder, n = base, 2
    while os.path.exists(folder):
        folder, n = f"{base} ({n})", n + 1
    return folder
