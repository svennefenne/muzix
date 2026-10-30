/** Away from wifi, the song that plays and the next two are downloaded whole, ahead of time: a
 * tunnel or a dead spot in the mobile network then doesn't stop the music, which plays on from
 * the copies (player/engine.ts). On wifi, and where the browser doesn't say (only Chrome on
 * Android does), songs stream as usual. */

interface Connection extends EventTarget {
  type?: string;
}

const connection = (navigator as Navigator & { connection?: Connection }).connection;

/** Whether this device is on mobile data now. */
export const onMobileData = () => connection?.type === "cellular";

/** The network changed (wifi to mobile data, say). */
export function onNetworkChange(fn: () => void) {
  connection?.addEventListener("change", fn);
  window.addEventListener("online", fn);
}

interface Wanted { key: string; url: string }

class Stash {
  private got = new Map<string, string>();      // item key -> object URL of the whole file
  private want: Wanted[] = [];
  private busy: { key: string; abort: AbortController } | null = null;
  private failed = new Map<string, number>();   // the server said no this many times
  private retry: number | undefined;

  /** The whole file of an item, when it's here. */
  url(key: string) {
    return this.got.get(key);
  }

  /** What to have, in order; everything else goes, except `keep` (the elements still use them). */
  set(want: Wanted[], keep: string[]) {
    this.want = want;
    const wanted = new Set([...want.map((w) => w.key), ...keep]);
    for (const [key, url] of this.got) {
      if (wanted.has(key)) continue;
      URL.revokeObjectURL(url);
      this.got.delete(key);
    }
    if (this.busy && !want.some((w) => w.key === this.busy!.key)) {
      this.busy.abort.abort();
      this.busy = null;
    }
    this.pump();
  }

  /** One download at a time, the song that plays first. A dropped connection tries again in a
   * while; a server that can't give the file (three times) is let be. */
  private pump() {
    window.clearTimeout(this.retry);
    const next = this.want.find((w) => !this.got.has(w.key) && (this.failed.get(w.key) ?? 0) < 3);
    if (this.busy || !next) return;
    const abort = new AbortController();
    this.busy = { key: next.key, abort };
    fetch(next.url, { signal: abort.signal, credentials: "same-origin" })
      .then((r) => {
        if (!r.ok) {
          this.failed.set(next.key, (this.failed.get(next.key) ?? 0) + 1);
          throw new Error(`HTTP ${r.status}`);
        }
        return r.blob();
      })
      .then((blob) => {
        if (this.busy?.abort === abort) this.got.set(next.key, URL.createObjectURL(blob));
      })
      .catch(() => {
        if (!abort.signal.aborted) this.retry = window.setTimeout(() => this.pump(), 5000);
      })
      .finally(() => {
        if (this.busy?.abort !== abort) return;
        this.busy = null;
        if (this.got.has(next.key)) this.pump();
      });
  }
}

export const stash = new Stash();
