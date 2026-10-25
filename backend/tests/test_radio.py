"""Station history: the songs a station announced while you listened, newest first, no
repeats in a row, and only the last hundred per station and listener."""
from muzix import db
from muzix.api import radio
from muzix.models import User


def test_history_keeps_the_last_hundred_without_repeats():
    with db.session() as s:
        me, other = User(username="radio-me", password_hash="x"), User(username="radio-other", password_hash="x")
        s.add_all([me, other])
        s.commit()
        for i in range(130):
            radio.remember(me.id, "station-a", f"Artist {i} - Song {i}")
            radio.remember(me.id, "station-a", f"Artist {i} - Song {i}")   # a reconnect announces it again
        radio.remember(me.id, "station-b", "Someone - Elsewhere")
        radio.remember(other.id, "station-a", "Their - Song")

        mine = radio.history("station-a", s, me)
        assert len(mine) == radio.HISTORY
        assert mine[0]["title"] == "Artist 129 - Song 129" and mine[-1]["title"] == "Artist 30 - Song 30"
        assert mine[0]["at"].endswith("+00:00")
        assert [h["title"] for h in radio.history("station-b", s, me)] == ["Someone - Elsewhere"]
        assert [h["title"] for h in radio.history("station-a", s, other)] == ["Their - Song"]
