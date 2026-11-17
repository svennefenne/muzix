"""Who and what a request is while it runs: its path from the start, the account and device once the sign-in
is known (security.py). The counting of what goes out (traffic.py) and the database's watch on its connections
(db.py) read it. The request's threads see the same Asker, so what one of them learns, the others know."""

import contextvars
import re
from dataclasses import dataclass

NUMBERS = re.compile(r"\d+")


@dataclass
class Asker:
    method: str
    path: str
    user_id: int = 0        # 0: no account (a linked server, a share link, the web page's own files)
    device: str = ""        # the login's device ("Pixel 8", "Firefox on Linux"), "Cast speaker", "Library Network: Salikon"…

    def route(self) -> str:
        """The request with its numbers left out ("GET /api/stream/N"): alike requests group together."""
        return f"{self.method} {NUMBERS.sub('N', self.path)}"


current: contextvars.ContextVar[Asker | None] = contextvars.ContextVar("muzix_asker", default=None)


def asked_by(user_id: int | None, device: str):
    """Who the running request is for."""
    if (a := current.get()) is not None:
        a.user_id, a.device = user_id or 0, device
