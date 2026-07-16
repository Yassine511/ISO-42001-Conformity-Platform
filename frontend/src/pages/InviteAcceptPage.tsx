import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { homeOf, useAuth } from "../auth";
import { AuthFrame } from "@/components/auth-frame";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Accept an invitation link: the e-mail is fixed by the invitation; the
    invitee only chooses their name and password. */
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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const session = await acceptInvitation(token, form);
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
        <></>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      title={`Rejoindre ${info.data.organization_name}`}
      subtitle={`Créez votre compte pour ${info.data.email}.`}
    >
      <form className="space-y-4" onSubmit={submit}>
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
        <div className="space-y-2">
          <Label htmlFor="password">Mot de passe</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="h-10"
          />
          <p className="text-xs text-muted-foreground">10 caractères minimum.</p>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="h-10 w-full" disabled={pending}>
          {pending ? "Création…" : "Rejoindre l'organisation"}
        </Button>
      </form>
    </AuthFrame>
  );
}
