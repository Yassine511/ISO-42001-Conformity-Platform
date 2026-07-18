import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { CircleX } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { AuthFrame } from "@/components/auth-frame";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const { user, organizations, loading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // already signed in (e.g. back-button onto /login) — straight to the app
  if (!loading && user) {
    return <Navigate replace to={homeOf(organizations)} />;
  }

  const from = (location.state as { from?: string } | null)?.from;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const session = await login(email, password);
      navigate(from ?? homeOf(session.organizations), { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthFrame
      title="Se connecter"
      subtitle="Reprenez votre travail de conformité."
      brand={{
        tagline: "La conformité, sans acte de foi.",
        text: "Citations vérifiées au caractère près. Verdicts confirmés par un humain.",
        note: "ISO/IEC 42001",
      }}
      footer={
        <>
          Pas encore de compte ?{" "}
          <Link to="/signup" className="font-medium text-foreground underline underline-offset-4">
            Créer un espace
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
          <Label htmlFor="email">Adresse e-mail</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="vous@entreprise.fr"
            className="h-10"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Mot de passe</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-10"
          />
        </div>
        <Button type="submit" className="h-10 w-full" disabled={pending}>
          {pending ? "Connexion…" : "Se connecter"}
        </Button>
      </form>
    </AuthFrame>
  );
}
