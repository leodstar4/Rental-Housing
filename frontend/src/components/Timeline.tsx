import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet, type ResultKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate } from "@/lib/dates";
import { ResultBadge } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface TimelineEvent {
  date: string; team_rule_id: string; title: string; category: string;
  before: ResultKind; after: ResultKind; status_line?: string; date_origin?: string;
  conflict_flag?: boolean; conflict_note?: string | null; past?: boolean;
}
interface TimelineData {
  next_change: TimelineEvent | null;
  events: TimelineEvent[];
  pending: { team_rule_id: string; title: string; category: string; status_line?: string }[];
  disclaimer: string;
}

const L = {
  en: { heading: "What changes for you", next: "Next change", none: "No scheduled changes for this address.", past: "Past",
    derived: "date calculated from the law's formula", calendar: "date from state calendar rule", conflict: "Possible conflict",
    showAll: "Show full timeline", showLess: "Show fewer", pending: "Pending bills (not law)", error: "The timeline could not be loaded.", retry: "Try again" },
  es: { heading: "Qué cambia para usted", next: "Próximo cambio", none: "No hay cambios programados para esta dirección.", past: "Pasado",
    derived: "fecha calculada con la fórmula de la ley", calendar: "fecha según la regla del calendario estatal", conflict: "Posible conflicto",
    showAll: "Ver la línea de tiempo completa", showLess: "Ver menos", pending: "Proyectos de ley (no son ley)", error: "No se pudo cargar la línea de tiempo.", retry: "Reintentar" },
};

function Change({ e }: { e: TimelineEvent }) {
  return <span className="inline-flex flex-wrap items-center gap-1.5"><ResultBadge kind={e.before} /><span aria-hidden>→</span><ResultBadge kind={e.after} /></span>;
}

export function Timeline({ addressId }: { addressId: string }) {
  const { lang } = useI18n();
  const l = L[lang];
  const [all, setAll] = useState(false);
  const q = useQuery({
    queryKey: ["timeline", addressId, lang],
    queryFn: () => apiGet<TimelineData>(`/timeline/${addressId}?lang=${lang}`),
  });

  if (q.isPending) return <section aria-busy className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-32 w-full" /></section>;
  if (q.isError) return <p className="text-destructive">{l.error} <Button variant="link" onClick={() => q.refetch()}>{l.retry}</Button></p>;

  const d = q.data;
  const firstFuture = d.events.findIndex((e) => !e.past);
  const shown = all ? d.events : (firstFuture < 0 ? [] : d.events.slice(firstFuture, firstFuture + 3));
  const years = [...new Set(shown.map((e) => e.date.slice(0, 4)))];
  const nc = d.next_change;

  return (
    <section className="space-y-4" aria-labelledby="timeline-h">
      <h2 id="timeline-h" className="text-xl font-bold text-primary">{l.heading}</h2>
      <div className="rounded-lg border-2 border-primary bg-highlight p-4">
        {nc ? (
          <p className="flex flex-wrap items-center gap-2">
            <strong>{l.next}: {formatDate(nc.date, lang)}</strong> — <span className="font-semibold">{nc.title}</span>: <Change e={nc} />
            {nc.conflict_flag && <ConflictTag note={nc.conflict_note} label={l.conflict} />}
          </p>
        ) : <p className="font-semibold">{l.none}</p>}
      </div>

      {years.map((y) => (
        <div key={y}>
          <h3 className="font-bold text-lg mb-2">{y}</h3>
          <ol className="border-l-2 border-input ml-2 space-y-4">
            {shown.filter((e) => e.date.startsWith(y)).map((e) => (
              <li key={e.team_rule_id + e.date} className={`relative pl-5 ${e.past ? "text-muted-foreground opacity-70" : ""}`}>
                <span className={`absolute -left-[7px] top-1.5 h-3 w-3 rounded-full ${e.past ? "bg-muted-foreground" : "bg-primary"}`} aria-hidden />
                <div className="flex flex-wrap items-center gap-2">
                  <strong>{formatDate(e.date, lang)}</strong>
                  {e.past && <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-semibold">{l.past}</span>}
                  {e.conflict_flag && <ConflictTag note={e.conflict_note} label={l.conflict} />}
                </div>
                <p className="font-semibold">{e.title}</p>
                <Change e={e} />
                {e.date_origin === "derived" && <p className="text-xs mt-1">{l.derived}</p>}
                {e.date_origin === "calendar_default" && <p className="text-xs mt-1">{l.calendar}</p>}
              </li>
            ))}
          </ol>
        </div>
      ))}
      {d.events.length > shown.length || all ? (
        d.events.length > 0 && <Button variant="outline" onClick={() => setAll(!all)} aria-expanded={all}>{all ? l.showLess : l.showAll}</Button>
      ) : null}

      {d.pending.length > 0 && (
        <div className="rounded-lg border border-pending/40 bg-pending-soft p-4">
          <h3 className="font-bold text-pending mb-2">{l.pending}</h3>
          <ul className="space-y-2">
            {d.pending.map((p) => (
              <li key={p.team_rule_id} className="text-pending"><span className="font-semibold">{p.title}</span>{p.status_line && <span className="block text-sm">{p.status_line}</span>}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ConflictTag({ note, label }: { note?: string | null | undefined; label: string }) {
  return <span title={note ?? undefined} tabIndex={0} className="rounded border border-destructive/40 bg-destructive/5 px-2 py-0.5 text-xs font-semibold text-destructive cursor-help">{label}</span>;
}
