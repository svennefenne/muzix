"""The admin's say over the artists' genre tags (Admin → Tags). What Last.fm, MusicBrainz or a
linked server gave an artist stays as it came (Artist.source_tags); what everyone sees is that after
the admin's rules (TagRule: tags removed, renamed or merged into another, put in a category; the
general one taking place names off, places.py) and the artist's own edits (tags added to it or taken
off it alone): Artist.tags for its genres, everywhere they were before, and Artist.other_tags for
categories shown on a row of their own. Rules change nothing that came, so each one can be taken back."""

from collections import Counter, defaultdict

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from . import settings
from .models import Artist, TagCategory, TagRule
from .places import is_place

SHOWS = ("genre", "apart", "hidden")     # a category's tags: among the genres, on a row of their own, nowhere


class Rules:
    """The rules, read once for a run of artists."""

    def __init__(self, s: Session):
        self.rules = {r.key: (r.removed, r.to, r.category_id) for r in s.scalars(select(TagRule))}
        self.shows = dict(s.execute(select(TagCategory.id, TagCategory.show)).all())
        self.places = bool(settings.get("tags_drop_places"))     # the general rule: place names off

    def place(self, name: str, mine: bool = False) -> bool:
        """Whether the general rule takes the tag off: a place name the admin didn't add to the artist."""
        return self.places and not mine and is_place(name)

    def dropped(self, name: str, mine: bool = False) -> bool:
        """Whether a tag (after its renames) is off: removed everywhere, or a place name."""
        n = self.resolve(name)
        return n is None or self.place(n, mine)

    def resolve(self, name: str, removed: bool = True) -> str | None:
        """What a tag is called after the renames, or None when it's removed (unless `removed` is
        False: then the name it would have)."""
        seen = set()
        while True:
            key = name.casefold()
            rule = self.rules.get(key)
            if rule is None:
                return name
            gone, to, _ = rule
            if gone and removed:
                return None
            if not to or key in seen:
                return name
            seen.add(key)
            if to.casefold() == key:          # only spelled otherwise
                return to
            name = to

    def category(self, name: str) -> int | None:
        rule = self.rules.get(name.casefold())
        return rule[2] if rule and rule[2] in self.shows else None

    def show(self, name: str) -> str:
        c = self.category(name)
        return self.shows[c] if c is not None else "genre"


def given(a: Artist) -> list:
    """What the sources gave an artist ([[tag, weight], ...])."""
    return a.source_tags if a.source_tags is not None else (a.tags or [])


def names(source: list, edits: dict | None, rules: Rules, removed: bool = True) -> list[tuple[str, float, bool]]:
    """An artist's tags after the rules and its own edits, strongest first: (name, weight, added by
    the admin). Two that became one keep the stronger weight; one the admin added counts as its
    strongest. With `removed` False, the ones removed everywhere stay in."""
    edits = edits or {}
    top = max((w or 0 for _, w in source), default=0) or 100
    off = {str(x).casefold() for x in edits.get("remove", [])}
    out: dict[str, list] = {}
    for name, weight, mine in [(n, top, True) for n in edits.get("add", [])] + [(t, w or 0, False) for t, w in source]:
        n = rules.resolve(str(name), removed)
        if not n or (not mine and n.casefold() in off) or (removed and rules.place(n, mine)):
            continue
        k = n.casefold()
        if k in out:
            out[k][1] = max(out[k][1], weight)
        else:
            out[k] = [n, weight, mine]
    return [(n, w, mine) for n, w, mine in out.values()]


def _split(tags, rules: Rules) -> tuple[list, list]:
    shown = [[n, w] for n, w, _ in tags if rules.show(n) == "genre"]
    apart = [[n, w] for n, w, _ in tags if rules.show(n) == "apart"]
    return shown, apart


def apply(a: Artist, rules: Rules):
    """Works out what an artist shows, after its tags or the rules changed."""
    if a.source_tags is None:
        a.source_tags = a.tags or []
    shown, apart = _split(names(a.source_tags, a.tag_edits, rules), rules)
    if a.tags != shown:
        a.tags = shown
    if (a.other_tags or []) != apart:
        a.other_tags = apart or None


def apply_all(s: Session) -> int:
    """Every artist's tags again, after the rules changed: how many changed."""
    rules = Rules(s)
    changes = []
    for aid, source, edits, tags, other in s.execute(
            select(Artist.id, Artist.source_tags, Artist.tag_edits, Artist.tags, Artist.other_tags)):
        src = source if source is not None else (tags or [])
        shown, apart = _split(names(src, edits, rules), rules)
        if source is None or shown != (tags or []) or apart != (other or []):
            changes.append({"id": aid, "source_tags": src, "tags": shown, "other_tags": apart or None})
    if changes:
        s.execute(update(Artist), changes)
    return len(changes)


RULES_VERSION = "places-1"      # raised when a general rule comes: every artist's tags again, once


def catch_up():
    """At start: every artist's tags worked out again once after the general rules changed (place names off,
    2026-11-13), so the tags looked up before follow them too."""
    if settings.get("tag_rules_applied") == RULES_VERSION:
        return
    from . import db
    with db.session() as s:
        apply_all(s)
    settings.set_many({"tag_rules_applied": RULES_VERSION})


def genres(s: Session, tags: list) -> list[str]:
    """Tags looked up for an artist outside the library, as its genres would show."""
    rules = Rules(s)
    return [n for n, _, _ in names(tags, None, rules) if rules.show(n) == "genre"]


def groups(s: Session, a: Artist) -> list[dict]:
    """An artist's tags in categories shown apart, by category: [{name, tags}]."""
    if not a.other_tags:
        return []
    rules = Rules(s)
    by: dict[int, list[str]] = defaultdict(list)
    for n, _ in a.other_tags:
        c = rules.category(n)
        if c is not None:
            by[c].append(n)
    cats = dict(s.execute(select(TagCategory.id, TagCategory.name).where(TagCategory.id.in_(by))).all())
    return [{"name": cats[c], "tags": by[c]} for c in sorted(by, key=lambda c: cats[c].casefold())]


# ---------------------------------------------------------------- Admin → Tags

def overview(s: Session) -> dict:
    """Every tag the artists carry, how many carry it and what the rules say of it; the removed
    ones, and the categories."""
    rules = Rules(s)
    count, added, removed, places, spelled = Counter(), Counter(), Counter(), Counter(), {}
    tagged = 0
    for source, edits, tags in s.execute(select(Artist.source_tags, Artist.tag_edits, Artist.tags)):
        src = source if source is not None else (tags or [])
        have = names(src, edits, rules, removed=False)
        tagged += any(not rules.dropped(n, mine) for n, _, mine in have)
        for n, _, mine in have:
            k = n.casefold()
            spelled.setdefault(k, n)
            if rules.resolve(n) is None:
                removed[k] += 1
            elif rules.place(n, mine) or (not rules.places and not mine and is_place(n)):
                places[k] += 1
                if not rules.places:            # the rule off: shown as any tag, and listed with what it would take
                    count[k] += 1
            else:
                count[k] += 1
                added[k] += mine
    aliases = defaultdict(list)
    for key, (_, to, _) in rules.rules.items():
        if to and to.casefold() != key:
            aliases[(rules.resolve(to, removed=False) or to).casefold()].append(key)
    cats = s.scalars(select(TagCategory).order_by(TagCategory.name)).all()
    in_cat = Counter(rules.category(spelled[k]) for k in count)
    return {
        "tagged": tagged,
        "tags": [{"name": spelled[k], "artists": n, "added": added[k], "category": rules.category(spelled[k]),
                  "aliases": sorted(aliases.get(k, []))}
                 for k, n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))],
        "removed": sorted(({"name": spelled.get(k, k), "artists": removed[k]}
                           for k, (gone, _, _) in rules.rules.items() if gone),
                          key=lambda r: (-r["artists"], r["name"].casefold())),
        "categories": [{"id": c.id, "name": c.name, "show": c.show, "tags": in_cat[c.id]} for c in cats],
        # the general rule: place names off (on), and those it takes (or would take) off how many artists
        "places": {"on": rules.places, "tags": [{"name": spelled[k], "artists": n}
                                                for k, n in sorted(places.items(), key=lambda kv: (-kv[1], kv[0]))]},
    }


def carriers(s: Session, name: str) -> dict:
    """The artists carrying a tag (as one it became, too), and those it was taken off alone."""
    rules = Rules(s)
    key = name.casefold()
    have, off = [], []
    for a in s.scalars(select(Artist).order_by(Artist.name)):
        for n, _, mine in names(given(a), a.tag_edits, rules, removed=False):
            if n.casefold() == key:
                have.append({"id": a.id, "name": a.name, "added": mine})
                break
        else:
            if any(str(x).casefold() == key for x in (a.tag_edits or {}).get("remove", [])):
                off.append({"id": a.id, "name": a.name})
    return {"artists": have, "taken_off": off}


def _rule(s: Session, rules: dict, name: str) -> TagRule:
    key = name.strip().casefold()[:128]
    if key not in rules:
        rules[key] = TagRule(key=key, removed=False, to="", category_id=None)
        s.add(rules[key])
    return rules[key]


def _tidy(s: Session):
    """Rules that no longer say anything go."""
    s.flush()
    for r in s.scalars(select(TagRule)):
        if not r.removed and r.category_id is None and (not r.to or r.to == r.key):
            s.delete(r)


def change(s: Session, *, remove=(), restore=(), merge=(), into: str = "", unmerge=(),
           categorize=(), category: int | None = None) -> int:
    """Changes the rules, then every artist's tags: how many artists changed.
    remove / restore: tags removed everywhere, or back. merge + into: tags renamed into one (a single
    one renamed). unmerge: names merged into another, their own again. categorize + category: tags
    put in a category (None: back among the genres)."""
    rules = {r.key: r for r in s.scalars(select(TagRule))}
    for n in remove:
        _rule(s, rules, n).removed = True
    for n in restore:
        _rule(s, rules, n).removed = False
    if merge:
        into = into.strip()[:128]
        ik = into.casefold()
        for n in merge:
            k = n.strip().casefold()
            if k == ik:
                continue
            r = _rule(s, rules, n)
            r.to, r.removed = into, False
            for other in rules.values():          # those merged into it before follow it
                if other.to and other.to.casefold() == k:
                    other.to = into
        target = _rule(s, rules, into)
        target.to, target.removed = into, False    # its own tag (and spelled so)
    for n in unmerge:
        r = _rule(s, rules, n)
        target, r.to = r.to.casefold(), ""
        # the name it was merged into, spelled the admin's way for it alone, is as it was
        t = rules.get(target)
        if t is not None and t.to.casefold() == target and not any(
                o.to and o.to.casefold() == target and o.key != target for o in rules.values()):
            t.to = ""
    if categorize:
        if category is not None and s.get(TagCategory, category) is None:
            raise ValueError("No such category")
        for n in categorize:
            _rule(s, rules, n).category_id = category
    _tidy(s)
    s.flush()
    return apply_all(s)


def delete_category(s: Session, cid: int) -> int:
    s.execute(update(TagRule).where(TagRule.category_id == cid).values(category_id=None))
    s.execute(delete(TagCategory).where(TagCategory.id == cid))
    _tidy(s)
    s.flush()
    return apply_all(s)


# ---------------------------------------------------------------- one artist

def artist_tags(s: Session, a: Artist) -> dict:
    """An artist's tags for its editor: each with whether the admin added it and its category; the
    ones taken off it alone."""
    rules = Rules(s)
    return {"tags": [{"name": n, "added": mine, "category": rules.category(n)}
                     for n, _, mine in names(given(a), a.tag_edits, rules)],
            "taken_off": list((a.tag_edits or {}).get("remove", [])),
            "given": [t for t, _ in given(a)]}


def set_artist_tags(s: Session, a: Artist, wanted: list[str]) -> list[str]:
    """Gives an artist these tags (as its editor shows them), as edits on what the sources gave it,
    so later lookups still come through. Returns those that won't show: removed everywhere."""
    rules = Rules(s)
    if a.source_tags is None:
        a.source_tags = a.tags or []
    base = {n.casefold(): n for n, _, _ in names(a.source_tags, None, rules)}
    want: dict[str, str] = {}
    for t in wanted:
        t = t.strip()[:128]
        if t:
            want.setdefault((rules.resolve(t, removed=False) or t).casefold(), t)
    edits = {"add": [t for k, t in want.items() if k not in base], "remove": [n for k, n in base.items() if k not in want]}
    a.tag_edits = edits if edits["add"] or edits["remove"] else None
    apply(a, rules)
    return [t for t in edits["add"] if rules.resolve(t) is None]


def edit_artist_tags(s: Session, a: Artist, add=(), remove=()) -> list[str]:
    """Adds tags to an artist, or takes them off it, leaving its others as they are."""
    rules = Rules(s)
    now = [n for n, _, _ in names(given(a), a.tag_edits, rules)]
    gone = {x.casefold() for x in remove}
    return set_artist_tags(s, a, [n for n in now if n.casefold() not in gone] + list(add))
