import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiGet, type Address, type ResultKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ResultBadge, StateMsg, setDisclaimer } from "@/components/Shell";

export const Route = createFileRoute("/changes")({
  head: () => ({
    meta: [
      { title: "What's Changing — Rental Housing Law Navigator" },
      { name: "description", content: "Upcoming housing law changes and the addresses they affect, before and after." },
      { property: "og:title", content: "What's Changing — Rental Housing Law Navigator" },
      { property: "og:description", content: "See upcoming rental housing law changes and how many addresses each affects." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: ChangesPage,
});

interface Summary { affected: number; conflict_flagged: number; notes: string; type: string; type_label?: string; title: string }
interface Detail { test_id: string; title?: string; notes?: string; type_label?: string; disclaimer?: string; addresses: Record<string, Record<string, { before: ResultKind; after: ResultKind }>>; conflict_flag_address_ids: string[] }

function ChangesPage() {
  const { t, lang } = useI18n();
  const [sel, setSel] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["changes", lang], queryFn: () => apiGet<{ summary: Record<string, Summary>; disclaimer: string }>(`/changes?lang=${lang}`) });
  useEffect(() => setDisclaimer(q.data?.disclaimer, lang), [q.data, lang]);
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold text-primary">{t.changesTitle}</h1>
      <p className="max-w-3xl text-muted-foreground">{t.changesIntro}</p>
      {!q.data ? <StateMsg error={q.isError} onRetry={() => q.refetch()} /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(q.data.summary).map(([id, s]) => (
            <button key={id} onClick={() => setSel(id)} aria-pressed={sel === id}
              className={`text-left rounded-lg border-2 bg-card p-5 space-y-2 hover:border-primary ${sel === id ? "border-primary" : "border-border"}`}>
              <div className="flex justify-between text-xs uppercase tracking-wide text-muted-foreground"><span>{id}</span><span>{t.type}: {s.type_label ?? s.type}</span></div>
              <h2 className="text-lg font-bold">{s.title}</h2>
              <p className="flex gap-4"><span><strong className="text-xl">{s.affected}</strong> {t.affected}</span>
                {s.conflict_flagged > 0 && <span className="text-destructive"><strong className="text-xl">{s.conflict_flagged}</strong> {t.conflicts}</span>}</p>
              <p className="text-sm text-muted-foreground">{s.notes}</p>
            </button>
          ))}
        </div>
      )}
      {sel && <DetailTable id={sel} />}
    </div>
  );
}

function DetailTable({ id }: { id: string }) {
  const { t, lang } = useI18n();
  const [limit, setLimit] = useState(50);
  const d = useQuery({ queryKey: ["change", id, lang], queryFn: () => apiGet<Detail>(`/changes/${id}?lang=${lang}`) });
  const addrs = useQuery({ queryKey: ["addresses", "all"], queryFn: () => apiGet<{ addresses: Address[] }>("/addresses?q=&limit=1000"), staleTime: Infinity });
  const map = useMemo(() => Object.fromEntries((addrs.data?.addresses ?? []).map((a) => [a.address_id, a])), [addrs.data]);
  useEffect(() => setLimit(50), [id]);
  if (!d.data) return <StateMsg error={d.isError} onRetry={() => d.refetch()} />;
  const rows = Object.entries(d.data.addresses).flatMap(([aid, rules]) => Object.entries(rules).map(([rid, v]) => ({ aid, rid, ...v })));
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">{d.data.title ?? id}</h2>
      {d.data.type_label && <p className="text-sm text-muted-foreground">{t.type}: {d.data.type_label}</p>}
      {d.data.notes && <p className="max-w-3xl">{d.data.notes}</p>}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left"><tr>
            <th className="p-3">{t.address}</th><th className="p-3">{t.city}</th><th className="p-3">{t.rule}</th><th className="p-3">{t.beforeAfter}</th>
          </tr></thead>
          <tbody>
            {rows.slice(0, limit).map((r) => (
              <tr key={r.aid + r.rid} className="border-t">
                <td className="p-3">{map[r.aid]?.street ?? r.aid}{d.data?.conflict_flag_address_ids?.includes(r.aid) && <span className="ml-1 text-destructive" aria-label={t.conflict} title={t.conflict}>⚠</span>}</td>
                <td className="p-3">{map[r.aid]?.city ?? ""}</td>
                <td className="p-3 font-mono text-xs">{r.rid}</td>
                <td className="p-3"><span className="inline-flex flex-wrap items-center gap-1.5"><ResultBadge kind={r.before} /> <span aria-hidden>→</span> <ResultBadge kind={r.after} /></span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        {t.showing(Math.min(limit, rows.length), rows.length)}
        {limit < rows.length && <button onClick={() => setLimit((l) => l + 100)} className="rounded-md border px-3 py-1.5 text-foreground hover:bg-accent">{t.showMore}</button>}
      </div>
    </section>
  );
}
