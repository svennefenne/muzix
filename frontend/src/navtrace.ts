/** TEMPORARY (diagnosing the back gesture in the installed app): records history changes,
 * the orientation lock and fullscreen, and sends the record to the server log when the app
 * goes to the background or closes. Remove once the back gesture works. */

const trace: string[] = [];
const t0 = Date.now();

export function note(what: string) {
  trace.push(`${((Date.now() - t0) / 1000).toFixed(1)}s ${what} | ${location.pathname} | entries ${history.length}`);
  if (trace.length > 200) trace.shift();
}

function shown() {
  const h = document.querySelector(".frame-scroll .display, .frame-scroll .h2, .frame-scroll h1");
  return (h?.textContent || "(no heading)").replace(/\s+/g, " ").trim().slice(0, 40);
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
  addEventListener("popstate", () => {
    note("popstate (back/forward)");
    // what the screen actually shows right after, and a moment later
    for (const ms of [0, 300, 1000])
      setTimeout(() => note(`${ms} ms later the page shows "${shown()}"`), ms);
  });
  addEventListener("pageshow", (e) => note(`pageshow persisted=${e.persisted}`));
  addEventListener("pagehide", () => flush("pagehide"));
  document.addEventListener("fullscreenchange", () => note(`fullscreen ${document.fullscreenElement ? "on" : "off"}`));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush("app hidden");
    else note("app visible again");
  });
  note("start");
}
