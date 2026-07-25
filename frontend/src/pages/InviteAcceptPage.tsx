import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Check, CircleX, Clock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { homeOf, useAuth } from "../auth";
import { AuthFrame } from "@/components/auth-frame";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Accept an invitation link. The e-mail is fixed by the invitation, and the
    form follows `account_exists`:
    - no account yet -> sign UP: choose a name and a new password;
    - account exists  -> sign IN: the password authenticates the existing
      account and only adds the membership, which is how someone joins a
      second organization. */
export default function InviteAcceptPage() {
  const { token = "" } = useParams<{ token: string }>();
  const { acceptInvitation } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ display_name: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const info = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api.invitationInfo(token),
    retry: false,
  });
  const joining = info.data?.account_exists ?? false;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const session = await acceptInvitation(
        token,
        joining
          ? { password: form.password }
          : { password: form.password, display_name: form.display_name },
      );
      navigate(homeOf(session.organizations), { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };

  if (info.isLoading) {
    return (
      <AuthFrame title="Invitation">
        <p className="text-center text-sm text-muted-foreground" aria-live="polite">
          Vérification de l'invitation…
        </p>
      </AuthFrame>
    );
  }

  if (info.isError || !info.data) {
    return (
      <AuthFrame
        title="Invitation introuvable"
        subtitle="Ce lien d'invitation est invalide ou a déjà été utilisé."
        footer={
          <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
            Aller à la connexion
          </Link>
        }
      >
        <></>
      </AuthFrame>
    );
  }

  if (info.data.expired) {
    return (
      <AuthFrame
        title="Invitation expirée"
        subtitle={`L'invitation à rejoindre ${info.data.organization_name} a expiré. Demandez un nouveau lien à un membre de l'organisation.`}
      >
        <div className="flex flex-col items-center text-center">
          <span className="flex size-13 items-center justify-center rounded-[14px] border bg-muted text-muted-foreground">
            <Clock className="size-6" aria-hidden="true" />
          </span>
          <Button asChild variant="outline" className="mt-6 h-10">
            <Link to="/login">Retour à la connexion</Link>
          </Button>
        </div>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      title={`Rejoindre ${info.data.organization_name}`}
      subtitle={
        joining
          ? "Vous avez déjà un compte : connectez-vous pour ajouter cette organisation à votre espace."
          : "Vous avez été invité·e à rejoindre l'espace de conformité de cette organisation."
      }
      badge={
        <span className="inline-flex items-center gap-1.5 rounded-full border border-success/45 bg-success/15 px-2.5 py-0.5 text-[11.5px] font-semibold text-success">
          <Check className="size-3" strokeWidth={2.5} aria-hidden="true" />
          Invitation valide
        </span>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        {error && (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/[0.08] px-3.5 py-2.5 text-[12.5px] text-destructive"
          >
            <CircleX className="mt-px size-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="invite_email">Adresse e-mail</Label>
          <Input
            id="invite_email"
            type="email"
            value={info.data.email}
            readOnly
            disabled
            className="h-10"
          />
          <p className="text-xs text-muted-foreground">Pré-remplie par l'invitation.</p>
        </div>
        {/* an existing account keeps the name it already has */}
        {!joining && (
          <div className="space-y-2">
            <Label htmlFor="display_name">Votre nom</Label>
            <Input
              id="display_name"
              autoComplete="name"
              required
              value={form.display_name}
              onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
              placeholder="Prénom Nom"
              className="h-10"
            />
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="password">Mot de passe</Label>
          <Input
            id="password"
            type="password"
            autoComplete={joining ? "current-password" : "new-password"}
            required
            minLength={joining ? undefined : 10}
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="h-10"
          />
          <p className="text-xs text-muted-foreground">
            {joining
              ? "Celui de votre compte existant — il n'est pas modifié."
              : "10 caractères minimum."}
          </p>
        </div>
        <Button type="submit" className="h-10 w-full" disabled={pending}>
          {pending
            ? joining
              ? "Connexion…"
              : "Création…"
            : joining
              ? "Se connecter et rejoindre"
              : "Rejoindre l'organisation"}
        </Button>
      </form>
    </AuthFrame>
  );
}
