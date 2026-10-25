/** "Swipe back again to exit", as Android apps do: in the installed app, backing out of the
 * first page shows a hint instead of closing, and a second back within the hint's time closes.
 *
 * It works with a guard history entry under the first page, holding the same address. Chrome
 * skips entries a page adds before anyone has touched it, so the guard is laid on the first
 * tap. Browser tabs keep the ordinary back button: leaving a site is the visitor's call. */

import { useUi } from "./store/ui";

const KEY = "muzixExitGuard";
const WINDOW = 3500;   // as long as the hint shows

function arm() {
  // the current entry becomes the guard; a copy of it goes on top
  history.replaceState({ ...history.state, [KEY]: true }, "");
  history.pushState({ ...history.state, [KEY]: false }, "");
}

export function guardExit() {
  if (!matchMedia("(display-mode: standalone)").matches) return;
  addEventListener("pointerdown", arm, { once: true, capture: true });
  addEventListener("popstate", () => {
    if (!history.state?.[KEY]) return;
    useUi.getState().notify("Swipe back again to exit");
    // no second swipe in time: put the guard back in place
    window.setTimeout(() => {
      if (history.state?.[KEY]) history.pushState({ ...history.state, [KEY]: false }, "");
    }, WINDOW);
  });
}
