import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";

import { apiGet, type MxSources } from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import { Disclaimer, HashChip, MxError, MxLoading, useMx } from "@/components/mx/MxShared";
import { formatDate } from "@/lib/dates";

export const Route = createFileRoute("/fuentes")({
  head: () => ({ meta: [{ title: "Fuentes oficiales — Renta MX" }] }),
  component: SourcesPage,
});

function SourcesPage() {
  const { mx, lang } = useMx();
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["mx-sources", lang], queryFn: () => apiGet<MxSources>(`/mx/sources?lang=${lang}`), staleTime: Infinity });
  useEffect(() => setDisclaimer(q.data?.disclaimer, lang), [q.data, lang]);

  const jurisdictions = useMemo(() => {
    const set = new Set<string>();
    for (const d of q.data?.docs ?? []) if (d.jurisdiction) set.add(d.jurisdiction);
    return [...set].sort();
  }, [q.data]);

  if (q.isLoading) return <MxLoading />;
  if (q.isError) return <MxError onRetry={() => q.refetch()} />;
  const data = q.data!;
  const docs = data.docs.filter((d) => !filter || d.jurisdiction === filter);

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="font-serif text-3xl font-bold text-primary">{mx.sources.title}</h1>
        <p className="max-w-prose text-muted-foreground">{mx.sources.intro}</p>
        <Disclaimer />
      </header>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-lg font-bold">{mx.sources.howTitle}</h2>
        <ol className="mt-3 grid gap-2 sm:grid-cols-5">
          {mx.sources.howSteps.map((s, i) => (
            <li key={i} className="rounded-lg border border-border p-3 text-sm">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">{i + 1}</span>
              <p className="mt-2">{s}</p>
            </li>
          ))}
        </ol>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="jur" className="text-sm font-medium">{mx.sources.filterLabel}</label>
        <select id="jur" value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm">
          <option value="">{mx.sources.filterAll}</option>
          {jurisdictions.map((j) => <option key={j} value={j}>{j}</option>)}
        </select>
      </div>

      {docs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center text-muted-foreground">{mx.sources.empty}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-3 py-2 font-semibold">{mx.sources.colDocument}</th>
                <th className="px-3 py-2 font-semibold">{mx.sources.colPublisher}</th>
                <th className="px-3 py-2 font-semibold">{mx.sources.colJurisdiction}</th>
                <th className="px-3 py-2 font-semibold">{mx.sources.colRetrieved}</th>
                <th className="px-3 py-2 font-semibold">{mx.sources.colHash}</th>
                <th className="px-3 py-2 font-semibold">{mx.sources.colLink}</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.doc_id} id={d.doc_id} className="scroll-mt-24 border-t border-border align-top">
                  <td className="px-3 py-2">
                    <span className="font-medium">{d.title ?? d.doc_id}</span>
                    <span className="block font-mono text-xs text-muted-foreground">{d.doc_id}</span>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{d.publisher ?? "—"}</td>
                  <td className="px-3 py-2">{d.jurisdiction ?? "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{d.retrieved_at ? formatDate(d.retrieved_at, lang) : "—"}</td>
                  <td className="px-3 py-2">{d.sha256 ? <HashChip sha={d.sha256} /> : "—"}</td>
                  <td className="px-3 py-2">
                    {d.url ? (
                      <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">{mx.common.openInNewTab}</span>
                      </a>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.states_without_state_source.length > 0 && (
        <section className="rounded-xl border border-unknown/30 bg-unknown-soft/50 p-5">
          <h2 className="font-semibold text-foreground">{mx.sources.noStateSourcesTitle}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{mx.sources.noStateSourcesBody}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {data.states_without_state_source.map((s) => (
              <li key={s.cve_ent} className="rounded-md border border-border bg-card px-2 py-1 text-sm">{s.name}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
