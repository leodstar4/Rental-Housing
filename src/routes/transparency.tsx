import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { StateMsg, setDisclaimer } from "@/components/Shell";
import { formatDate } from "@/lib/dates";

export const Route = createFileRoute("/transparency")({
  head: () => ({
    meta: [
      { title: "Transparency — Rental Housing Law Navigator" },
      { name: "description", content: "How the navigator builds answers: model, sources, conflicts and the human-review register." },
      { property: "og:title", content: "Transparency — Rental Housing Law Navigator" },
      { property: "og:description", content: "Model, sources, open questions and conflicts flagged for human review." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: TransparencyPage,
});

/* eslint-disable @typescript-eslint/no-explicit-any */
function TransparencyPage() {
  const { t, lang } = useI18n();
  const audit = useQuery({ queryKey: ["audit", lang], queryFn: () => apiGet<any>(`/audit?lang=${lang}`) });
  const conf = useQuery({ queryKey: ["conflicts", lang], queryFn: () => apiGet<any>(`/conflicts?lang=${lang}`) });
  useEffect(() => setDisclaimer(audit.data?.disclaimer ?? conf.data?.disclaimer, lang), [audit.data, conf.data, lang]);
  const a = audit.data;
  const c = conf.data;
  const ex = a?.extraction ?? {};
  const statusEntries = Object.entries(a?.rules?.by_status ?? {}) as [string, number][];
  const items: { label: string; value: string; help: string; extra?: string }[] = a ? [
    { label: t.rules, value: String(a.rules?.exported ?? "—"), help: t.rulesHelp, extra: statusEntries.length ? `${t.byStatus}: ${statusEntries.map(([k, n]) => `${k} ${n}`).join(" · ")}` : undefined },
    { label: t.documents, value: String(ex.documents ?? "—"), help: t.docsHelp },
    { label: t.model, value: String(ex.model ?? "—"), help: t.modelHelp },
    { label: t.snapshot, value: String(ex.snapshot ?? "—"), help: t.snapshotHelp, extra: ex.created_at ? t.createdOn(formatDate(ex.created_at, lang)) : undefined },
    { label: t.cost, value: ex.cost_usd?.total != null ? `$${ex.cost_usd.total.toFixed(2)} USD` : "—", help: t.costHelp },
    { label: t.addresses, value: String(a.addresses ?? "—"), help: t.addressesHelp },
  ] : [];
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-3xl font-bold text-primary">{t.transTitle}</h1>
        <p className="mt-2 text-muted-foreground max-w-3xl">{t.transIntro}</p>
      </div>
      <section aria-labelledby="hiw">
        <h2 id="hiw" className="text-xl font-bold mb-4">{t.howItWorks}</h2>
        <ol className="flex flex-col md:flex-row md:items-stretch gap-2">
          {t.steps.map((s, i) => (
            <li key={s} className="flex md:flex-col items-center gap-2 flex-1">
              <div className="flex-1 w-full rounded-md border-2 border-primary/30 bg-accent p-3 text-center text-sm font-semibold text-accent-foreground">
                <span className="block text-xs text-muted-foreground">{i + 1}</span>{s}
              </div>
              {i < t.steps.length - 1 && <span aria-hidden className="text-primary text-xl md:hidden">↓</span>}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="text-xl font-bold mb-4">{t.system}</h2>
        {!a ? <StateMsg error={audit.isError} onRetry={() => audit.refetch()} /> : (
          <ul className="divide-y rounded-md border">
            {items.map((it) => (
              <li key={it.label} className="p-4 md:grid md:grid-cols-[220px_1fr] md:gap-4">
                <p className="font-semibold">{it.label}</p>
                <div>
                  <p className="text-lg font-semibold break-words">{it.value}</p>
                  <p className="text-sm text-muted-foreground">{it.help}</p>
                  {it.extra && <p className="text-sm">{it.extra}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {!c ? <StateMsg error={conf.isError} onRetry={() => conf.refetch()} /> : (
        <>
          <section>
            <h2 className="text-xl font-bold">{t.openQuestions}</h2>
            <p className="text-sm text-muted-foreground mb-4">{t.oqHelp}</p>
            <ul className="space-y-3">
              {(c.open_questions ?? []).map((q: any) => (
                <li key={q.id} className="rounded-md border p-4 space-y-1">
                  <p className="text-xs text-muted-foreground">{q.id}{q.rule_ids?.length ? ` · ${q.rule_ids.join(", ")}` : ""}</p>
                  <h3 className="font-sans font-bold">{q.topic}</h3>
                  <p>{q.question}</p>
                  {q.corpus && <p className="text-sm"><span className="font-semibold">{t.corpus}: </span>{q.corpus}</p>}
                  {q.handling && <p className="text-sm"><span className="font-semibold">{t.handling}: </span>{q.handling}</p>}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="text-xl font-bold mb-4">{t.flagged}</h2>
            <ul className="divide-y rounded-md border">
              {(c.flagged_rules ?? []).map((f: any) => (
                <li key={f.team_rule_id} className="p-4">
                  <p><span className="font-mono text-sm font-semibold">{f.team_rule_id}</span> <span className="text-muted-foreground">· {f.jurisdiction}</span></p>
                  <p className="text-sm">{f.conflict_note}</p>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="text-xl font-bold">{t.reviewRegister}</h2>
            <p className="text-sm text-muted-foreground mb-4">{t.hrHelp}</p>
            <ul className="space-y-3">
              {(c.human_review ?? []).map((h: any) => (
                <li key={h.id} className="rounded-md border p-4 space-y-1">
                  <p className="text-sm"><span className="font-semibold">{h.id}</span> · <span className="font-mono">{h.rule_id}</span>{h.date && <> · {formatDate(h.date, lang)}</>}</p>
                  <p className="text-sm"><span className="font-semibold">{t.action}: </span>{[h.action, h.kind, h.scope].filter(Boolean).join(" · ")}</p>
                  {h.reason && <p className="text-sm"><span className="font-semibold">{t.reason}: </span>{h.reason}</p>}
                  {h.quoted_span && <blockquote className="border-l-4 border-input pl-3 italic text-sm text-muted-foreground">“{h.quoted_span}”</blockquote>}
                  {h.reviewer && <p className="text-xs text-muted-foreground">{t.reviewer}: {h.reviewer}</p>}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
