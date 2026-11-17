/** An audiobook's genre (a label in the genre's own hue, base.css) and language (outlined, in its own words). */

import type { ReactNode } from "react";
import type { Book } from "../types";

/** A language's own name for itself, capitalised: "English", "Svenska", "Deutsch". */
export function languageName(code: string) {
  if (!code) return "";
  try {
    const n = new Intl.DisplayNames([code], { type: "language" }).of(code) || code;
    return n.charAt(0).toLocaleUpperCase(code) + n.slice(1);
  } catch {
    return code.toUpperCase();
  }
}

export function GenreLabel({ genre }: { genre: string }) {
  return <span className="blabel genre" data-genre={genre || "Uncategorized"}>{genre || "Uncategorized"}</span>;
}

export function Labels({ b, children, big }: { b: Pick<Book, "genre" | "language">; children?: ReactNode; big?: boolean }) {
  return (
    <div className={`blabels ${big ? "big" : ""}`}>
      <GenreLabel genre={b.genre} />
      {b.language && <span className="blabel lang">{languageName(b.language)}</span>}
      {children}
    </div>
  );
}
