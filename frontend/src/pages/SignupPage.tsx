import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
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
      title="Créer un compte"
      subtitle="Votre organisation et son espace de conformité sont créés ensemble."
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
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="h-10 w-full" disabled={pending}>
          {pending ? "Création…" : "Créer mon espace"}
        </Button>
      </form>
    </AuthFrame>
  );
}
