/** A newer version of the app this page is in, for Update in the user menu: the Android app's, or Muzix
 * Desktop's for the computer's system (the server asks GitHub which is the newest:
 * backend/muzix/api/android.py). In a browser, none. */

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { appPlayer, useShell } from "./player/app";

interface Latest {
  version: string | null;
  url: string | null;
}

/** The Android app's version, from its user agent ("MuzixApp/0.8.0 (Android)"). */
const androidVersion = () => navigator.userAgent.match(/MuzixApp\/(\d+(?:\.\d+)*)/)?.[1] ?? "";

/** The app's own version: the Android app's, or Muzix Desktop's (its hello). */
export const appVersion = () => androidVersion() || useShell.getState().desktop?.version || "";

/** The same, as it becomes known (Muzix Desktop says it once the page has said hello); "" in a browser. */
export function useAppVersion() {
  const desktop = useShell((s) => s.desktop);
  return androidVersion() || desktop?.version || "";
}

function newer(a: string, b: string) {
  const x = a.split(".").map(Number);
  const y = b.split(".").map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) > (y[i] ?? 0);
  return false;
}

export function useAppUpdate(): { version: string; url: string } | null {
  const desktop = useShell((s) => s.desktop);
  const mine = androidVersion() || desktop?.version || "";
  const q = useQuery({
    queryKey: ["app-latest", desktop?.platform ?? "android"],
    queryFn: () => (desktop ? api.get<Latest>("/api/desktop/latest", { platform: desktop.platform }) : api.get<Latest>("/api/android/latest")),
    enabled: appPlayer.available && !!mine,
    staleTime: 3600_000,
  });
  const { version, url } = q.data ?? {};
  return version && url && mine && newer(version, mine) ? { version, url } : null;
}
