#!/bin/sh
# Run Muzix as PUID:PGID (Unraid: 99:100 = nobody:users) so files it writes
# on your shares get the usual owner.
set -e
PUID=${PUID:-99}
PGID=${PGID:-100}
umask "${UMASK:-002}"
if [ "$(id -u)" = "0" ]; then
  if ! getent group "$PGID" >/dev/null; then groupadd -g "$PGID" muzix; fi
  if ! getent passwd "$PUID" >/dev/null; then useradd -u "$PUID" -g "$PGID" -d /config -M -s /usr/sbin/nologin muzix; fi
  mkdir -p /config
  chown "$PUID:$PGID" /config
  find /config -maxdepth 1 ! -user "$PUID" -exec chown -R "$PUID:$PGID" {} + 2>/dev/null || true
  exec gosu "$PUID:$PGID" "$@"
fi
exec "$@"
