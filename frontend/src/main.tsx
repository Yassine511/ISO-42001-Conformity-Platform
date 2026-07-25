import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";
import App from "./App";
import { ApiError } from "./api";
import { AuthProvider } from "./auth";
import { ThemeProvider } from "@/components/theme-provider";
import { MotionRoot } from "@/components/motion";
// "Registre" type system: Instrument Sans (body/UI), Newsreader (serif
// headings), Spline Sans Mono (technical values — ids, offsets, counts).
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/instrument-sans/700.css";
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/600.css";
import "@fontsource/newsreader/400-italic.css";
// the landing hero's italic line is weight 500 — without this face the browser
// synthesises the slant off the upright instead of using Newsreader's italic
import "@fontsource/newsreader/500-italic.css";
import "@fontsource/spline-sans-mono/400.css";
import "@fontsource/spline-sans-mono/500.css";
import "@fontsource/spline-sans-mono/600.css";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Client errors are deterministic — a 401/404/409 answers identically on
      // every retry. The stock policy (3 retries) turned one expired session
      // into four 401s and four redirect events per query; server/network
      // errors still get one retry.
      retry: (failureCount, error) =>
        error instanceof ApiError && error.status >= 400 && error.status < 500
          ? false
          : failureCount < 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionRoot>
          <BrowserRouter>
            <AuthProvider>
              <App />
            </AuthProvider>
          </BrowserRouter>
        </MotionRoot>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
