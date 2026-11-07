/** The parts of Muzix a server can do without (backend/muzix/modules.py): a module that's off
 * isn't in the menus, and its pages say it's off. */

import { useUi } from "./store/ui";
import type { ModuleKey, Modules } from "./types";

const SECTIONS: [string, ModuleKey][] = [
  ["/vgm", "vgm"], ["/audiobooks", "audiobooks"], ["/podcasts", "podcasts"], ["/radio", "radio"], ["/spotify", "spotify"],
];

/** The module a page belongs to, if any (music's are Muzix itself). */
export function moduleOf(path: string): ModuleKey | null {
  return SECTIONS.find(([p]) => path === p || path.startsWith(p + "/"))?.[1] ?? null;
}

export function useModules(): Modules {
  return useUi((s) => s.modules);
}

/** Of a list of links, those whose module is on. */
export function useShown<T extends { to: string }>(links: T[]): T[] {
  const on = useModules();
  return links.filter((l) => {
    const m = moduleOf(l.to);
    return !m || on[m];
  });
}
