// The append-only case event stream.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { eventTypeLabel } from "@/lib/labels";
import { SectionHeading } from "@/components/section-heading";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import {
  type RemediationCaseDetail,
} from "../../api";

// ----------------------------------------------------------------- events

export function EventsTimeline({ c }: { c: RemediationCaseDetail }) {
  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Journal d'audit"
        description="Chaque étape du cas, dans l'ordre — rien ne s'efface."
      />
      <ol className="relative space-y-4 border-l border-border pl-5">
        {[...c.events].reverse().map((e) => (
          <li key={e.sequence} className="relative text-xs text-muted-foreground">
            <span
              aria-hidden
              className="absolute top-1 -left-[calc(1.25rem+3.5px)] size-2 rounded-full border border-background bg-primary/70"
            />
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="font-medium text-foreground">{eventTypeLabel(e.event_type)}</span>
              <span>{new Date(e.created_at).toLocaleString("fr-FR")}</span>
              {e.actor_label && (
                <span className="text-muted-foreground/80">par {e.actor_label} (non vérifié)</span>
              )}
            </div>
          </li>
        ))}
      </ol>
      <TechnicalDisclosure summary="Détails techniques du journal">
        <ul className="space-y-1">
          {[...c.events].reverse().map((e) => (
            <li key={e.sequence} className="font-mono text-xs">
              #{e.sequence} {e.event_type} (v{e.payload_version})
            </li>
          ))}
        </ul>
      </TechnicalDisclosure>
    </section>
  );
}
