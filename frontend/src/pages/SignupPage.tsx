import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { CircleX } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { AuthFrame, ACCENT_ON_INK } from "@/components/auth-frame";
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
      title="Créer un espace de conformité"
      subtitle="Un compte nominatif et l'organisation qu'il administre — invitez vos collègues ensuite, par lien à usage unique."
      brand={{
        eyebrow: "Nouvel espace de conformité",
        tagline: (
          <>
            Un espace, une organisation,
            <br />
            <em className="font-serif font-normal italic" style={ACCENT_ON_INK}>
              un registre qui fait foi.
            </em>
          </>
        ),
        text:
          "Votre compte et votre organisation sont créés d'un seul geste — vous en êtes le " +
          "premier membre, et chaque décision prise ensuite portera un nom et une date.",
        points: [
          ["Étape 1", "Créez l'espace — compte + organisation, atomiquement"],
          ["Étape 2", "Déposez vos politiques — les originaux restent immuables"],
          ["Étape 3", "Lancez la première évaluation, puis confirmez les constats"],
        ],
        note: "L'IA rédige · le code vérifie · l'humain confirme",
      }}
      footer={
        <>
          <span>Déjà un espace ?</span>
          <Link to="/login" className="font-medium text-primary hover:underline hover:underline-offset-4">
            Se connecter
          </Link>
        </>
      }
      caps="Création atomique : compte + organisation + adhésion — rien n'existe à moitié."
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
          <Label htmlFor="display_name">Votre nom</Label>
          <Input
            id="display_name"
            autoComplete="name"
            required
            value={form.display_name}
            onChange={set("display_name")}
            placeholder="Prénom Nom"
            className="h-11"
          />
          <p className="text-xs text-muted-foreground">
            Il apparaîtra sur chaque décision que vous confirmerez.
          </p>
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
            className="h-11"
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
            className="h-11"
          />
          <p className="text-xs text-muted-foreground">
            10 caractères minimum — conservé uniquement sous forme de hachage bcrypt.
          </p>
        </div>

        <p className="flex items-center gap-3 font-mono text-[10px] tracking-[0.14em] text-muted-foreground/70 uppercase before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
          L'organisation
        </p>
        <div className="space-y-2">
          <Label htmlFor="organization_name">Nom de l'organisation</Label>
          <Input
            id="organization_name"
            required
            value={form.organization_name}
            onChange={set("organization_name")}
            placeholder="Lumen AI"
            className="h-11"
          />
          <p className="text-xs text-muted-foreground">
            Le périmètre de vos preuves, évaluations et registres.
          </p>
        </div>

        <Button type="submit" className="h-11 w-full" disabled={pending}>
          {pending ? "Création…" : "Créer l'espace →"}
        </Button>
      </form>
    </AuthFrame>
  );
}
