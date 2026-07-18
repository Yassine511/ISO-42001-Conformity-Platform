import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "../components/theme-provider";
import { AuthProvider, RequireAuth } from "../auth";
import LoginPage from "../pages/LoginPage";
import LandingPage from "../pages/LandingPage";
import type { SessionInfo } from "../api";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      me: vi.fn(),
      login: vi.fn(),
    },
  };
});

import { api } from "../api";
const mocked = api as unknown as {
  me: ReturnType<typeof vi.fn>;
  login: ReturnType<typeof vi.fn>;
};

const SESSION: SessionInfo = {
  user: { id: "u1", email: "alice@lumen.fr", display_name: "Alice" },
  organizations: [{ id: "org-1", name: "Lumen SA", created_at: "2026-07-16T10:00:00Z" }],
};

function renderAuthed(ui: React.ReactElement, route = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[route]}>
          <AuthProvider>{ui}</AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RequireAuth", () => {
  it("redirects an anonymous visitor to /login", async () => {
    mocked.me.mockRejectedValue(new Error("Authentification requise."));
    renderAuthed(
      <Routes>
        <Route path="/login" element={<p>Page de connexion</p>} />
        <Route
          path="/organizations/:orgId"
          element={
            <RequireAuth>
              <p>Espace protégé</p>
            </RequireAuth>
          }
        />
      </Routes>,
      "/organizations/org-1",
    );
    expect(await screen.findByText("Page de connexion")).toBeInTheDocument();
    expect(screen.queryByText("Espace protégé")).not.toBeInTheDocument();
  });

  it("renders the protected content for a signed-in user", async () => {
    mocked.me.mockResolvedValue(SESSION);
    renderAuthed(
      <Routes>
        <Route
          path="/organizations/:orgId"
          element={
            <RequireAuth>
              <p>Espace protégé</p>
            </RequireAuth>
          }
        />
      </Routes>,
      "/organizations/org-1",
    );
    expect(await screen.findByText("Espace protégé")).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  it("submits credentials and navigates to the user's organization", async () => {
    mocked.me.mockRejectedValue(new Error("Authentification requise."));
    mocked.login.mockResolvedValue(SESSION);
    renderAuthed(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/organizations/:orgId" element={<p>Tableau de bord org-1</p>} />
      </Routes>,
      "/login",
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Adresse e-mail"), "alice@lumen.fr");
    await user.type(screen.getByLabelText("Mot de passe"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    await waitFor(() =>
      expect(mocked.login).toHaveBeenCalledWith("alice@lumen.fr", "correct horse battery"),
    );
    expect(await screen.findByText("Tableau de bord org-1")).toBeInTheDocument();
  });

  it("surfaces the French error on bad credentials", async () => {
    mocked.me.mockRejectedValue(new Error("Authentification requise."));
    mocked.login.mockRejectedValue(new Error("Identifiants invalides."));
    renderAuthed(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>,
      "/login",
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Adresse e-mail"), "alice@lumen.fr");
    await user.type(screen.getByLabelText("Mot de passe"), "mauvais mot de passe");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiants invalides.");
  });
});

describe("LandingPage", () => {
  it("shows signup/login CTAs to anonymous visitors", async () => {
    mocked.me.mockRejectedValue(new Error("Authentification requise."));
    renderAuthed(
      <Routes>
        <Route path="/" element={<LandingPage />} />
      </Routes>,
    );
    expect(
      await screen.findByRole("heading", { name: /L'humain confirme\./ }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Créer/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Se connecter" }).length).toBeGreaterThan(0);
  });

  it("shows the open-app CTA to a signed-in user", async () => {
    mocked.me.mockResolvedValue(SESSION);
    renderAuthed(
      <Routes>
        <Route path="/" element={<LandingPage />} />
      </Routes>,
    );
    const links = await screen.findAllByRole("link", { name: /Ouvrir l'application/ });
    expect(links[0]).toHaveAttribute("href", "/organizations/org-1");
    expect(screen.queryByRole("link", { name: "Créer un compte" })).not.toBeInTheDocument();
  });
});
