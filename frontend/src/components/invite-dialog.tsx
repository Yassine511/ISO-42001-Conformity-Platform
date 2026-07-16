import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
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

/** Invite a teammate by link (no e-mail server): the API returns the raw
    token exactly once; we render the full URL for copy-paste and it is never
    retrievable again — closing the dialog discards it. */
export function InviteDialog({
  orgId,
  open,
  onOpenChange,
}: {
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [email, setEmail] = useState("");
  const [copied, setCopied] = useState(false);

  const invite = useMutation({
    mutationFn: (address: string) => api.createInvitation(orgId, address),
  });

  const inviteUrl = invite.data
    ? `${window.location.origin}/invitation/${invite.data.invite_token}`
    : null;

  const close = (next: boolean) => {
    if (!next) {
      setEmail("");
      setCopied(false);
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

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Inviter un membre</DialogTitle>
          <DialogDescription>
            {inviteUrl
              ? "Transmettez ce lien à votre collègue. Il est affiché une seule fois et expire dans 7 jours."
              : "Générez un lien d'invitation à transmettre à votre collègue."}
          </DialogDescription>
        </DialogHeader>

        {inviteUrl ? (
          <div className="space-y-3">
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
              Invitation pour {invite.data?.email}.
            </p>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
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
            </div>
            {invite.isError && (
              <p role="alert" className="text-sm text-destructive">
                {(invite.error as Error).message}
              </p>
            )}
            <Button type="submit" className="h-10 w-full" disabled={invite.isPending}>
              {invite.isPending ? "Génération…" : "Générer le lien d'invitation"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
