"""Writes backend/muzix/places_data.py: the place names an artist's genre tags lose (Admin → Tags, "Place
names"): countries (ISO 3166, with their codes), what their people are called, regions, US states and other
parts of countries, and cities (the time zone database's, and those music is named by). A tag is one only
whole: "finnish" is, "finnish metal" isn't. Words that are genres too stay out (latin, celtic, balkan...).

    python3 scripts/places.py      (needs Debian's iso-codes and tzdata, as most Linux systems have)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from muzix.places import norm  # noqa: E402   (as Muzix matches a tag against the list)

ISO = Path("/usr/share/iso-codes/json/iso_3166-1.json")
ZONES = Path("/usr/share/zoneinfo/zone1970.tab")
OUT = Path(__file__).parents[1] / "backend" / "muzix" / "places_data.py"

# genres and kinds of music named after places: never taken off as a place
GENRES = {"latin", "celtic", "balkan", "oriental", "arabic", "west coast", "east coast", "southern", "nordic folk",
          "americana", "britpop", "krautrock", "j pop", "k pop", "afro", "tropical", "flamenco"}
# two letters that are tags of their own, not countries: DJ mixes, TV music, FM radio...
NOT_CODES = {"dj", "tv", "fm", "ai", "am", "pm"}
# names that are people's or things' more than places
NOT_CITIES = {"regina", "phoenix", "victoria", "troll", "casey", "nome", "eucla", "lord howe", "mawson", "vostok",
              "davis", "palmer", "rothera", "syowa", "dumontdurville", "macquarie", "mcmurdo"}

OTHER_NAMES = """usa, us, u s a, uk, u k, united states, united states of america, america, great britain, britain,
england, scotland, wales, northern ireland, holland, czechia, czech republic, south korea, north korea, korea, russia,
iran, syria, vietnam, laos, taiwan, bolivia, venezuela, tanzania, moldova, macedonia, north macedonia, ivory coast,
eu, ussr, soviet union, yugoslavia, east germany, west germany, the netherlands, republic of ireland, palestine,
congo, dr congo, the gambia, the bahamas, vatican, burma, swaziland, cape verde"""

# as MusicBrainz's and Last.fm's taggers write them in their own languages ("island", Iceland, is an English word)
ABROAD = """estados unidos, eua, eeuu, ee uu, alemanha, alemania, deutschland, allemagne, germania, reino unido,
royaume uni, regno unito, vereinigtes königreich, grossbritannien, großbritannien, suécia, suecia, sverige, schweden,
suède, svezia, finlândia, finlandia, suomi, finnland, noruega, norge, norwegen, norvège, dinamarca, danmark, dänemark,
frança, francia, frankreich, españa, espana, espanha, spanien, espagne, italia, itália, italien, brasil, brasilien,
japão, japon, japón, giappone, canadá, kanada, austrália, australien, holanda, países bajos, paises bajos,
niederlande, pays bas, rusia, rússia, russland, russie, polska, polônia, polonia, polen, méxico, mexiko, grécia,
grecia, griechenland, grèce, irlanda, irland, islândia, islandia, österreich, schweiz, suiza, suíça, svizzera,
suisse, belgien, bélgica, belgique, ukraina, türkei, turquía, turquia, chile, argentinien, kolumbien, portugal,
tschechien, ungarn, rumänien, kroatien, serbien, schottland, escocia, escócia, irlande, inglaterra, angleterre"""

PEOPLE = """american, british, english, scottish, welsh, irish, northern irish, canadian, australian, new zealander,
kiwi, swedish, norwegian, danish, finnish, icelandic, faroese, greenlandic, german, austrian, swiss, dutch, belgian,
flemish, walloon, luxembourgish, french, italian, spanish, catalan, basque, galician, portuguese, greek, cypriot,
maltese, polish, czech, slovak, hungarian, romanian, moldovan, bulgarian, serbian, croatian, slovenian, bosnian,
montenegrin, macedonian, albanian, kosovar, ukrainian, russian, belarusian, lithuanian, latvian, estonian, georgian,
armenian, azerbaijani, turkish, kurdish, israeli, palestinian, lebanese, syrian, jordanian, iraqi, iranian, persian,
saudi, emirati, yemeni, egyptian, libyan, tunisian, algerian, moroccan, sudanese, ethiopian, eritrean, somali,
kenyan, tanzanian, ugandan, rwandan, congolese, angolan, zambian, zimbabwean, mozambican, malagasy, south african,
namibian, botswanan, nigerian, ghanaian, ivorian, malian, senegalese, gambian, guinean, cameroonian, beninese,
burkinabe, nigerien, chadian, cape verdean, japanese, chinese, korean, south korean, north korean, taiwanese,
mongolian, hong konger, thai, vietnamese, cambodian, laotian, burmese, malaysian, singaporean, indonesian, filipino,
philippine, indian, pakistani, bangladeshi, sri lankan, nepalese, nepali, bhutanese, afghan, kazakh, uzbek, kyrgyz,
tajik, turkmen, mexican, guatemalan, honduran, salvadoran, nicaraguan, costa rican, panamanian, cuban, jamaican,
haitian, dominican, puerto rican, trinidadian, barbadian, bahamian, brazilian, argentinian, argentine, chilean,
colombian, peruvian, venezuelan, ecuadorian, bolivian, paraguayan, uruguayan, surinamese, guyanese, quebecois,
bavarian, scandinavian, european, african, asian, east asian, south asian, southeast asian, middle eastern,
latin american, south american, north american, central american, caribbean, nordic, baltic, californian, texan"""

REGIONS = """europe, scandinavia, baltics, africa, north africa, west africa, east africa, southern africa, asia,
east asia, south asia, southeast asia, central asia, middle east, near east, latin america, south america,
north america, central america, oceania, australasia, the caribbean, mediterranean, iberia, benelux, balkans,
eastern europe, western europe, northern europe, southern europe, central europe, midwest, bay area, pacific northwest,
new england, deep south, the south, west indies, siberia, lapland, sapmi, patagonia, polynesia, scandinavian peninsula"""

STATES = """alabama, alaska, arizona, arkansas, california, colorado, connecticut, delaware, florida, georgia, hawaii,
idaho, illinois, indiana, iowa, kansas, kentucky, louisiana, maine, maryland, massachusetts, michigan, minnesota,
mississippi, missouri, montana, nebraska, nevada, new hampshire, new jersey, new mexico, new york, north carolina,
north dakota, ohio, oklahoma, oregon, pennsylvania, rhode island, south carolina, south dakota, tennessee, texas, utah,
vermont, virginia, washington, west virginia, wisconsin, wyoming, washington dc, ontario, quebec, british columbia,
alberta, manitoba, saskatchewan, nova scotia, new brunswick, newfoundland, new south wales, queensland, tasmania,
western australia, south australia, bavaria, saxony, andalusia, catalonia, basque country, galicia, sicily, sardinia,
tuscany, lombardy, flanders, wallonia, brittany, normandy, provence, corsica, scania, norrland, jutland, karelia,
yorkshire, lancashire, cornwall, kent, essex, midlands, ulster, highlands"""

CITIES = """new york city, nyc, ny, la, sf, san francisco, san diego, seattle, portland, austin, nashville, memphis,
new orleans, atlanta, boston, philadelphia, minneapolis, miami, houston, dallas, baltimore, oakland, brooklyn, bronx,
queens, harlem, compton, detroit, chicago, los angeles, las vegas, salt lake city, washington d c, pittsburgh,
cleveland, st louis, kansas city, richmond, athens georgia, olympia, tacoma, sacramento, long island, new jersey,
manchester, liverpool, birmingham, bristol, leeds, sheffield, newcastle, nottingham, brighton, oxford, cambridge,
glasgow, edinburgh, aberdeen, dublin, cork, belfast, cardiff, gothenburg, goteborg, göteborg, malmo, malmö, uppsala,
umea, umeå, linkoping, linköping, orebro, örebro, oslo, bergen, trondheim, stavanger, copenhagen, aarhus, helsinki,
tampere, turku, oulu, reykjavik, reykjavík, hamburg, munich, münchen, cologne, köln, dusseldorf, düsseldorf, frankfurt,
leipzig, dresden, stuttgart, hannover, vienna, wien, zurich, zürich, geneva, basel, amsterdam, rotterdam, utrecht,
the hague, eindhoven, brussels, antwerp, ghent, paris, lyon, marseille, toulouse, bordeaux, lille, nantes, madrid,
barcelona, valencia, seville, bilbao, lisbon, porto, rome, milan, naples, turin, florence, bologna, venice, athens,
thessaloniki, istanbul, ankara, warsaw, krakow, kraków, gdansk, wroclaw, prague, brno, budapest, bucharest, sofia,
belgrade, zagreb, ljubljana, sarajevo, kyiv, kiev, kharkiv, odessa, lviv, moscow, st petersburg, saint petersburg,
minsk, vilnius, riga, tallinn, tokyo, osaka, kyoto, nagoya, seoul, busan, beijing, shanghai, hong kong, taipei,
bangkok, singapore, jakarta, manila, kuala lumpur, mumbai, bombay, delhi, new delhi, bangalore, kolkata, sydney,
melbourne, brisbane, perth, adelaide, auckland, wellington, christchurch, toronto, montreal, montréal, vancouver,
ottawa, calgary, winnipeg, halifax, mexico city, guadalajara, monterrey, tijuana, sao paulo, são paulo,
rio de janeiro, rio, buenos aires, santiago, bogota, bogotá, medellin, lima, caracas, havana, kingston, lagos,
accra, nairobi, addis ababa, cairo, johannesburg, cape town, durban, tel aviv, jerusalem, beirut, tehran, dubai"""


def words(text: str) -> set[str]:
    return {norm(w) for w in text.replace("\n", " ").split(",") if w.strip()}


def main():
    out: set[str] = set()
    for c in json.loads(ISO.read_text())["3166-1"]:
        out.add(norm(c["alpha_2"]))
        for k in ("name", "common_name", "official_name"):
            if c.get(k):
                name = c[k]
                out.add(norm(name))
                if ", " in name:                          # "Korea, Republic of" → "korea"
                    out.add(norm(name.split(", ")[0]))
    out -= {norm(c) for c in NOT_CODES}
    for line in ZONES.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        zone = line.split("\t")[2]
        if zone.startswith(("Antarctica/", "Etc/")):
            continue
        out.add(norm(zone.split("/")[-1].replace("_", " ")))
    out |= words(OTHER_NAMES) | words(ABROAD) | words(PEOPLE) | words(REGIONS) | words(STATES) | words(CITIES)
    out -= {norm(c) for c in NOT_CITIES} | {norm(g) for g in GENRES}
    body = "\n".join(f"    {p!r}," for p in sorted(out))
    OUT.write_text(f'"""Place names an artist\'s genre tags lose (tagging.py, Admin → Tags): written by scripts/places.py,\n'
                   f'as its norm() has them."""\n\nPLACES = frozenset({{\n{body}\n}})\n')
    print(f"{len(out)} place names → {OUT}")


if __name__ == "__main__":
    main()
