// The confirmed gap findings a case covers, and linking more.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useMutation, useQuery } from "@tanstack/react-query";
import { verdictDisplay } from "@/lib/labels";
import { SectionHeading } from "@/components/section-heading";
import { StatusLabel } from "@/components/status-label";
import {
  api,
  type RemediationCaseDetail,
} from "../../api";
import { ErrorText } from "./shared";

// -------------------------------------------------------- linked findings

export function LinkedFindings({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const suggestions = useQuery({
    queryKey: ["link-suggestions", orgId, c.id],
    queryFn: () => api.linkSuggestions(orgId, c.id),
    enabled: c.status === "TRIAGE",
  });
  const link = useMutation({
    mutationFn: (body: { finding_id: string; decision: "link" | "reject" }) =>
      api.linkFinding(orgId, c.id, { ...body, link_source: "search_suggested" }),
    onSuccess: () => {
      onChanged();
      suggestions.refetch();
    },
  });
  const unlink = useMutation({
    mutationFn: (findingId: string) => api.unlinkFinding(orgId, c.id, findingId),
    onSuccess: onChanged,
  });

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Écart confirmé"
        description="Les constats humains qui fondent ce cas."
      />
      <ul className="space-y-2">
        {c.finding_links.map((l) => (
          <li
            key={l.finding_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3 text-sm"
          >
            <span className="font-mono text-xs font-semibold text-primary">
              {l.finding_requirement_id}
            </span>
            {l.is_primary && (
              <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-primary">
                principal
              </span>
            )}
            <span className="text-muted-foreground">{l.finding_requirement_fr}</span>
            <StatusLabel display={verdictDisplay(l.finding_human_verdict)} />
            {!l.is_primary && c.status === "TRIAGE" && (
              <button
                onClick={() => unlink.mutate(l.finding_id)}
                className="ml-auto min-h-9 text-xs text-destructive hover:underline"
              >
                Délier
              </button>
            )}
          </li>
        ))}
      </ul>
      {c.status === "TRIAGE" && (suggestions.data?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-muted-foreground">
            Lacunes similaires suggérées (décision humaine : lier ou écarter)
          </h3>
          <ul className="space-y-1">
            {suggestions.data!.map((s) => (
              <li
                key={s.finding_id}
                className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-2 text-sm"
              >
                <span className="font-mono text-xs">{s.requirement_id}</span>
                <span className="text-muted-foreground">{s.requirement_fr}</span>
                {s.same_domain && (
                  <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-xs text-primary">
                    même domaine
                  </span>
                )}
                <span className="ml-auto flex gap-2">
                  <button
                    onClick={() => link.mutate({ finding_id: s.finding_id, decision: "link" })}
                    className="min-h-9 text-xs font-medium text-primary hover:underline"
                  >
                    Lier
                  </button>
                  <button
                    onClick={() => link.mutate({ finding_id: s.finding_id, decision: "reject" })}
                    className="min-h-9 text-xs text-muted-foreground hover:underline"
                  >
                    Écarter
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ErrorText error={link.error || unlink.error} />
    </section>
  );
}
