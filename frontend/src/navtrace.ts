/** TEMPORARY (diagnosing the back gesture in the installed app): records history changes,
 * the orientation lock and fullscreen, and sends the record to the server log when the app
 * goes to the background or closes. Remove once the back gesture works. */

const trace: string[] = [];
const t0 = Date.now();

export function note(what: string) {
  trace.push(`${((Date.now() - t0) / 1000).toFixed(1)}s ${what} | ${location.pathname} | entries ${history.length}`);
  if (trace.length > 200) trace.shift();
}

function flush(why: string) {
  note(why);
  const mode = matchMedia("(display-mode: standalone)").matches ? "installed app" : "browser tab";
  const body = JSON.stringify({ kind: "navtrace", message: `${mode}, ${why}`, stack: trace.join("\n"), url: location.href });
  navigator.sendBeacon("/api/client-errors", new Blob([body], { type: "application/json" }));
}

export function startNavTrace() {
  for (const m of ["pushState", "replaceState"] as const) {
    const orig = history[m].bind(history);
    history[m] = (...args: Parameters<History["pushState"]>) => {
      orig(...args);
      note(m);
    };
  }
  addEventListener("popstate", () => note("popstate (back/forward)"));
  addEventListener("pageshow", (e) => note(`pageshow persisted=${e.persisted}`));
  addEventListener("pagehide", () => flush("pagehide"));
  document.addEventListener("fullscreenchange", () => note(`fullscreen ${document.fullscreenElement ? "on" : "off"}`));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush("app hidden");
    else note("app visible again");
  });
  note("start");
}
