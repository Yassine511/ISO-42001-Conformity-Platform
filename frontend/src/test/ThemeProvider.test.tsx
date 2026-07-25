import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "../components/theme-provider";
import { ThemeToggle } from "../components/theme-toggle";

/** Audit pass 5 (F5). `resolvedTheme` was recomputed during render by calling
    matchMedia inline, while the change listener toggled the `dark` class
    imperatively — no state, so no re-render. The page followed the OS; the
    context did not. ThemeToggle reads `resolvedTheme` both to pick its icon
    and to compute the theme its next click sets. */

/** A controllable `prefers-color-scheme: dark` media query. The global stub in
    setup.ts is inert (matches: false, listeners dropped), which is exactly
    what let the old bug go unnoticed. */
function installMatchMedia(initialDark: boolean) {
  const listeners = new Set<() => void>();
  const state = { matches: initialDark };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      get matches() {
        return query.includes("prefers-color-scheme: dark") ? state.matches : false;
      },
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: (_event: string, cb: () => void) => listeners.add(cb),
      removeEventListener: (_event: string, cb: () => void) => listeners.delete(cb),
      dispatchEvent: vi.fn(),
    })),
  });
  return {
    setDark(next: boolean) {
      state.matches = next;
      act(() => listeners.forEach((cb) => cb()));
    },
    get listenerCount() {
      return listeners.size;
    },
  };
}

function Probe() {
  const { theme, resolvedTheme } = useTheme();
  return (
    <span data-testid="probe">
      {theme}/{resolvedTheme}
    </span>
  );
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

describe("ThemeProvider", () => {
  it("propagates an OS theme change to consumers, not only to the DOM", () => {
    const media = installMatchMedia(false);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("system/light");

    media.setDark(true);

    // the class was always updated; the CONTEXT is what used to go stale
    expect(document.documentElement).toHaveClass("dark");
    expect(screen.getByTestId("probe")).toHaveTextContent("system/dark");
  });

  it("keeps the toggle's first click meaningful after an OS change", async () => {
    const user = userEvent.setup();
    const media = installMatchMedia(false);
    render(
      <ThemeProvider>
        <ThemeToggle />
        <Probe />
      </ThemeProvider>,
    );

    media.setDark(true);
    // With a stale resolvedTheme the toggle computed next="dark" — setting the
    // theme the page already showed, so the first click did nothing visible.
    await user.click(screen.getByRole("button"));
    expect(screen.getByTestId("probe")).toHaveTextContent("light/light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("still tracks the OS after an explicit choice and a return to system", () => {
    const media = installMatchMedia(false);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    // the old effect unsubscribed whenever theme !== "system", so a change
    // that happened while an explicit theme was active was lost for good
    media.setDark(true);
    expect(screen.getByTestId("probe")).toHaveTextContent("system/dark");
  });

  it("removes its media listener on unmount", () => {
    const media = installMatchMedia(false);
    const { unmount } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(media.listenerCount).toBe(1);
    unmount();
    expect(media.listenerCount).toBe(0);
  });

  it("an explicit theme ignores the OS preference", () => {
    localStorage.setItem("int102-theme", "light");
    const media = installMatchMedia(true);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("light/light");
    media.setDark(false);
    expect(screen.getByTestId("probe")).toHaveTextContent("light/light");
  });
});
