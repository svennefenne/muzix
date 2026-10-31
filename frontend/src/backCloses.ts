/** Back (the phone's button or swipe, or the browser's) closes a full-screen sheet, the big
 * player say, as in Android apps, instead of leaving the page underneath.
 *
 * Opening the sheet lays a history entry on top, holding the same address; back takes it off
 * and closes the sheet. Closing it any other way (its arrow, Esc) takes the entry off too.
 * Sheets stack: back from the lyrics over the player closes only the lyrics. */

import { useEffect } from "react";

/** `set` must stay the same function (a store's setter). */
export function useBackCloses(name: string, open: boolean, set: (open: boolean) => void) {
  useEffect(() => {
    if (!open) return;
    // an entry of its own: one left from before a reload isn't taken for it
    const id = Math.random();
    const ours = () => history.state?.[name] === id;
    history.pushState({ ...history.state, [name]: id }, "");
    const pop = () => {
      if (!ours()) set(false);
    };
    addEventListener("popstate", pop);
    return () => {
      removeEventListener("popstate", pop);
      if (ours()) history.back();
    };
  }, [name, open, set]);
}
