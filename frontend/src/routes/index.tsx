import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useState } from "react";
import { Check, Database, FileText, Search } from "lucide-react";

import { apiGet, type MxStates, type MxZones, type MxZoneSearchItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { setDisclaimer } from "@/components/Shell";
import { CoverageBadge, MxError, useMx } from "@/components/mx/MxShared";
import { ZoneMapExplorer } from "@/routes/mapa";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Renta MX — Rentar y vivir en México" },
      { name: "description", content: "Busque por zona, vea las viviendas publicadas y los requisitos legales con su cita literal, y firme su contrato en línea." },
    ],
  }),
  component: LandingPage,
});

function LandingPage() {
  const { mx, lang } = useMx();
  const states = useQuery({ queryKey: ["mx-states", lang], queryFn: () => apiGet<MxStates>(`/mx/states?lang=${lang}`), staleTime: 5 * 60_000 });
  useEffect(() => setDisclaimer(states.data?.disclaimer, lang), [states.data, lang]);
  const [onlyVerified, setOnlyVerified] = useState(false);

  const list = states.data?.states ?? [];
  const shown = onlyVerified ? list.filter((s) => s.legal_coverage === "estatal_verificada") : list;

  return (
    <div className="space-y-12">
      <section className="space-y-6">
        <div className="max-w-3xl space-y-3">
          <h1 className="font-serif text-3xl font-bold leading-tight text-primary md:text-4xl">{mx.landing.title}</h1>
          <p className="text-lg text-muted-foreground">{mx.landing.subtitle}</p>
        </div>
        <ZoneSearch states={states.data?.states ?? []} />
        <ul className="grid gap-3 sm:grid-cols-3">
          {[
            { icon: <Check className="h-4 w-4" />, text: mx.landing.trustNoFake },
            { icon: <FileText className="h-4 w-4" />, text: mx.landing.trustQuotes },
            { icon: <Database className="h-4 w-4" />, text: mx.landing.trustStats },
          ].map((p, i) => (
            <li key={i} className="flex items-start gap-2 rounded-lg border border-border bg-card p-3 text-sm">
              <span className="mt-0.5 text-primary" aria-hidden>{p.icon}</span>
              <span>{p.text}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="map-title" className="space-y-4">
        <div className="max-w-3xl space-y-1">
          <h2 id="map-title" className="text-xl font-bold text-primary">{mx.map.sectionTitle}</h2>
          <p className="text-muted-foreground">{mx.map.sectionIntro}</p>
        </div>
        <ZoneMapExplorer cveEnt="09" stateName="Ciudad de México" />
      </section>

      <section aria-labelledby="states-title" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="states-title" className="text-xl font-bold text-primary">{mx.landing.statesTitle}</h2>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={onlyVerified} onChange={(e) => setOnlyVerified(e.target.checked)} className="h-4 w-4" />
            {mx.coverage.stateVerified}
          </label>
        </div>
        {states.isError ? (
          <MxError message={mx.landing.statesError} onRetry={() => states.refetch()} />
        ) : states.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-muted/40" />)}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {shown.map((s) => (
              <Link key={s.cve_ent} to="/requisitos/$cveEnt" params={{ cveEnt: s.cve_ent }}
                className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-accent/40">
                <span className="font-semibold text-foreground">{s.name}</span>
                <CoverageBadge coverage={s.legal_coverage} />
                <span className="text-xs text-muted-foreground">{mx.listingsCount(s.listings_count)}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="how-title" className="space-y-4">
        <h2 id="how-title" className="text-xl font-bold text-primary">{mx.landing.howTitle}</h2>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {mx.landing.howSteps.map((step, i) => (
            <li key={i} className="rounded-xl border border-border bg-card p-4">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">{i + 1}</span>
              <p className="mt-2 text-sm">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-primary/20 bg-primary/5 p-6">
        <p className="text-lg font-semibold text-foreground">{mx.landing.publishPrompt}</p>
        <Button asChild><Link to="/publicar">{mx.landing.publishCta}</Link></Button>
      </section>
    </div>
  );
}

function ZoneSearch({ states }: { states: MxStates["states"] }) {
  const { mx, lang } = useMx();
  const navigate = useNavigate();
  const stateId = useId();
  const munId = useId();
  const [cveEnt, setCveEnt] = useState("");
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  useEffect(() => { const h = setTimeout(() => setDeb(q.trim()), 300); return () => clearTimeout(h); }, [q]);

  const zones = useQuery({
    queryKey: ["mx-zone-search", cveEnt, deb, lang],
    queryFn: () => apiGet<MxZones>(`/mx/zones?cve_ent=${cveEnt}&q=${encodeURIComponent(deb)}&limit=20&lang=${lang}`),
    enabled: !!cveEnt && deb.length >= 2,
    placeholderData: keepPreviousData,
  });
  const list: MxZoneSearchItem[] = zones.data?.zones ?? [];
  const stateName = useMemo(() => states.find((s) => s.cve_ent === cveEnt)?.name ?? "", [states, cveEnt]);
  const pick = (m: MxZoneSearchItem) => navigate({ to: "/zona/$cveEnt/$cveMun", params: { cveEnt, cveMun: m.cve_mun } });

  return (
    <fieldset className="grid max-w-3xl gap-3 rounded-xl border border-border bg-card p-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] sm:items-end">
      <legend className="mb-1 flex items-center gap-2 px-1 font-semibold text-foreground"><Search className="h-4 w-4" aria-hidden /> {mx.landing.searchLegend}</legend>
      <div className="flex flex-col gap-1">
        <label htmlFor={stateId} className="text-sm font-medium">{mx.landing.stateLabel}</label>
        <select id={stateId} value={cveEnt} onChange={(e) => { setCveEnt(e.target.value); setQ(""); setOpen(false); }}
          className="rounded-md border-2 border-input bg-background px-3 py-2.5 focus:border-primary">
          <option value="">{mx.landing.statePlaceholder}</option>
          {states.map((s) => <option key={s.cve_ent} value={s.cve_ent}>{s.name}</option>)}
        </select>
      </div>
      <div className="relative flex flex-col gap-1">
        <label htmlFor={munId} className="text-sm font-medium">{mx.landing.municipioLabel}</label>
        <input id={munId} role="combobox" aria-expanded={open} aria-controls={munId + "-list"} aria-autocomplete="list"
          disabled={!cveEnt} value={q} placeholder={cveEnt ? mx.landing.municipioPlaceholder : mx.landing.municipioDisabled}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, list.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === "Enter" && list[active]) { e.preventDefault(); pick(list[active]); }
            if (e.key === "Escape") setOpen(false);
          }}
          className="rounded-md border-2 border-input bg-background px-3 py-2.5 focus:border-primary disabled:opacity-50" />
        <span className="sr-only" role="status" aria-live="polite">{deb.length >= 2 ? mx.landing.municipioResults(list.length) : ""}</span>
        {open && cveEnt && deb.length >= 2 && (
          <ul id={munId + "-list"} role="listbox" className="absolute top-full z-10 mt-1 max-h-72 w-full overflow-auto rounded-md border bg-popover shadow-lg">
            {zones.isFetching && !list.length && <li className="px-4 py-3 text-muted-foreground">{mx.common.loading}</li>}
            {!zones.isFetching && !list.length && <li className="px-4 py-3 text-muted-foreground">{mx.landing.municipioNoMatches(deb, stateName)}</li>}
            {list.map((m, i) => (
              <li key={m.cve_mun} role="option" aria-selected={i === active} onMouseDown={() => pick(m)}
                className={`flex cursor-pointer items-center justify-between px-4 py-2.5 ${i === active ? "bg-accent" : ""}`}>
                <span className="font-medium">{m.name}</span>
                <span className="text-xs text-muted-foreground">{mx.listingsCount(m.listings_count)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Link to="/requisitos/$cveEnt" params={{ cveEnt: cveEnt || "09" }} disabled={!cveEnt}
        className={`text-sm underline underline-offset-2 ${cveEnt ? "text-primary" : "pointer-events-none opacity-40"}`}>
        {mx.landing.seeStateRequirements}
      </Link>
    </fieldset>
  );
}
