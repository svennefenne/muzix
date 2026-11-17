/** Admin → Data: what this server has sent out (backend traffic.py), today so far, yesterday, this and last
 * week and month; day by day, week by week or month by month; and for the period picked, of what kind and to
 * which device. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmtBytes } from "../../api";
import { Empty, Loading } from "../../components/ui";

type Kinds = Record<string, number>;
interface Period { start: string; end: string; bytes: number; kinds: Kinds }
interface Summary { now: (Period & { key: string; label: string })[]; periods: Period[]; by: By; kinds: string[] }
interface Device { user: string; device: string; bytes: number; kinds: Kinds }
type By = "day" | "week" | "month";

const KIND_NAMES: Record<string, string> = {
  music: "Music", audiobooks: "Audiobooks", podcasts: "Podcasts", radio: "Radio", pictures: "Covers & pictures",
  other: "The app & other",
};
const BY: [By, string][] = [["day", "Days"], ["week", "Weeks"], ["month", "Months"]];

const day = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const todayIso = () => {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
};
function isoWeek(d: Date): number {
  const t = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 3 - ((d.getDay() + 6) % 7));   // that week's Thursday
  const first = new Date(t.getFullYear(), 0, 4);
  return 1 + Math.round(((t.getTime() - first.getTime()) / 86400000 - 3 + ((first.getDay() + 6) % 7)) / 7);
}
const fmt = (d: Date, o: Intl.DateTimeFormatOptions) => d.toLocaleDateString(undefined, o);

/** What a period is called, in full (`long`) or under its bar. */
function name(p: Period, by: By, long = true): string {
  const a = day(p.start);
  if (by === "month") return long ? fmt(a, { month: "long", year: "numeric" }) : fmt(a, { month: "short" });
  if (by === "week") {
    const z = day(p.end);
    return long ? `Week ${isoWeek(a)}, ${fmt(a, { day: "numeric", month: "short" })} – ${fmt(z, { day: "numeric", month: "short" })}`
      : `W${isoWeek(a)}`;
  }
  return long ? fmt(a, { weekday: "long", day: "numeric", month: "long" }) : String(a.getDate());
}

/** A round top for the scale: 1, 2 or 5 of a power of ten (in the unit fmtBytes would use). */
function niceTop(n: number): number {
  if (n <= 0) return 1;
  const unit = 1024 ** Math.min(4, Math.floor(Math.log(n) / Math.log(1024)));
  const v = n / unit;
  const p = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 5, 10].find((s) => s * p >= v) ?? 10;
  return step * p * unit;
}

const kindLine = (k: Kinds) => Object.entries(k).filter(([, n]) => n > 0).sort((x, y) => y[1] - x[1])
  .map(([kind, n]) => `${KIND_NAMES[kind] ?? kind} ${fmtBytes(n)}`).join(" · ");

export function Data() {
  const [by, setBy] = useState<By>("day");
  const [pick, setPick] = useState<{ start: string; end: string; title: string } | null>(null);
  const sum = useQuery({ queryKey: ["admin-data", by], queryFn: () => api.get<Summary>("/api/admin/data", { by }), refetchInterval: 30000 });
  const s = sum.data;
  const today = s?.now.find((p) => p.key === "today");
  const sel = pick ?? (today ? { start: today.start, end: today.end, title: "Today so far" } : null);
  const devs = useQuery({
    queryKey: ["admin-data-devices", sel?.start, sel?.end], enabled: !!sel, refetchInterval: 30000,
    queryFn: () => api.get<Device[]>("/api/admin/data/devices", { start: sel!.start, end: sel!.end }),
  });
  if (!s) return <Loading />;
  const selKinds = [...s.now, ...s.periods].find((p) => p.start === sel?.start && p.end === sel?.end)?.kinds
    ?? (devs.data ? devs.data.reduce<Kinds>((acc, d) => {
      for (const [k, n] of Object.entries(d.kinds)) acc[k] = (acc[k] || 0) + n;
      return acc;
    }, {}) : {});
  const selTotal = Object.values(selKinds).reduce((a, b) => a + b, 0);
  const top = niceTop(Math.max(...s.periods.map((p) => p.bytes)));
  const now = todayIso();
  const devMax = Math.max(1, ...(devs.data || []).map((d) => d.bytes));

  return (
    <>
      <section className="panel">
        <div className="panel-head"><div className="h3">Data sent out</div></div>
        <p className="dim" style={{ marginTop: 0 }}>
          Everything this server sends: songs and other audio, covers, and the app's own pages and lists. Pick a
          figure or a bar to see what it was and which devices it went to.
        </p>
        <div className="kv data-now">
          {s.now.map((p) => (
            <button key={p.key} className={`stat stat-link ${sel?.start === p.start && sel?.end === p.end ? "on" : ""}`}
                    onClick={() => setPick({ start: p.start, end: p.end, title: p.label })}>
              <div className="v">{fmtBytes(p.bytes)}</div>
              <div className="k">{p.label}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div className="h3">{{ day: "Day by day", week: "Week by week", month: "Month by month" }[by]}</div>
          <div className="seg" role="radiogroup" aria-label="Show by">
            {BY.map(([b, label]) => (
              <button key={b} role="radio" aria-checked={by === b} className={by === b ? "on" : ""} onClick={() => setBy(b)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="data-chart">
          <div className="data-scale" aria-hidden>
            <span style={{ bottom: "100%" }}>{fmtBytes(top)}</span>
            <span style={{ bottom: "50%" }}>{fmtBytes(top / 2)}</span>
            <span style={{ bottom: 0 }}>0</span>
          </div>
          <div className="data-bars">
            {s.periods.map((p) => {
              const on = sel?.start === p.start && sel?.end === p.end;
              const going = p.start <= now && now <= p.end;
              const title = name(p, by) + (going ? " (so far)" : "");
              return (
                <button key={p.start} className={`data-bar ${on ? "on" : ""}`} aria-pressed={on}
                        aria-label={`${title}: ${fmtBytes(p.bytes)}`}
                        data-tip={`${title}: ${fmtBytes(p.bytes)}${p.bytes ? ` · ${kindLine(p.kinds)}` : ""}`}
                        onClick={() => setPick({ start: p.start, end: p.end, title })}>
                  <span className="data-fill" style={{ height: `${(p.bytes / top) * 100}%` }} />
                  <span className="data-label">
                    {name(p, by, false)}
                    {by === "day" && <small>{fmt(day(p.start), { weekday: "short" })}</small>}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {sel && (
        <section className="panel">
          <div className="panel-head"><div className="h3">{sel.title}: {fmtBytes(selTotal)}</div></div>
          {selTotal === 0 ? <Empty title="Nothing sent" /> : (
            <>
              <div className="data-kinds">
                {Object.entries(selKinds).filter(([, n]) => n > 0).sort((x, y) => y[1] - x[1]).map(([k, n]) => (
                  <div key={k} className="data-row">
                    <span className="data-what">{KIND_NAMES[k] ?? k}</span>
                    <span className="data-meter"><span style={{ width: `${(n / selTotal) * 100}%` }} /></span>
                    <span className="data-amount">{fmtBytes(n)}</span>
                  </div>
                ))}
              </div>
              <div className="h3" style={{ margin: "22px 0 10px" }}>By device</div>
              {!devs.data ? <Loading /> : (
                <div className="data-devices">
                  {devs.data.map((d) => (
                    <div key={`${d.user}|${d.device}`} className="data-row">
                      <span className="data-what">
                        <b className="ellipsis">{d.device || (d.user ? "A device without a name" : "Not signed in")}</b>
                        <span className="faint ellipsis">{d.user ? `${d.user} · ` : ""}{kindLine(d.kinds)}</span>
                      </span>
                      <span className="data-meter"><span style={{ width: `${(d.bytes / devMax) * 100}%` }} /></span>
                      <span className="data-amount">{fmtBytes(d.bytes)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      )}
    </>
  );
}
