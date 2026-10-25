import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { queryClient } from "./actions";
import App from "./App";
import { ErrorBoundary, reportGlobalErrors } from "./components/ErrorBoundary";
import { note, startNavTrace } from "./navtrace";
import "./styles/fonts";
import "./styles/base.css";
import "./styles/skins.css";

reportGlobalErrors();
startNavTrace();
keepPhonesUpright();

/** Installed on a phone, Muzix stays upright; tablets turn freely. The manifest asks for it
 * on phones; this lock takes effect at once where the browser allows it. */
function keepPhonesUpright() {
  const o = screen.orientation as ScreenOrientation & { lock?: (o: "portrait") => Promise<void> };
  if (matchMedia("(display-mode: standalone)").matches && Math.min(screen.width, screen.height) < 600)
    o?.lock?.("portrait").then(() => note("orientation lock accepted"), (e) => note(`orientation lock refused: ${e?.name}`));
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      {/* page changes render straight away: as transitions, a back swipe in the installed app
          could leave the old page up while the address had already gone back */}
      <BrowserRouter useTransitions={false}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
