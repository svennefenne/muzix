# Messages in the Library Network

The chat lets people on a Muzix server, and on the servers it's linked with, write to each other two
at a time, and link albums and songs in what they write. The owner's choices (2026-11-11):

- Private conversations only, between two people. Anyone on this server or a linked one can be written
  to, unless they left themselves out (*Settings → Messages*). They can still write, and be answered.
- Both servers keep the conversation, for good.
- On desktops the chat takes the now playing panel's place; below 1180 px it's a drawer, on phones the
  whole screen. Its button replaced the top bar's fullscreen button (F11 and the footer's chip still go
  fullscreen) and shows only while there's something to it: unread messages, a conversation with
  something new in the last seven days, or the chat open. New conversations start from the account menu
  (*Messages*) and the phone's *More*.
- Linking: Ctrl/⌘+click, the link button's pick mode (for phones), *Share in chat* in a song's menu and
  *Share* on an album page.
- On hover a link shows its cover, name and songs; a click opens *More info*, whose own player plays
  the album without touching the queue (Muzix's music pauses meanwhile and goes on afterwards).
- An unread count on the button and a note when something comes in; no system notifications.

## Where things are

| | |
|---|---|
| `backend/muzix/chat.py` | people, messages, links (snapshots and how a reader's server finds them), handing over and catching up |
| `backend/muzix/api/chat.py` | the pages' routes (`/api/chat/...`), the stream and cover of a link not mirrored here |
| `backend/muzix/api/network.py` | what linked servers call: `/api/network/chat`, `/api/network/chat/people`, `/api/network/avatars/{name}` |
| `backend/muzix/api/connect.py` | `tell(uid, msg)`: a word to an account's open pages over Muzix Connect's websocket |
| `models.ChatMessage`, `Peer.chat_after` | the messages; how far this server has fetched a linked server's |
| `frontend/src/chat/` | the panel (`Chat.tsx`), links, hover card and More info (`Links.tsx`), the preview player (`preview.ts`), state (`store.ts`), rules that need no page (`logic.ts`, tested in `frontend/tests`) |
| `frontend/src/styles/chat.css` | the chat's look |

## One message, two servers

A message is written on its *origin* server and keeps that server's id and its id there
(`origin`, `origin_id`, unique together). A message between two people on the same server is kept once.
One for a linked server is handed over straight away:

```
POST {their address}/api/network/chat           Authorization: Bearer {the key they gave us}
{"id", "from_user", "from_name", "to_user", "text", "links", "sent_at"}
→ 200 {"ok": true, "name": "<their username>"}  | 403 not taking messages | 404 nobody by that id
```

A refusal (403, 404) takes the message back out and tells the writer why; a route that isn't there
(404 "Not Found") means a Muzix from before the chat. When the other server can't be reached the message
stays, `delivered` false, and the page says *Waiting for …*.

Nothing is retried from the writer's side. Instead every server asks each linked server, on starting
(after 30 s) and every five minutes, for what's waiting for its people there:

```
GET {their address}/api/network/chat?after={Peer.chat_after}
→ {"messages": [...as above], "more": bool}     (500 at a time; each one counted delivered there)
```

Messages already here are skipped, so a message handed over and fetched again is kept once. Only
pulls move `chat_after`. Nothing is passed on: a server linked with two others never forwards one's
messages to the other.

The pages hear of new messages, reads and deliveries over the websocket Muzix Connect keeps open
(`{"t": "chat", "event": "new" | "read" | "delivered", "with", "mine", "text", "links"}`), and fetch
the lists again; the list of conversations is also fetched every minute and when the page comes back
into view.

## Icons

People show with their account's icon (`components/Avatar.tsx`, `User.avatar`): a picture of their own
or a letter on a colour. A server tells its linked servers each person's icon with its list of people
and with every message they write (`"avatar"` / `"from_avatar"`: `{"picture": "<name>.webp" | null,
"letter", "color"}`), and the other server keeps the latest in memory (`chat._looks`; the five-minute
catch-up fetches the lists again). A picture is fetched once through the reader's own server,
`/api/chat/avatars/{sid}/{name}` → `GET {their address}/api/network/avatars/{name}`, which hands out only
pictures an account there uses. A picture's name is the start of its contents' SHA-256, so it's checked
on arrival and kept for good under the cache folder (`avatars/`).

## Links

The writer's server makes a snapshot of what's linked, from the writer's own view of the library
(`chat.snapshot`): the server whose own library has it and its id there (a mirrored album is the other
server's, `peer:<sid>/albums/<id>`), title, artist, year, its album, the cover's version and up to 400
songs with their ids there. Another server's snapshots are cleaned on the way in (`clean_link`).

The reader's server works out what the reader gets (`chat.resolve`):

- **here**: this server has it (its own, or mirrored from that server), and the reader sees it. The
  album page, likes and the normal stream and cover addresses apply.
- **network**: the server it's on is linked with this one. Its songs stream through
  `/api/chat/stream/{sid}/{track id there}` and its cover through `/api/art/network/{sid}/album/{id}?v=`,
  the same way mirrored music is fetched (`mirror.audio`, `mirror.picture`). This is what plays an album
  the other server got after the last nightly sync.
- **away**: neither, so the link shows what it is and nothing plays.

Something this server has that the reader can't see (an admin hid it, a module is off, the account's
limits leave it out) isn't fetched from elsewhere for them either. An account with limits
(`limits.py`) gets links only as this server has them for it, never from another server, where the
artist's genres can't be checked; the link then just can't be played, with nothing saying why. Someone
who left the network's music out of their library can still hear a link from another server.

## Trying it

The backend's tests are `backend/tests/test_chat.py` (a stand-in for the other server) and the front
end's `frontend/tests/chat.test.ts` (`npm test`). Two real servers talking to each other were tried
with throwaway servers on their own ports (127.0.0.1:18101 and :18102, scratch libraries, test
accounts only): messages and links both ways, a link to an album the other server hadn't mirrored yet
(cover and stream through the own server), a message written while the other server was down and
fetched once it was back, and the pages in a browser at desktop, drawer and phone sizes. The scripts
are outside the repository, with the other browser checks, in `~/Projects/muzix-testdata/mln_chat/`
(`mln_chat_setup.py` starts and links the two servers; the `mln_chat_*` scripts try them).
