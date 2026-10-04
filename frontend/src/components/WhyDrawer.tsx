import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, X, HelpCircle } from "lucide-react";
import { apiGet, type Lang } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate } from "@/lib/dates";
import { useIsMobile } from "@/hooks/use-mobile";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";

type Dict = Record<string, unknown>;
interface Step { condition?: string; value?: Dict; fact_source?: Dict; certainty?: Dict; outcome?: string; note?: string; source_text?: string }
interface Explain {
  title: string; summary?: string; status_line?: string;
  jurisdiction?: { note?: string; matched_address?: string; rule_jurisdiction?: string; address_city?: string };
  coverage_steps?: Step[]; exemption_steps?: Step[];
  precedence?: { governed_by?: string; governing_title?: string; note?: string; interaction?: string; conflict_note?: string | null } | null;
  status_steps?: { step: string; value?: string; date?: string; origin?: string; quote?: string; note?: string }[];
  confidence_breakdown?: { rule?: { value: number; reason?: string }; coverage?: { value: number; reason?: string; factors?: { factor: number; reason: string }[] }; geocoding?: { value: number; reason?: string }; combined?: number };
  provenance?: { citation?: string; quoted_span?: string; source_url?: string; retrieved_at?: string; model?: string; snapshot?: string };
  human_review?: Dict[] | null; reviews?: Dict[] | null;
}

const L = {
  en: { why: "Why this answer?", where: "Where", coverage: "Coverage checks", exemptions: "Exemptions checked", governs: "Which rule governs",
    when: "When it applies", confident: "How confident", source: "Source", rule: "Rule", cov: "Coverage", loc: "Location", total: "Total",
    value: "Value used", from: "Source", certainty: "Certainty", yes: "Yes", no: "No", unknown: "Unknown", open: "Open source",
    retrieved: "Retrieved", model: "Model", snapshot: "Snapshot version", review: "Human review", error: "The explanation could not be loaded.", retry: "Try again" },
  es: { why: "¿Por qué esta respuesta?", where: "Dónde", coverage: "Verificación de cobertura", exemptions: "Exenciones revisadas", governs: "Qué regla prevalece",
    when: "Cuándo aplica", confident: "Nivel de confianza", source: "Fuente", rule: "Regla", cov: "Cobertura", loc: "Ubicación", total: "Total",
    value: "Valor utilizado", from: "Fuente", certainty: "Certeza", yes: "Sí", no: "No", unknown: "Desconocido", open: "Abrir la fuente",
    retrieved: "Consultado", model: "Modelo", snapshot: "Versión de la instantánea", review: "Revisión humana", error: "No se pudo cargar la explicación.", retry: "Reintentar" },
};

const str = (v: unknown) => (v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const pairs = (d?: Dict) => Object.entries(d ?? {}).map(([k, v]) => `${k}: ${str(v)}`).join("; ");

function Outcome({ o, l }: { o?: string | undefined; l: (typeof L)[Lang] }) {
  if (o === "yes") return <Check className="h-5 w-5 shrink-0 text-applies" aria-label={l.yes} />;
  if (o === "no") return <X className="h-5 w-5 shrink-0 text-muted-foreground" aria-label={l.no} />;
  return <HelpCircle className="h-5 w-5 shrink-0 text-unknown" aria-label={l.unknown} />;
}

function Steps({ steps, l }: { steps: Step[]; l: (typeof L)[Lang] }) {
  return (
    <ul className="space-y-3">
      {steps.map((s, i) => (
        <li key={i} className="flex gap-2">
          <Outcome o={s.outcome} l={l} />
          <div className="text-sm space-y-0.5 min-w-0 break-words">
            <p className="font-semibold">{s.condition}</p>
            {!!Object.keys(s.value ?? {}).length && <p><span className="text-muted-foreground">{l.value}: </span>{pairs(s.value)}</p>}
            {!!Object.keys(s.fact_source ?? {}).length && <p><span className="text-muted-foreground">{l.from}: </span>{pairs(s.fact_source)}</p>}
            {!!Object.keys(s.certainty ?? {}).length && <p><span className="text-muted-foreground">{l.certainty}: </span>{pairs(s.certainty)}</p>}
            {s.note && <p className="text-xs text-muted-foreground">{s.note}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="font-bold text-primary border-b pb-1 mb-2">{children}</h3>;
}

export function WhyButton({ addressId, ruleId, asOf }: { addressId: string; ruleId: string; asOf: string }) {
  const { lang } = useI18n();
  const l = L[lang];
  const [open, setOpen] = useState(false);
  const mobile = useIsMobile();
  const q = useQuery({
    queryKey: ["explain", addressId, ruleId, asOf, lang],
    queryFn: () => apiGet<Explain>(`/explain/${addressId}/${ruleId}?as_of=${asOf}&lang=${lang}`),
    enabled: open,
    staleTime: Infinity,
  });
  const d = q.data;
  const cb = d?.confidence_breakdown;
  const reviews = d?.human_review ?? d?.reviews ?? [];
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>{l.why}</Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={mobile ? "bottom" : "right"} className={`overflow-y-auto overflow-x-hidden break-words ${mobile ? "max-h-[85vh]" : "w-full sm:max-w-lg"}`}>
          <SheetHeader>
            <SheetTitle>{l.why}</SheetTitle>
            <SheetDescription>{d?.title ?? ruleId}</SheetDescription>
          </SheetHeader>
          {q.isPending && <div className="space-y-3 p-4" aria-busy>{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>}
          {q.isError && <p className="p-4 text-destructive">{l.error} <Button variant="link" onClick={() => q.refetch()}>{l.retry}</Button></p>}
          {d && (
            <div className="space-y-6 p-4 min-w-0">
              {d.summary && <p className="rounded-md bg-highlight p-3 font-medium">{d.summary}</p>}
              {d.jurisdiction && <section><H>{l.where}</H><p className="text-sm">{d.jurisdiction.note}</p>{d.jurisdiction.matched_address && <p className="text-xs text-muted-foreground">{d.jurisdiction.matched_address}</p>}</section>}
              {!!d.coverage_steps?.length && <section><H>{l.coverage}</H><Steps steps={d.coverage_steps} l={l} /></section>}
              {!!d.exemption_steps?.length && <section><H>{l.exemptions}</H><Steps steps={d.exemption_steps} l={l} /></section>}
              {d.precedence && (
                <section className="text-sm space-y-1"><H>{l.governs}</H>
                  {d.precedence.governed_by && <p className="font-semibold">{d.precedence.governed_by}{d.precedence.governing_title ? ` — ${d.precedence.governing_title}` : ""}</p>}
                  {d.precedence.note && <p>{d.precedence.note}</p>}
                  {d.precedence.conflict_note && <p className="text-destructive">{d.precedence.conflict_note}</p>}
                </section>
              )}
              {!!d.status_steps?.length && (
                <section className="text-sm"><H>{l.when}</H><ul className="space-y-2">
                  {d.status_steps.map((s, i) => (
                    <li key={i}>{s.date && <strong>{formatDate(s.date, lang)} </strong>}{s.note}
                      {s.quote && <blockquote className="mt-1 border-l-4 border-input pl-3 italic">“{s.quote}”</blockquote>}</li>
                  ))}
                </ul></section>
              )}
              {cb && (
                <section className="text-sm space-y-2"><H>{l.confident}</H>
                  <p className="font-mono text-base">
                    {cb.rule?.value ?? "—"} × {cb.coverage?.value ?? "—"} × {cb.geocoding?.value ?? "—"} = <strong>{cb.combined ?? "—"}</strong>
                  </p>
                  <ul className="space-y-1">
                    {cb.rule && <li><strong>{l.rule} ({cb.rule.value}):</strong> {cb.rule.reason}</li>}
                    {cb.coverage && <li><strong>{l.cov} ({cb.coverage.value}):</strong> {cb.coverage.reason}
                      {!!cb.coverage.factors?.length && <ul className="list-disc pl-5">{cb.coverage.factors.map((f, i) => <li key={i}>{f.factor} — {f.reason}</li>)}</ul>}</li>}
                    {cb.geocoding && <li><strong>{l.loc} ({cb.geocoding.value}):</strong> {cb.geocoding.reason}</li>}
                  </ul>
                </section>
              )}
              {d.provenance && (
                <section className="text-sm space-y-2"><H>{l.source}</H>
                  {d.provenance.citation && <p className="font-semibold">{d.provenance.citation}</p>}
                  {d.provenance.quoted_span && <blockquote className="border-l-4 border-input pl-3 italic">“{d.provenance.quoted_span}”</blockquote>}
                  {d.provenance.source_url && <a href={d.provenance.source_url} target="_blank" rel="noopener noreferrer" className="text-primary underline">{l.open} ↗</a>}
                  {d.provenance.retrieved_at && <p className="text-muted-foreground">{l.retrieved}: {formatDate(d.provenance.retrieved_at, lang)}</p>}
                  {d.provenance.model && <p className="text-muted-foreground">{l.model}: {d.provenance.model}</p>}
                  {d.provenance.snapshot && <p className="text-muted-foreground">{l.snapshot}: {d.provenance.snapshot}</p>}
                </section>
              )}
              {!!reviews?.length && (
                <section className="text-sm"><H>{l.review}</H><ul className="space-y-2">
                  {reviews.map((r, i) => <li key={i} className="rounded border p-2">{Object.entries(r).map(([k, v]) => <p key={k}><span className="text-muted-foreground">{k}: </span>{str(v)}</p>)}</li>)}
                </ul></section>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
