import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./helpers";
import type { OrganizationMember, PendingInvitation } from "../api";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listMembers: vi.fn(),
      listInvitations: vi.fn(),
      createInvitation: vi.fn(),
      removeMember: vi.fn(),
      revokeInvitation: vi.fn(),
    },
  };
});

import { api } from "../api";
import { MembersDialog } from "../components/members-dialog";

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const ALICE: OrganizationMember = {
  user_id: "u1",
  email: "alice@lumen.fr",
  display_name: "Alice",
  joined_at: "2026-07-01T10:00:00Z",
  is_self: true,
};
const BOB: OrganizationMember = {
  user_id: "u2",
  email: "bob@lumen.fr",
  display_name: "Bob",
  joined_at: "2026-07-05T10:00:00Z",
  is_self: false,
};
const INVITE: PendingInvitation = {
  id: "inv-1",
  email: "carol@lumen.fr",
  created_at: "2026-07-20T10:00:00Z",
  expires_at: "2026-07-27T10:00:00Z",
  expired: false,
};

function open() {
  return renderWithProviders(
    <MembersDialog orgId="org-1" open onOpenChange={() => {}} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listMembers.mockResolvedValue([ALICE, BOB]);
  mocked.listInvitations.mockResolvedValue([]);
});

describe("MembersDialog", () => {
  it("lists members and marks the caller", async () => {
    open();
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("(vous)")).toBeInTheDocument();
    expect(screen.getByText("bob@lumen.fr")).toBeInTheDocument();
    expect(screen.getByText(/Membres \(2\)/)).toBeInTheDocument();
  });

  it("removes a member only after an explicit confirmation", async () => {
    mocked.removeMember.mockResolvedValue(undefined);
    const user = userEvent.setup();
    open();

    await user.click(await screen.findByRole("button", { name: /Retirer/ }));
    expect(mocked.removeMember).not.toHaveBeenCalled(); // first click only arms it

    await user.click(screen.getByRole("button", { name: "Confirmer" }));
    await waitFor(() => expect(mocked.removeMember).toHaveBeenCalledWith("org-1", "u2"));
  });

  it("closes and hands off navigation when the caller removes themselves", async () => {
    // after leaving, every route of this org 404s for the caller — refetching
    // the dialog's own queries would only render dead error states
    mocked.removeMember.mockResolvedValue(undefined);
    const onOpenChange = vi.fn();
    const onSelfRemoved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <MembersDialog
        orgId="org-1"
        open
        onOpenChange={onOpenChange}
        onSelfRemoved={onSelfRemoved}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Quitter/ }));
    await user.click(screen.getByRole("button", { name: "Confirmer" }));

    await waitFor(() => expect(mocked.removeMember).toHaveBeenCalledWith("org-1", "u1"));
    await waitFor(() => expect(onSelfRemoved).toHaveBeenCalled());
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mocked.listMembers).toHaveBeenCalledTimes(1); // no dead refetch
  });

  it("surfaces the backend refusal instead of swallowing it", async () => {
    mocked.removeMember.mockRejectedValue(
      new Error("Impossible de retirer le dernier membre : …"),
    );
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: /Retirer/ }));
    await user.click(screen.getByRole("button", { name: "Confirmer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/dernier membre/);
  });

  it("disables removal when a single member is left — leaving would strand the org", async () => {
    mocked.listMembers.mockResolvedValue([ALICE]);
    open();
    expect(await screen.findByRole("button", { name: /Quitter/ })).toBeDisabled();
    expect(screen.getByText(/seul·e membre/)).toBeInTheDocument();
  });

  it("lists pending invitations and revokes them", async () => {
    mocked.listInvitations.mockResolvedValue([INVITE]);
    mocked.revokeInvitation.mockResolvedValue(undefined);
    const user = userEvent.setup();
    open();

    expect(await screen.findByText("carol@lumen.fr")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Révoquer/ }));
    await waitFor(() =>
      expect(mocked.revokeInvitation).toHaveBeenCalledWith("org-1", "inv-1"),
    );
  });

  it("shows the invite link exactly once and says an existing account can join", async () => {
    mocked.createInvitation.mockResolvedValue({
      invite_token: "raw-token-abc",
      email: "dan@lumen.fr",
      expires_at: "2026-08-01T10:00:00Z",
    });
    const user = userEvent.setup();
    open();

    // the copy that closes the multi-org gap must be visible before inviting
    expect(
      await screen.findByText(/déjà un compte, elle rejoindra cette/),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Adresse e-mail/), "dan@lumen.fr");
    await user.click(screen.getByRole("button", { name: /Générer le lien/ }));

    const link = await screen.findByLabelText("Lien d'invitation");
    expect((link as HTMLInputElement).value).toContain("/invitation/raw-token-abc");
    expect(screen.getByText(/affiché une seule fois/)).toBeInTheDocument();
  });

  it("refuses a duplicate invite visibly", async () => {
    mocked.createInvitation.mockRejectedValue(
      new Error("Cette personne est déjà membre de l'organisation."),
    );
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText(/Adresse e-mail/), "bob@lumen.fr");
    await user.click(screen.getByRole("button", { name: /Générer le lien/ }));
    const alerts = await screen.findAllByRole("alert");
    expect(within(alerts[0]).getByText(/déjà membre/)).toBeInTheDocument();
  });
  // ---------------------------------------------------------------- F6

  /** Swap navigator.clipboard AFTER userEvent.setup(): user-event v14 installs
      its own clipboard stub during setup, which would otherwise put the API
      back and hide exactly the condition under test. Returns the restore fn. */
  function withClipboard(value: unknown) {
    const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { value, configurable: true });
    return () => {
      if (original) Object.defineProperty(navigator, "clipboard", original);
      else Reflect.deleteProperty(navigator, "clipboard");
    };
  }

  async function generateLink(user: ReturnType<typeof userEvent.setup>) {
    mocked.createInvitation.mockResolvedValue({
      invite_token: "raw-token-abc",
      email: "dan@lumen.fr",
      expires_at: "2026-08-01T10:00:00Z",
    });
    open();
    await user.type(await screen.findByLabelText(/Adresse e-mail/), "dan@lumen.fr");
    await user.click(screen.getByRole("button", { name: /Générer le lien/ }));
    return await screen.findByRole("button", { name: "Copier le lien" });
  }

  it("tells the user when the browser refuses the clipboard instead of failing mute", async () => {
    // Audit pass 5 (F6): navigator.clipboard exists only in a SECURE CONTEXT,
    // and this app ships on plain HTTP by design — served from anything but
    // localhost the property is undefined, the await threw an unhandled
    // rejection, and the button gave no feedback at all on a link the UI
    // states is shown exactly once.
    const user = userEvent.setup();
    const button = await generateLink(user);
    const restore = withClipboard(undefined);
    try {
      await user.click(button);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/Copie automatique indisponible/);
      expect(alert).toHaveTextContent(/HTTPS/);
      // the link stays selectable — that IS the recovery the message points to
      const link = screen.getByLabelText("Lien d'invitation") as HTMLInputElement;
      expect(link.value).toContain("/invitation/raw-token-abc");
      expect(link).toHaveAttribute("readonly");
    } finally {
      restore();
    }
  });

  it("copies the link and confirms when the clipboard is available", async () => {
    const user = userEvent.setup();
    const button = await generateLink(user);
    const writeText = vi.fn().mockResolvedValue(undefined);
    const restore = withClipboard({ writeText });
    try {
      await user.click(button);

      await waitFor(() =>
        expect(writeText).toHaveBeenCalledWith(
          expect.stringContaining("/invitation/raw-token-abc"),
        ),
      );
      expect(screen.queryByText(/Copie automatique indisponible/)).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
