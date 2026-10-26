/** A crash shows what went wrong and a way back instead of a blank screen, and every
 * error (crash or not) is reported to the server so it lands in Muzix's log. */

import { Component, type ReactNode } from "react";

let sent = 0;

export function report(kind: string, error: unknown, extra = "") {
  if (sent++ > 20) return;   // one bad loop shouldn't flood the log
  const e = error instanceof Error ? error : new Error(String(error));
  const stack = error instanceof Error ? e.stack || "" : "";     // a message's own stack would only point here
  fetch("/api/client-errors", {
    method: "POST", credentials: "same-origin", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, message: e.message, stack: `${stack}${extra}`.slice(0, 6000), url: location.href }),
  }).catch(() => {});
}

/** Errors outside React's rendering (event handlers, promises, third-party scripts). */
export function reportGlobalErrors() {
  window.addEventListener("error", (e) => report("error", e.error ?? e.message));
  window.addEventListener("unhandledrejection", (e) => report("promise", e.reason));
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    report("render", error, `\n--- components ---${info.componentStack || ""}`);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // going to another page tries again
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="page crash" role="alert">
        <h1 className="h2">This page crashed</h1>
        <p className="lede">Something went wrong while showing it. The details went to Muzix's log; reloading usually helps.</p>
        <pre className="crash-detail">{error.message}</pre>
        <button className="btn accent" onClick={() => location.reload()}>Reload</button>
      </div>
    );
  }
}
