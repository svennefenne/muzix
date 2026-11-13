/** The section the search field is in now (scope.ts): by the page's address, or as the page says (an album's
 * page: its album's, music or VGM). A section turned off on the server searches everything. */

import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { create } from "zustand";
import { useUi } from "../store/ui";
import { isScope, type Scope, sectionOf, shownScope } from "./scope";

const usePageSection = create<{ section: Scope | null }>(() => ({ section: null }));

/** For a page whose section its address doesn't tell (the album's page): null while it doesn't know yet. */
export function useSectionOfPage(section: Scope | null) {
  useEffect(() => {
    usePageSection.setState({ section });
    return () => usePageSection.setState({ section: null });
  }, [section]);
}

export function useSearchHere(): Scope {
  const { pathname, search } = useLocation();
  const said = usePageSection((s) => s.section);
  const modules = useUi((s) => s.modules);
  // Search's own page searches the section it was opened from (?in=)
  const asked = pathname === "/search" ? new URLSearchParams(search).get("in") : null;
  return shownScope(isScope(asked) ? asked : sectionOf(pathname) ?? said ?? "all", modules);
}
