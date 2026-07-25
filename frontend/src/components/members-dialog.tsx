import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, UserMinus, X } from "lucide-react";
import { api } from "../api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

/** Members of the organization: who has access, which invitations are
    outstanding, and how to end either.

    Every member is equal by design (the membership table has no role column),
    so any member may invite and remove any other — including themselves. The
    backend refuses only one thing: removing the LAST member, which would leave
    the organization and its data permanently unreachable.

    Invite links are shown exactly once, at creation: only the token's sha256 is
    stored, so a pending invitation can be revoked but never re-displayed. */
export function MembersDialog({
  orgId,
  open,
  onOpenChange,
  onSelfRemoved,
}: {
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after the caller removes THEMSELVES: every route of this org now
      404s for them, so the parent must navigate away instead of refetching. */
  onSelfRemoved?: () => void;
}) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [copied, setCopied] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const members = useQuery({
    queryKey: ["members", orgId],
    queryFn: () => api.listMembers(orgId),
    enabled: open,
  });
  const invitations = useQuery({
    queryKey: ["invitations", orgId],
    queryFn: () => api.listInvitations(orgId),
    enabled: open,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["members", orgId] });
    queryClient.invalidateQueries({ queryKey: ["invitations", orgId] });
  };

  const invite = useMutation({
    mutationFn: (address: string) => api.createInvitation(orgId, address),
    onSuccess: () => {
      setEmail("");
      refresh();
    },
  });
  // The backend refuses the last removal (409) and unknown members (404) —
  // those refusals must be visible, never swallowed.
  const remove = useMutation({
    mutationFn: (userId: string) => api.removeMember(orgId, userId),
    onSuccess: (_data, userId) => {
      setConfirmRemove(null);
      setActionError(null);
      // Removing yourself means this org's routes all 404 for you from now
      // on — refetching would only render dead error states. Close and let
      // the parent navigate somewhere you still belong.
      if (members.data?.find((m) => m.user_id === userId)?.is_self) {
        onOpenChange(false);
        onSelfRemoved?.();
        return;
      }
      refresh();
    },
    onError: (err) => setActionError((err as Error).message),
  });
  const revoke = useMutation({
    mutationFn: (invitationId: string) => api.revokeInvitation(orgId, invitationId),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err) => setActionError((err as Error).message),
  });

  const inviteUrl = invite.data
    ? `${window.location.origin}/invitation/${invite.data.invite_token}`
    : null;

  const close = (next: boolean) => {
    if (!next) {
      setEmail("");
      setCopied(false);
      setConfirmRemove(null);
      setActionError(null);
      invite.reset();
    }
    onOpenChange(next);
  };

  const copy = async () => {
    if (!inviteUrl) return;
    await navigator.clipboard.writeText(inviteUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const memberList = members.data ?? [];
  const pending = invitations.data ?? [];
  const isLast = memberList.length <= 1;

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Membres de l'organisation</DialogTitle>
          <DialogDescription>
            Tout membre a le même accès à l'ensemble des preuves, constats et
            échanges de l'organisation.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-5 overflow-y-auto">
          {actionError && (
            <p role="alert" className="text-sm text-destructive">
              {actionError}
            </p>
          )}

          {/* ---- current members */}
          <section className="space-y-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Membres ({memberList.length})
            </h3>
            {members.isPending ? (
              <p className="text-sm text-muted-foreground">Chargement…</p>
            ) : (
              <ul className="divide-y overflow-hidden rounded-lg border">
                {memberList.map((m) => (
                  <li key={m.user_id} className="flex items-center gap-3 p-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold uppercase text-ink-foreground">
                      {m.display_name.slice(0, 1)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium">
                        {m.display_name}
                        {m.is_self && (
                          <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                            (vous)
                          </span>
                        )}
                      </div>
                      <div className="truncate font-mono text-xs text-muted-foreground">
                        {m.email}
                      </div>
                    </div>
                    {confirmRemove === m.user_id ? (
                      <span className="flex shrink-0 items-center gap-2 text-xs">
                        {m.is_self ? "Quitter ?" : "Retirer ?"}
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={remove.isPending}
                          onClick={() => remove.mutate(m.user_id)}
                        >
                          Confirmer
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setConfirmRemove(null)}
                        >
                          Non
                        </Button>
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        disabled={isLast}
                        title={
                          isLast
                            ? "Le dernier membre ne peut pas être retiré : l'organisation deviendrait inaccessible."
                            : undefined
                        }
                        onClick={() => {
                          setActionError(null);
                          setConfirmRemove(m.user_id);
                        }}
                      >
                        <UserMinus className="size-3.5" aria-hidden="true" />
                        {m.is_self ? "Quitter" : "Retirer"}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {isLast && !members.isPending && (
              <p className="text-xs text-muted-foreground">
                Vous êtes seul·e membre : invitez quelqu'un avant de pouvoir quitter
                l'organisation.
              </p>
            )}
          </section>

          {/* ---- outstanding invitations */}
          {pending.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Invitations en attente ({pending.length})
              </h3>
              <ul className="divide-y overflow-hidden rounded-lg border">
                {pending.map((inv) => (
                  <li key={inv.id} className="flex items-center gap-3 p-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-mono text-[13px]">{inv.email}</div>
                      <div className="text-xs text-muted-foreground">
                        {inv.expired
                          ? "Expirée"
                          : `Expire le ${new Date(inv.expires_at).toLocaleDateString("fr-FR")}`}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate(inv.id)}
                    >
                      <X className="size-3.5" aria-hidden="true" />
                      Révoquer
                    </Button>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                Le lien d'invitation n'est affiché qu'une fois : il ne peut pas être
                retrouvé, seulement révoqué puis régénéré.
              </p>
            </section>
          )}

          <Separator />

          {/* ---- invite */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Inviter
            </h3>
            {inviteUrl ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Input
                    readOnly
                    value={inviteUrl}
                    onFocus={(e) => e.currentTarget.select()}
                    aria-label="Lien d'invitation"
                    className="h-10 font-mono text-xs"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-10 w-10 shrink-0"
                    onClick={copy}
                    aria-label="Copier le lien"
                  >
                    {copied ? (
                      <Check className="size-4" aria-hidden="true" />
                    ) : (
                      <Copy className="size-4" aria-hidden="true" />
                    )}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Transmettez ce lien à {invite.data?.email}. Il est affiché une seule
                  fois et expire dans 7 jours.
                </p>
                <Button variant="outline" size="sm" onClick={() => invite.reset()}>
                  Inviter quelqu'un d'autre
                </Button>
              </div>
            ) : (
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  setActionError(null);
                  if (email.trim()) invite.mutate(email.trim());
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="invite-email">Adresse e-mail du collègue</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="collegue@entreprise.fr"
                    className="h-10"
                  />
                  <p className="text-xs text-muted-foreground">
                    Si cette personne a déjà un compte, elle rejoindra cette
                    organisation en se connectant.
                  </p>
                </div>
                {invite.isError && (
                  <p role="alert" className="text-sm text-destructive">
                    {(invite.error as Error).message}
                  </p>
                )}
                <Button type="submit" className="h-10 w-full" disabled={invite.isPending}>
                  {invite.isPending && (
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  )}
                  {invite.isPending ? "Génération…" : "Générer le lien d'invitation"}
                </Button>
              </form>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
