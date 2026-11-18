"""What in a folder of uploads is one book, and what its folder and files say about it.

- A folder with audio is a book; its disc folders ("CD1", "Disc 2", "The Light Fantastic disc 3", "Elantris [02]")
  belong to it.
- Folders whose audio all carries one album tag are one book together (an anthology split in parts).
- Loose files side by side that are different books (each its own album, or untagged next to other books) are
  one book each; m4b files of one album in a folder (a book cut at every chapter) are one book.
- A book's home is the highest folder holding nothing but it: what else lies there (a pdf, pictures) goes along."""

import collections
import os
import re
from dataclasses import dataclass, field

from .. import formats
from ..meta import tags
from .sources import Guess, sim, split_by

DISC = re.compile(r"(^|\s|[-_.])(cd|disc|disk|part|del)\s*[-_.]?\s*\d+$|\[\d+\]$|^\d+$", re.I)
JUNK_DIR = {"__MACOSX"}
GENERIC_ALBUM = re.compile(r"^(the horus heresy|unknown album.*|)$", re.I)
ASIN = re.compile(r"\b(B0[0-9A-Z]{8})\b")


@dataclass
class Part:
    path: str
    duration: float = 0
    album: str = ""
    author: str = ""
    narrator: str = ""
    title: str = ""
    year: str = ""
    track: int = 0


@dataclass
class Found:
    files: list                       # Part, in no order yet (make.py orders them)
    home: str | None                  # the folder that is only this book, or None for loose files
    unit: str                         # the folder the book was found in
    guess: Guess = field(default_factory=Guess)


def album_base(a: str) -> str:
    a = (a or "").lower()
    a = re.sub(r"\s*[\[(]?\b(cd|disc|disk|part)\s*\d+\b[\])]?", "", a)
    a = re.sub(r"\s*[\[(]\d+( of \d+)?[\])]\s*$|\s*\d+ of \d+\s*$", "", a)
    return re.sub(r"[\W_]+", " ", a).strip()


LEAD = re.compile(r"^\s*(?:(?:track|part|disc|cd|chapter|kapitel|del)[\s._-]*)?\d{1,3}(?:\s*of\s*\d+)?\s*[-._)\]]+\s*|"
                  r"^\s*\d{1,3}\s+(?=\D)", re.I)
TRAIL = re.compile(r"[\s._-]*[\[(]?\b(?:part|pt|disc|disk|cd|track|chapter|kapitel|del)[\s._-]*\d{1,3}(?:\s*of\s*\d+)?[\])]?\s*$|"
                   r"\s*[\[(]\d{1,3}\s*of\s*\d{1,3}[\])]\s*$", re.I)


def book_of(file: str) -> str:
    """The book a loose file is a part of, by its name: "01. J.K. Rowling - Harry Potter and the Philosopher's
    Stone.mp3", "… - Part 02.mp3" and "… (3 of 17).mp3" are their book's; "" when the name has no number to drop."""
    stem = os.path.splitext(os.path.basename(file))[0]
    bare = TRAIL.sub("", LEAD.sub("", stem, count=1)).strip(" -_.")
    return bare if bare and bare != stem.strip(" -_.") else ""


def one_book(paths: list[str]) -> bool:
    """Whether files are one book's parts by their names: alike but for their numbers ("01.mp3", "02.mp3" too)."""
    keys = {book_of(p) or re.sub(r"\d+", "", os.path.splitext(os.path.basename(p))[0]).strip(" -_.") for p in paths}
    return len(paths) > 1 and len(keys) == 1


def unmangle(s: str) -> str:
    """A tag's text as it was meant: UTF-8 or Windows-1252 written into a Latin-1 tag reads as "Philosopherâ\x80\x99s"
    or "Philosopher\x92s"; both are "Philosopher’s"."""
    if not s or not re.search(r"[\x80-\x9f]", s):
        return s or ""
    for enc in ("utf-8", "cp1252"):
        try:
            return s.encode("latin-1").decode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def _read(path: str) -> Part:
    try:
        i = tags.read(path)
    except Exception:  # noqa: BLE001  an unreadable tag still leaves the sound
        return Part(path=path)
    narrator = unmangle(i.extra.get("narrator", ""))
    author = unmangle(i.albumartist or i.artist)
    if author and narrator and author == narrator:
        author = unmangle(i.artist) if unmangle(i.artist) != narrator else ""
    return Part(path=path, duration=i.duration or 0, album=unmangle(i.album), author=author, narrator=narrator,
                title=unmangle(i.title), year=str(i.year or ""), track=i.track_no)


def scan(root: str, named_root: bool = False) -> list[Found]:
    """Every book under ``root``. ``named_root``: the root's own name says what's in it (a folder put in the watch
    folder), for a book lying in it loose."""
    by_dir: dict[str, list[Part]] = collections.defaultdict(list)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in JUNK_DIR and not d.startswith(".")]
        for fn in fns:
            if not fn.startswith(".") and formats.is_audio(fn):
                by_dir[dp].append(_read(os.path.join(dp, fn)))
    units: dict[str, list[Part]] = collections.defaultdict(list)
    for d, parts in by_dir.items():
        u = d
        while u != root and DISC.search(os.path.basename(u)) and os.path.dirname(u) != root:
            u = os.path.dirname(u)
        units[u] += parts

    children = collections.defaultdict(list)
    for u in list(units):
        if u != root:
            children[os.path.dirname(u)].append(u)
    for parent, kids in children.items():
        if parent in units or len(kids) < 2:
            continue
        albums = {album_base(p.album) for k in kids for p in units[k]}
        if len(albums) == 1 and not GENERIC_ALBUM.match(next(iter(albums))):
            for k in kids:
                units[parent] += units.pop(k)

    books: list[Found] = []
    for u, parts in units.items():
        by_album = collections.defaultdict(list)
        for p in parts:
            by_album[album_base(p.album)].append(p)
        named = re.match(r"^(vol\s*[\d.]+\s*-\s*)?\d{4}\s*-", os.path.basename(u), re.I)
        loose = all(os.path.dirname(p.path) == u for p in parts)
        container = u == root or any(k != u and k.startswith(u + os.sep) for k in units)
        big = [a for a, g in by_album.items() if sum(p.duration for p in g) > 1500]
        if container and loose and "" in by_album and not (named_root and u == root and one_book([p.path for p in by_album[""]])):
            by_album.update({p.path: [p] for p in by_album.pop("")})
        if loose and not named and "" not in by_album and len(by_album) > 1 and (container or len(big) == len(by_album)) \
                and all(len(g) <= 4 for g in by_album.values()):
            books += [Found(files=g, home=None, unit=u) for g in by_album.values()]
        elif u == root and len(by_album) > 1:
            books += [Found(files=g, home=None, unit=u) for g in by_album.values()]
        else:
            books.append(Found(files=parts, home=None if u == root else u, unit=u))

    owner = {p.path: i for i, b in enumerate(books) for p in b.files}
    under = collections.defaultdict(set)
    for path, i in owner.items():
        d = os.path.dirname(path)
        while d.startswith(root) and d != root:
            under[d].add(i)
            d = os.path.dirname(d)
    for i, b in enumerate(books):
        if b.home:
            h = b.home
            while os.path.dirname(h) != root and os.path.dirname(h).startswith(root) and under[os.path.dirname(h)] == {i}:
                h = os.path.dirname(h)
            b.home = h
        b.guess = guess(b, root, named_root and len(books) == 1)
    return books


LANGUAGE = {"svensk": "swedish", "svenska": "swedish", "swedish": "swedish", "english": "english", "engelska": "english",
            "engelsk": "english", "deutsch": "german", "german": "german", "tysk": "german", "tyska": "german",
            "norsk": "norwegian", "dansk": "danish", "suomi": "finnish", "finska": "finnish"}
LANGUAGE_AT_END = re.compile(r"\s*(?:-|–|\(|\[)\s*(" + "|".join(LANGUAGE) + r")\s*[)\]]?\s*$", re.I)


def from_folder(name: str) -> dict:
    """What a folder's name says: "Vol 5 - 2024 - Wind and Truth {Narrator}", "2011 - The Martian",
    "1 - 1979 - Title [Author]", "Book 03 - Equal Rites", "Kerstin Ekman - Mordets praktik - Svensk"."""
    g = {}
    m = re.search(r"\{([^}]+)\}", name)
    if m:
        g["narrator"] = m.group(1).strip()
        name = name.replace(m.group(0), "").strip()
    m = LANGUAGE_AT_END.search(name)
    if m:
        g["language"] = LANGUAGE[m.group(1).lower()]
        name = name[:m.start()].strip()
    for pat in (r"^Vol\s*(?P<vol>[\d.]+)\s*-\s*(?P<year>\d{4})\s*-\s*(?P<title>.+)$",
                r"^(?P<vol>[\d.]+)\s*-\s*(?P<year>\d{4})\s*-\s*(?P<title>.+?)\s*\[(?P<author>[^\]]+)\]$",
                r"^(?P<year>(19|20)\d\d)\s*-\s*(?P<title>.+)$",
                r"^Book\s*(?P<vol>\d+)\s*-\s*(?P<title>.+)$",
                r"^(?P<author>[^-]{3,40}?)\s+-\s+(?P<title>.+)$"):
        m = re.match(pat, name, re.I)
        if m:
            g.update({k: v.strip() for k, v in m.groupdict().items() if v})
            return g
    g["title"] = name
    return g


JUNK_TITLE = re.compile(r"\s*[\[(]?(unabridged|abridged|audio ?book|mp3|\d+\s*kbps)[\])]?\s*", re.I)


def clean(t: str) -> str:
    t = re.sub(r"\{[^}]*\}|^\s*\[[^\]]*\]\s*", "", t or "")
    t = JUNK_TITLE.sub(" ", t)
    t = re.sub(r"\s*\(novella\)|\[\d+\]|\s+-\s*copy$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -_:,.")


def guess(b: Found, root: str, named_root: bool = False) -> Guess:
    from collections import Counter

    def most(attr):
        c = Counter(getattr(p, attr) for p in b.files if getattr(p, attr))
        return c.most_common(1)[0][0] if c else ""

    album, author, narrator = most("album"), most("author"), most("narrator")
    g = from_folder(os.path.basename(b.home or (root if named_root else ""))) if b.home or named_root else {}
    titles = [clean(g.get("title", "")), clean(album)]
    if not b.home and len(b.files) == 1:
        titles.append(clean(os.path.splitext(os.path.basename(b.files[0].path))[0]))
    first, last = [], []
    for i, t in enumerate(titles):
        title, who = split_by(t)            # "Mordets praktik av Kerstin Ekman": the title, and who wrote it ...
        if title:
            if any(sim(who, a) > 0.8 for a in (g.get("author", ""), author) if a):
                titles[i:i + 1] = [title, t]
                first.append(who)
            else:                           # ... or "Death by Black Hole": one more way to put it, for a source to say
                titles.append(title)
                last.append(who)
            break
    titles = [t for t in dict.fromkeys(titles) if t]
    authors = [g.get("author", ""), *first, author, *last]
    authors = [a for a in dict.fromkeys(re.sub(r"\[.*?\]|graphic ?audio|;", "", a, flags=re.I).strip() for a in authors)
               if a and not re.search(r"black library|big finish|unknown|heavy ent|full cast", a, re.I)]
    asin = ""
    for p in b.files:
        m = ASIN.search(os.path.basename(p.path))
        if m:
            asin = m.group(1)
            break
    series = ""
    if b.home and g.get("vol"):
        parent = os.path.basename(os.path.dirname(b.home))
        if os.path.dirname(b.home) != root and not any(parent.lower() == a.lower() for a in authors):
            series = parent
    return Guess(title=titles[0] if titles else "", titles=titles[1:], authors=authors,
                 narrator=g.get("narrator") or narrator, series=series, vol=g.get("vol", "") if series else "",
                 year=g.get("year", ""), asin=asin, language=g.get("language", ""),
                 duration=sum(p.duration for p in b.files))
