import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiGet, type MxStates, type MxZones } from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import { Disclaimer, MxError, MxLoading, useMx } from "@/components/mx/MxShared";
import { MxMap, zoneKey, type MxMapZone } from "@/components/mx/MxMap";
import { formatMXN } from "@/lib/mx-i18n";

export const Route = createFileRoute("/mapa")({
  head: () => ({ meta: [{ title: "Mapa de zonas — Renta MX" }] }),
  component: MapPage,
});

/** Accent/case-insensitive fold so "cuauhtemoc" matches "Cuauhtémoc". */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function MapPage() {
  const { mx, lang } = useMx();
  const [cveEnt, setCveEnt] = useState("09");

  const states = useQuery({ queryKey: ["mx-states", lang], queryFn: () => apiGet<MxStates>(`/mx/states?lang=${lang}`), staleTime: 5 * 60_000 });
  useEffect(() => setDisclaimer(states.data?.disclaimer, lang), [states.data, lang]);
  const stateName = useMemo(() => states.data?.states.find((s) => s.cve_ent === cveEnt)?.name ?? "", [states.data, cveEnt]);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="font-serif text-3xl font-bold text-primary">{mx.map.pageTitle}</h1>
        <p className="max-w-prose text-muted-foreground">{mx.map.pageIntro}</p>
        <Disclaimer />
      </header>

      <label className="flex max-w-xs flex-col gap-1">
        <span className="text-sm font-medium">{mx.map.stateLabel}</span>
        <select
          value={cveEnt}
          onChange={(e) => setCveEnt(e.target.value)}
          className="rounded-md border-2 border-input bg-background px-3 py-2.5 focus:border-primary"
        >
          {(states.data?.states ?? []).map((s) => (
            <option key={s.cve_ent} value={s.cve_ent}>{s.name}</option>
          ))}
        </select>
      </label>

      <ZoneMapExplorer cveEnt={cveEnt} stateName={stateName} />
    </div>
  );
}

/** Shared map + synchronized search; reused by the landing section (CDMX) and /mapa. */
export function ZoneMapExplorer({ cveEnt, stateName }: { cveEnt: string; stateName?: string }) {
  const { mx, lang } = useMx();
  const [q, setQ] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const zones = useQuery({
    queryKey: ["mx-zones-map", cveEnt, lang],
    queryFn: () => apiGet<MxZones>(`/mx/zones?cve_ent=${cveEnt}&limit=600&lang=${lang}`),
    enabled: !!cveEnt,
  });

  // Reset the selection when the state changes.
  useEffect(() => setSelectedKey(null), [cveEnt]);

  // The map only shows a price hint when a median exists (count >= min_count_for_stats); never a
  // placeholder. The median is the one figure honest enough to summarize a zone in a popup.
  const all: MxMapZone[] = (zones.data?.zones ?? []).map((z) => {
    const median = z.price_summary?.has_stats ? z.price_summary.median : undefined;
    return { ...z, price_hint: median != null ? mx.map.medianHint(formatMXN(median, lang)) : undefined } as MxMapZone;
  });
  const folded = fold(q.trim());
  const filtered = folded ? all.filter((z) => fold(z.name).includes(folded)) : all;

  if (zones.isLoading) return <MxLoading />;
  if (zones.isError) return <MxError onRetry={() => zones.refetch()} message={mx.map.loadError} />;

  return (
    <div className="space-y-4">
      <label className="flex max-w-md flex-col gap-1">
        <span className="text-sm font-medium">{mx.map.searchLabel}</span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={mx.map.searchPlaceholder}
          className="rounded-md border-2 border-input bg-background px-3 py-2.5 focus:border-primary"
        />
        <span className="sr-only" role="status" aria-live="polite">
          {q.trim() ? mx.map.resultsCount(filtered.length) : ""}
        </span>
      </label>

      {all.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center text-muted-foreground">{mx.map.empty}</p>
      ) : filtered.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center text-muted-foreground">{mx.map.noResults(q.trim())}</p>
      ) : (
        <MxMap
          zones={filtered}
          selectedKey={selectedKey}
          onSelect={(z) => setSelectedKey(zoneKey(z))}
          stateName={stateName}
        />
      )}
    </div>
  );
}
