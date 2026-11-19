"""What in a folder of uploads is one book, and what its folder and files say about it.

- A folder with audio is a book; its disc folders ("CD1", "Disc 2", "The Light Fantastic disc 3", "Elantris [02]")
  belong to it.
- Folders whose audio all carries one album tag are one book together (an anthology split in parts).
- Loose files side by side that are different books (each its own album, or untagged next to other books) are
  one book each; m4b files of one album in a folder (a book cut at every chapter) are one book. Files lying beside
  other books' folders are books by their names ("The Hound 1 of 2" and "2 of 2" one, "Dagon" another), whatever
  album a collection tagged them with.
- A book's home is the highest folder holding nothing but it: what else lies there (a pdf, pictures) goes along, and
  it goes once the book is made. A folder other books lie in too is no book's home."""

import collections
import os
import re
import subprocess
from dataclasses import dataclass, field

from .. import formats
from ..meta import tags
from .sources import Guess, sim, split_by

DISC = re.compile(r"(^|\s|[-_.])(cd|disc|disk|part|del)\s*[-_.]?\s*\d+$|\[\d+\]$|^\d+$", re.I)
JUNK_DIR = {"__MACOSX"}
GENERIC_ALBUM = re.compile(r"^(the horus heresy|unknown album.*|)$", re.I)
# a folder named for the files' format (a book as mp3 and as m4b side by side), not for the book
FORMAT_DIR = re.compile(r"^(mp3|m4b|m4a|aac|flac|ogg|opus|wma|audio|audio ?books?|files|(un)?abridged|\d+\s*kbps)$", re.I)
ASIN = re.compile(r"\b(B0[0-9A-Z]{8})\b")
LOSSY = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wma", ".mp2")


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
    folder: str | None = None         # the folder whose name says what the book is (its home's, or the one it lies in)
    by_name: bool = False             # lying loose beside other books: its files' names say what it is


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


# a part's number anywhere in a name: " - Part 01 (Read by …)", "(1 of 2)", " - 1 of 4", "(Part II)"
PARTNO = re.compile(r"[\s._-]*[\[(]?\b(?:part|pt|disc|disk|cd|track|chapter|kapitel|del)[\s._-]*(?:\d{1,3}|[ivx]{1,4})\b"
                    r"(?:\s*of\s*\d+)?[\])]?|[\s._-]*[\[(]\d{1,3}\s*of\s*\d{1,3}[\])]|[\s._-]+\d{1,3}\s*of\s*\d{1,3}\b", re.I)


def title_in_name(path: str) -> str:
    """What a file's name says it is, its part's number left out: "The Hound 1 of 2" and "The Hound 2 of 2" are
    "The Hound"; "Nyarlathotep (Broken Sea)" and "Nyarlathotep (McGrenery)" two readings of it."""
    stem = os.path.splitext(os.path.basename(path))[0]
    s = PARTNO.sub("", LEAD.sub("", stem, count=1) or stem)
    s = re.sub(r"[\s._-]+\d{1,3}$", "", s)
    return re.sub(r"\s+", " ", s).strip(" -_.") or stem


def _numbered(parts: list) -> bool:
    """Files numbered 1, 2, 3 … that carry one album tag: a book's chapters, whatever they're called."""
    nums = [re.match(r"^\s*(\d{1,3})(?!\d)", os.path.basename(p.path)) for p in parts]
    albums = {album_base(p.album) for p in parts}
    return len(parts) > 1 and all(nums) and len({int(n.group(1)) for n in nums}) == len(parts) and \
        len(albums) == 1 and not GENERIC_ALBUM.match(next(iter(albums)))


def by_name(parts: list) -> list[list]:
    """Loose files as books, by their names (title_in_name)."""
    out: dict[str, list] = {}
    for p in sorted(parts, key=lambda p: p.path):
        out.setdefault(re.sub(r"[\W_]+", " ", title_in_name(p.path)).strip().casefold(), []).append(p)
    return list(out.values())


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


def probed(path: str) -> float:
    """ffprobe's length of a file (0 when it can't tell)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=120).stdout
        return float(out.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _length(path: str, said: float) -> float:
    """A file's length: its tags', unless they give none or one its size can't be (a broken VBR header said 2 of a
    Legacy of the Force book's 6 hours: 2 Mbit/s for an mp3), then ffprobe's."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return said
    if said and not (path.lower().endswith(LOSSY) and size * 8 / said > 640_000):
        return said
    return probed(path) or said


def _read(path: str) -> Part:
    try:
        i = tags.read(path)
    except Exception:  # noqa: BLE001  an unreadable tag still leaves the sound
        return Part(path=path, duration=_length(path, 0))
    narrator = unmangle(i.extra.get("narrator", ""))
    author = unmangle(i.albumartist or i.artist)
    if author and narrator and author == narrator:
        author = unmangle(i.artist) if unmangle(i.artist) != narrator else ""
    return Part(path=path, duration=_length(path, i.duration or 0), album=unmangle(i.album), author=author,
                narrator=narrator, title=unmangle(i.title), year=str(i.year or ""), track=i.track_no)


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
        if len(albums) == 1 and not GENERIC_ALBUM.match(next(iter(albums))) and \
                not all(FORMAT_DIR.match(os.path.basename(k)) for k in kids):    # "mp3" and "m4b": one book twice
            for k in kids:
                units[parent] += units.pop(k)

    books: list[Found] = []
    for u, parts in units.items():
        by_album = collections.defaultdict(list)
        for p in parts:
            by_album[album_base(p.album)].append(p)
        named = re.match(r"^(vol\s*[\d.]+\s*-\s*)?\d{4}\s*-", os.path.basename(u), re.I)
        loose = all(os.path.dirname(p.path) == u for p in parts)
        beside = any(k != u and k.startswith(u + os.sep) for k in units)     # other books' folders in it
        container = u == root or beside
        if beside and loose:
            paths = [p.path for p in parts]
            groups = [parts] if one_book(paths) or _numbered(parts) else by_name(parts)
            for g in groups:
                whole = len(groups) == 1 and len(g) > 1     # all its loose files, one book: the folder's name is its
                books.append(Found(files=g, home=None, unit=u, folder=u if whole and u != root else None,
                                   by_name=not whole))
            continue
        big = [a for a, g in by_album.items() if sum(p.duration for p in g) > 1500]
        if container and loose and "" in by_album and not (named_root and u == root and one_book([p.path for p in by_album[""]])):
            by_album.update({p.path: [p] for p in by_album.pop("")})
        alike = one_book([p.path for p in parts])      # "1 - Vector Prime" … "4 - Vector Prime", however tagged
        if loose and not named and not alike and "" not in by_album and len(by_album) > 1 and \
                (container or len(big) == len(by_album)) and all(len(g) <= 4 for g in by_album.values()):
            books += [Found(files=g, home=None, unit=u) for g in by_album.values()]
        elif u == root and len(by_album) > 1 and not alike:
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
        if b.home and under[b.home] != {i}:     # other books lie in it too: not this one's to take along or remove
            b.folder, b.home = b.folder or b.home, None
        if b.home:
            b.folder = b.folder or b.home
            h = b.home
            while os.path.dirname(h) != root and os.path.dirname(h).startswith(root) and under[os.path.dirname(h)] == {i}:
                h = os.path.dirname(h)
            b.home = h
        while b.folder and FORMAT_DIR.match(os.path.basename(b.folder)) and os.path.dirname(b.folder) != root:
            b.folder = os.path.dirname(b.folder)
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
                r"^Book\s*(?P<vol>\d+)\s*-\s*(?P<title>.+)$"):
        m = re.match(pat, name, re.I)
        if m:
            g.update({k: v.strip() for k, v in m.groupdict().items() if v})
            return g
    m = re.match(r"^\d{1,3}\s*[-.)]\s*(?P<rest>\S.*)$", name)
    if m:                   # "15 - Kenobi", "01. Star Wars Heir to the Empire": its place in a list, not part of its name
        rest = from_folder(m.group("rest"))
        if rest.get("author"):      # "02 - Dark Tide I - Onslaught": a series before the title as often as an author
            rest = {"title": m.group("rest").strip(), "alt": rest["title"],
                    **{k: v for k, v in rest.items() if k not in ("author", "title")}}
        return {**g, **rest}
    m = re.match(r"^(?P<author>[^-]{3,40}?)\s+-\s+(?P<title>.+)$", name)
    if m:
        g.update({k: v.strip() for k, v in m.groupdict().items() if v})
        return g
    g["title"] = name
    return g


JUNK_TITLE = re.compile(r"\s*[\[(]?(unabridged|abridged|audio ?book|mp3|\d+\s*kbps)[\])]?\s*", re.I)
READ_BY = re.compile(r"\s*[\[(](?:read|narrated|performed) by ([^)\]]+)[)\]]", re.I)
NOT_AUTHOR = re.compile(r"black library|big finish|unknown|heavy ent|full cast|^(artist|various( artists)?|audio ?book.*)$", re.I)


def clean(t: str) -> str:
    t = re.sub(r"\{[^}]*\}|^\s*\[[^\]]*\]\s*", "", t or "")
    t = t.replace("_", " ") if " " not in t else t          # "At_The_Mountains_Of_Madness"
    t = READ_BY.sub("", t)
    t = JUNK_TITLE.sub(" ", t)
    t = re.sub(r"\s*\(novella\)|\[\d+\]|\s+-\s*copy$", "", t, flags=re.I)
    t = re.sub(r"\s*\([^)]*\b(book|vol\.?|volume|#)\s*\d+[^)]*\)\s*$", "", t, flags=re.I)  # "(X-Wing Saga, Book 8)"
    return re.sub(r"\s+", " ", t).strip(" -_:,.")


def names(s: str) -> list[str]:
    """The people in an artist tag: "Aaron Allston, Marc Thompson", "James Luceno / Anthony Heald" are two; "Rowling,
    J.K." one."""
    s = re.sub(r"\s*\((foreword|introduction|editor|ed\.)\)", "", s or "", flags=re.I)
    out = []
    for part in re.split(r"\s*[/;]\s*|\s+&\s+", s):
        bits = [b.strip() for b in part.split(",") if b.strip()]
        out += bits if len(bits) > 1 and all(len(b.split()) > 1 for b in bits) else [part.strip()]
    return [n for n in out if n]


def guess(b: Found, root: str, named_root: bool = False) -> Guess:
    from collections import Counter

    def most(attr):
        c = Counter(getattr(p, attr) for p in b.files if getattr(p, attr))
        return c.most_common(1)[0][0] if c else ""

    album, author, narrator = most("album"), most("author"), most("narrator")
    if GENERIC_ALBUM.match(album_base(album)):         # "Unknown Album (3/25/2011 4:36:17 PM)" says nothing
        album = ""
    folder = b.folder or (root if named_root else "")
    g = from_folder(os.path.basename(folder)) if folder else {}
    titles = [clean(g.get("title", "")), clean(g.get("alt", "")), clean(album)]
    if not folder and (b.by_name or len(b.files) == 1):
        own = title_in_name(sorted(p.path for p in b.files)[0])
        n = from_folder(own)            # "1905 - The Beast in the Cave": a year and a title
        said = clean(PARTNO.sub("", most("title")))
        named = [clean(n.get("title", "")), clean(n.get("alt", "")), said]
        titles = named + titles if b.by_name else titles + [clean(own)]
        g = {**{k: v for k, v in n.items() if k in ("year", "language")}, **g}
        m = READ_BY.search(own)
        narrator = narrator or (m.group(1).strip() if m else "")
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
    authors = [n for a in [g.get("author", ""), *first, author, *last] for n in names(a)]
    authors = [a for a in dict.fromkeys(re.sub(r"\[.*?\]|graphic ?audio", "", a, flags=re.I).strip() for a in authors)
               if a and not NOT_AUTHOR.search(a)]
    asin = ""
    for p in b.files:
        m = ASIN.search(os.path.basename(p.path))
        if m:
            asin = m.group(1)
            break
    series = ""
    if b.folder and g.get("vol"):
        parent = os.path.basename(os.path.dirname(b.folder))
        if os.path.dirname(b.folder) != root and not any(parent.lower() == a.lower() for a in authors):
            series = parent
    return Guess(title=titles[0] if titles else "", titles=titles[1:], authors=authors,
                 narrator=g.get("narrator") or narrator, series=series, vol=g.get("vol", "") if series else "",
                 year=g.get("year", ""), asin=asin, language=g.get("language", ""),
                 duration=sum(p.duration for p in b.files))
