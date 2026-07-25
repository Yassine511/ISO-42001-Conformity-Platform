import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { CircleX } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { AuthFrame, ACCENT_ON_INK } from "@/components/auth-frame";
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
      subtitle="Retrouvez vos espaces d'organisation et reprenez la revue là où vous l'avez laissée."
      stamp="✓ Accès nominatif · journalisé"
      brand={{
        eyebrow: "Espace de conformité",
        tagline: (
          <>
            Le registre où chaque
            <br />
            verdict porte{" "}
            <em className="font-serif font-normal italic" style={ACCENT_ON_INK}>
              une signature.
            </em>
          </>
        ),
        text:
          "Vos documents, vos évaluations, vos décisions — et la preuve que chacune d'elles " +
          "repose sur une citation localisée, pas sur l'assurance d'un modèle.",
        points: [
          ["§1", "Session par cookie httpOnly — aucun jeton exposé au script"],
          ["§2", "Isolation stricte par organisation — l'existence d'autrui ne fuit pas"],
          ["§3", "Invitations à usage unique, expirées sous 7 jours"],
        ],
        note: "L'IA rédige · le code vérifie · l'humain confirme",
      }}
      footer={
        <>
          <span>Pas encore d'espace ?</span>
          <Link to="/signup" className="font-medium text-primary hover:underline hover:underline-offset-4">
            Créer un espace de conformité
          </Link>
        </>
      }
      caps="Session par cookie httpOnly · chaque connexion est journalisée."
    >
      <form className="space-y-5" onSubmit={submit}>
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
            placeholder="solene.vasseur@lumen-ai.fr"
            className="h-11"
          />
          <p className="text-xs text-muted-foreground">
            Celle avec laquelle votre espace a été créé ou votre invitation émise.
          </p>
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
            className="h-11"
          />
        </div>
        <Button type="submit" className="h-11 w-full" disabled={pending}>
          {pending ? "Connexion…" : "Ouvrir mon espace →"}
        </Button>
      </form>
    </AuthFrame>
  );
}
