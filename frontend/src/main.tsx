import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { queryClient } from "./actions";
import App from "./App";
import { ErrorBoundary, reportGlobalErrors } from "./components/ErrorBoundary";
import "./styles/fonts";
import "./styles/base.css";
import "./styles/skins.css";

reportGlobalErrors();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
