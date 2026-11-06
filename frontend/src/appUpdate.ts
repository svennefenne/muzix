/** A newer version of the Android app than the one this page is in, for Update in the user menu
 * (the server asks GitHub which is the newest: backend/muzix/api/android.py). Outside the app, none. */

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { appPlayer } from "./player/app";

interface Latest {
  version: string | null;
  url: string | null;
}

/** The app's own version, from its user agent ("MuzixApp/0.8.0 (Android)"). */
export const appVersion = () => navigator.userAgent.match(/MuzixApp\/(\d+(?:\.\d+)*)/)?.[1] ?? "";

function newer(a: string, b: string) {
  const x = a.split(".").map(Number);
  const y = b.split(".").map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) > (y[i] ?? 0);
  return false;
}

export function useAppUpdate(): { version: string; url: string } | null {
  const q = useQuery({
    queryKey: ["android-latest"],
    queryFn: () => api.get<Latest>("/api/android/latest"),
    enabled: appPlayer.available,
    staleTime: 3600_000,
  });
  const { version, url } = q.data ?? {};
  return version && url && newer(version, appVersion()) ? { version, url } : null;
}
