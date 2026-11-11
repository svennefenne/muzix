/** Each account's icon (backend api/me.py): a picture of its own, cropped to a circle here and kept
 * as a small WebP by the server, or a letter or two on a colour; until it's changed, the first
 * letter of the name on the scheme's colours. */

import { ImagePlus, RotateCcw } from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useUi } from "../store/ui";
import type { AvatarLook } from "../types";
import { Modal } from "./ui";

// a dozen colours that read well in light and dark, and in every scheme around them
const COLORS = ["#e8dcc0", "#f2a93b", "#c4553a", "#5f9e6e", "#4a7fc1", "#7a5f8f",
  "#e05f8a", "#2bb3a8", "#9bc53d", "#f26b38", "#3d4f7a", "#1c1c1c"];

/** Black or white on this colour, whichever reads better. */
function inkOn(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.32 ? "#111" : "#fff";
}

export function Avatar({ user, className = "" }: { user: { username: string; avatar?: AvatarLook } | null; className?: string }) {
  const look = user?.avatar;
  if (look?.picture) {
    return <span className={`avatar pic ${className}`}><img src={look.picture} alt="" draggable={false} /></span>;
  }
  const letter = look?.letter || (user?.username || "?")[0].toUpperCase();
  const style = look?.color ? { background: look.color, color: inkOn(look.color) } : undefined;
  return <span className={`avatar ${className}`} style={style} data-long={Array.from(letter).length > 1 || undefined}>{letter}</span>;
}

/** Settings → Your icon. */
export function AvatarSettings() {
  const user = useUi((s) => s.user);
  const notify = useUi((s) => s.notify);
  const [letter, setLetter] = useState("");
  const [picked, setPicked] = useState<string | null>(null);   // a picture chosen, to crop
  const file = useRef<File | null>(null);
  const look = user?.avatar;
  useEffect(() => setLetter(look?.letter || ""), [look?.letter]);
  if (!user) return null;

  const saved = (avatar: AvatarLook) => useUi.setState({ user: { ...user, avatar } });
  const put = async (body: Partial<AvatarLook>) => {
    try {
      saved(await api.put<AvatarLook>("/api/me/avatar", body));
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const color = look?.picture ? null : look?.color ?? null;
  const shown = Array.from(letter.trim()).slice(0, 2).join("") || user.username[0].toUpperCase();
  return (
    <section className="panel">
      <div className="panel-head"><div><div className="kicker">Account</div><div className="h2">Your icon</div></div></div>
      <div className="avatar-settings">
        <Avatar user={user} className="big" />
        <div className="avatar-choices">
          <div className="row-actions">
            <label className="btn">
              <ImagePlus size={16} /> {look?.picture ? "Another picture" : "Upload a picture"}
              <input type="file" accept="image/*" hidden onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                file.current = f;
                setPicked(URL.createObjectURL(f));
              }} />
            </label>
            {(look?.picture || look?.color || look?.letter !== user.username[0].toUpperCase()) && (
              <button className="btn ghost" onClick={async () => saved(await api.del<AvatarLook>("/api/me/avatar"))}>
                <RotateCcw size={15} /> As it was
              </button>
            )}
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Or a letter on a colour</label>
            <div className="row-actions">
              <input className="input avatar-letter" value={letter} maxLength={8} aria-label="Letters on your icon"
                     placeholder={user.username[0].toUpperCase()}
                     onChange={(e) => setLetter(Array.from(e.target.value).slice(0, 2).join(""))}
                     onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                     onBlur={() => letter !== (look?.letter || "") && put({ letter: shown, color: color ?? undefined })} />
              <div className="avatar-swatches" role="radiogroup" aria-label="Colour">
                {COLORS.map((c) => (
                  <button key={c} role="radio" aria-checked={color === c} aria-label={c} className={color === c ? "on" : ""}
                          style={{ background: c }} onClick={() => put({ letter: shown, color: c })} />
                ))}
                <label className="avatar-own-color" data-tip="A colour of your own">
                  <input type="color" value={color || "#888888"} aria-label="A colour of your own"
                         onChange={(e) => put({ letter: shown, color: e.target.value })} />
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>
      {picked && file.current && (
        <CropPicture src={picked} file={file.current} onClose={() => { URL.revokeObjectURL(picked); setPicked(null); }}
                     onSaved={(a) => { saved(a); notify("Your new icon is saved"); }} />
      )}
    </section>
  );
}

const STAGE = 260;

/** Drag the picture and zoom it until the circle shows what it should. */
function CropPicture({ src, file, onClose, onSaved }: { src: string; file: File; onClose: () => void; onSaved: (a: AvatarLook) => void }) {
  const notify = useUi((s) => s.notify);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [at, setAt] = useState({ x: 0.5, y: 0.5 });      // the circle's centre, as fractions of the picture
  const [saving, setSaving] = useState(false);
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);

  // the square the circle covers, in the picture's pixels
  const side = size ? Math.min(size.w, size.h) / zoom : 1;
  const scale = STAGE / side;
  const clamp = (v: number, total: number) => Math.min(Math.max(v, side / 2 / total), 1 - side / 2 / total);
  const centre = size ? { x: clamp(at.x, size.w), y: clamp(at.y, size.h) } : at;

  const down = (e: ReactPointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { px: e.clientX, py: e.clientY, ...centre };
  };
  const move = (e: ReactPointerEvent) => {
    if (!drag.current || !size) return;
    const d = drag.current;
    // kept inside the picture as it's dragged, so zooming afterwards starts from what shows
    setAt({ x: clamp(d.x - (e.clientX - d.px) / scale / size.w, size.w), y: clamp(d.y - (e.clientY - d.py) / scale / size.h, size.h) });
  };
  const save = async () => {
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("x", String(centre.x));
      fd.append("y", String(centre.y));
      fd.append("size", String(1 / zoom));
      const up = await api.post<{ picture: string }>("/api/me/avatar/picture", fd);
      onSaved(await api.put<AvatarLook>("/api/me/avatar", { picture: up.picture }));
      onClose();
    } catch (e) {
      notify((e as Error).message, "error");
      setSaving(false);
    }
  };
  return (
    <Modal onClose={onClose} className="avatar-crop">
      <div className="kicker">Your icon</div>
      <h2 className="h2">Crop your picture</h2>
      <p className="dim" style={{ margin: "8px 0 16px" }}>Drag the picture and zoom until the circle shows what it should.</p>
      <div className="crop-stage" style={{ width: STAGE, height: STAGE }} onPointerDown={down} onPointerMove={move}
           onPointerUp={() => (drag.current = null)} onPointerCancel={() => (drag.current = null)}
           onWheel={(e) => setZoom((z) => Math.min(Math.max(z * (e.deltaY < 0 ? 1.1 : 1 / 1.1), 1), 6))}>
        <img src={src} alt="" draggable={false} onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
             style={size ? { width: size.w * scale, height: size.h * scale,
                             left: STAGE / 2 - centre.x * size.w * scale, top: STAGE / 2 - centre.y * size.h * scale } : { opacity: 0 }} />
        <span className="crop-ring" aria-hidden />
      </div>
      <label className="crop-zoom">
        <span className="seg-label">Zoom</span>
        <input type="range" min={1} max={6} step={0.01} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} aria-label="Zoom" />
      </label>
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 20 }}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn accent" disabled={saving || !size} onClick={save}>{saving ? "Saving…" : "Use it"}</button>
      </div>
    </Modal>
  );
}
