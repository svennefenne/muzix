"""VGMRips as an online archive: its systems, composers, companies and chips pages become folders,
their packs come twenty to a page, and a pack's own title names its album."""
from muzix import online, vgmrips

SYSTEMS = """<div class="system">
  <div class="pic"><a href="https://vgmrips.net/packs/system/sega/mega-drive"><div class="overlay"><span class="badge">722 packs</span></div></a></div>
  <div class="name"><a href="https://vgmrips.net/packs/system/sega/mega-drive" title="View games on Mega Drive">Mega Drive</a></div>
  <div class="cat">Console &bull; Sega</div>
</div>
<div class="system">
  <div class="pic"><a href="https://vgmrips.net/packs/system/sharp/x68000"><div class="overlay"><span class="badge">240 packs</span></div></a></div>
  <div class="name"><a href="https://vgmrips.net/packs/system/sharp/x68000">X68000</a></div>
  <div class="cat">Computer &bull; Sharp</div>
</div>"""

COMPOSERS = """<li class="composer"><a href="https://vgmrips.net/packs/composer/konami-kukeiha-club">
  <span class="pull-right"><div class="stars stars35"></div></span>
  <span class="pull-right" style="padding-right: 1em"><span class="badge">68</span> </span>
  Konami Kukeiha Club</a></li>"""

COMPANIES = """<tr><td class="link"><a href="https://vgmrips.net/packs/company/konami" title="Konami">Konami</a></td>
  <td><span class="badge"><a href="https://vgmrips.net/packs/company/konami/developed" title="developed">308</a></span></td>
  <td><span class="badge"><a href="https://vgmrips.net/packs/company/konami/published">325</a></span></td></tr>
<tr><td class="link"><a href="https://vgmrips.net/packs/company/publisher-only" title="Publisher Only">P</a></td>
  <td><span class="badge"><a href="https://vgmrips.net/packs/company/publisher-only/developed">0</a></span></td></tr>"""

PACKS = """<div class="container"><div class="clearfix">Packs 1 to 20 of 240 total</div></div>
<div class="result row" id="pack-1">
  <div class="image"><a href="https://vgmrips.net/packs/pack/akumajo-dracula-x68000"><img src="x.png" alt="Akumajō Dracula"></a></div>
  <div class="details"><h2 class="clearfix title">
    <a class="download" href="https://vgmrips.net/files/Computers/Sharp/Akumajo_Dracula_%28Sharp_X68000%29.zip"><small>34 songs &bull;
    653 KB</small> <span class="icon icon-download"></span></a></h2>
    <tr class="composers"><td><a class="badge" href="https://vgmrips.net/packs/composer/konami-kukeiha-club">Konami Kukeiha Club</a></td></tr>
  </div>
</div>"""


def test_groups_become_folders():
    systems = vgmrips.parse_groups(SYSTEMS, "systems")
    assert systems == [{"name": "Mega Drive", "path": "systems/sega/mega-drive", "count": 722},
                       {"name": "X68000", "path": "systems/sharp/x68000", "count": 240}]
    assert vgmrips.parse_groups(COMPOSERS, "composers") == [
        {"name": "Konami Kukeiha Club", "path": "composers/konami-kukeiha-club", "count": 68}]
    # companies count the games they developed; one with none is left out
    assert vgmrips.parse_groups(COMPANIES, "companies") == [{"name": "Konami", "path": "companies/konami", "count": 308}]


def test_pages_and_urls():
    assert vgmrips.page_url(["systems"]) == "https://vgmrips.net/packs/systems/"
    assert vgmrips.page_url(["systems", "sega", "mega-drive"], 2) == "https://vgmrips.net/packs/system/sega/mega-drive?p=2"
    assert vgmrips.page_url(["companies", "konami"]) == "https://vgmrips.net/packs/company/konami/developed"
    assert vgmrips.page_url(["chips", "ym2151"], 1) == "https://vgmrips.net/packs/chip/ym2151?p=1"
    for bad in (["systems", "sega"], ["chips", "../x"], ["files", "x.zip"], ["composers", "a", "b"]):
        assert vgmrips.page_url(bad) is None, bad


def test_packs_page_by_page(monkeypatch):
    pages = {"packs/systems/": SYSTEMS, "packs/system/sharp/x68000": PACKS}

    class Page:
        status_code = 200
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass
    asked = []

    def get(url):
        asked.append(url)
        return Page(next(v for k, v in pages.items() if k in url))
    monkeypatch.setattr(online, "_get", get)
    online._listings.clear()
    src = online.source("vgmrips")
    d = online.listing(src, "systems/sharp/x68000")
    assert d["crumbs"] == [{"name": "Systems", "path": "systems"}, {"name": "X68000", "path": "systems/sharp/x68000"}]
    assert d["more"] and d["total"] == 240
    pack = d["files"][0]
    assert pack["path"] == "files/Computers/Sharp/Akumajo_Dracula_(Sharp_X68000).zip" and pack["kind"] == "archive"
    assert (pack["title"], pack["artist"], pack["songs"], pack["size"]) == ("Akumajō Dracula", "Konami Kukeiha Club", 34, 653 * 1024)
    online.listing(src, "systems/sharp/x68000", page=1)
    assert asked[-1].endswith("/packs/system/sharp/x68000?p=1")
    assert online.remote_url(src, online.parts(pack["path"]), False) == \
        "https://vgmrips.net/files/Computers/Sharp/Akumajo_Dracula_(Sharp_X68000).zip"
    row = {"title": "Black Mass (Opening)", "artist": "", "album": "悪魔城ドラキュラ"}
    vgmrips.label(pack["path"], row)
    assert row["album"] == "Akumajō Dracula" and row["artist"] == "Konami Kukeiha Club"
