import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { CircleX } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { AuthFrame } from "@/components/auth-frame";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Signup IS organization creation: the account and its espace de travail
    are born together; teammates join later via lien d'invitation. */
export default function SignupPage() {
  const { user, organizations, loading, signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    organization_name: "",
    display_name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (!loading && user) {
    return <Navigate replace to={homeOf(organizations)} />;
  }

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const session = await signup(form);
      navigate(homeOf(session.organizations), { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthFrame
      title="Créer un espace"
      subtitle="Votre organisation et son espace de conformité sont créés ensemble."
      brand={{
        tagline: "Un espace de conformité, prêt en minutes.",
        text: "Importez vos preuves, lancez une évaluation, revoyez les constats.",
        note: "Hébergé en France · RGPD",
      }}
      footer={
        <>
          Déjà un compte ?{" "}
          <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
            Se connecter
          </Link>
        </>
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
          <Label htmlFor="display_name">Votre nom</Label>
          <Input
            id="display_name"
            autoComplete="name"
            required
            value={form.display_name}
            onChange={set("display_name")}
            placeholder="Prénom Nom"
            className="h-10"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Adresse e-mail</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={form.email}
            onChange={set("email")}
            placeholder="vous@entreprise.fr"
            className="h-10"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="password">Mot de passe</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              value={form.password}
              onChange={set("password")}
              className="h-10"
            />
            <p className="text-xs text-muted-foreground">10 caractères minimum.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="organization_name">Nom de l'organisation</Label>
            <Input
              id="organization_name"
              required
              value={form.organization_name}
              onChange={set("organization_name")}
              placeholder="Lumen AI"
              className="h-10"
            />
          </div>
        </div>
        <Button type="submit" className="h-10 w-full" disabled={pending}>
          {pending ? "Création…" : "Créer mon espace"}
        </Button>
      </form>
    </AuthFrame>
  );
}
