import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Home } from "lucide-react";

import { apiGet, type MxZoneDetail, type MxListing, type MxSources, type MxStat, type MxPriceSummary } from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import {
  CoverageBadge,
  CoverageNotice,
  Disclaimer,
  EmptyState,
  MxError,
  MxLoading,
  StatCard,
  useMx,
} from "@/components/mx/MxShared";
import { formatInt, formatMXN, formatPct, type MxCopy } from "@/lib/mx-i18n";
import { formatDate } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import { MxMap, zoneKey, type MxMapZone } from "@/components/mx/MxMap";

export const Route = createFileRoute("/zona/$cveEnt/$cveMun")({
  component: ZonePage,
});

function ZonePage() {
  const { cveEnt, cveMun } = Route.useParams();
  const { mx, lang } = useMx();
  const q = useQuery({
    queryKey: ["mx-zone", cveEnt, cveMun, lang],
    queryFn: () => apiGet<MxZoneDetail>(`/mx/zones/${cveEnt}/${cveMun}?lang=${lang}`),
  });
  // Source docs let us turn a stat's doc_id into a title + retrieval date.
  const sources = useQuery({ queryKey: ["mx-sources", lang], queryFn: () => apiGet<MxSources>(`/mx/sources?lang=${lang}`), staleTime: Infinity });
  useEffect(() => setDisclaimer(q.data?.disclaimer, lang), [q.data, lang]);

  const docTitle = useMemo(() => {
    const m = new Map<string, { title: string; retrieved?: string }>();
    for (const d of sources.data?.docs ?? []) if (d.doc_id) m.set(d.doc_id, { title: d.title ?? d.doc_id, retrieved: d.retrieved_at });
    return m;
  }, [sources.data]);

  if (q.isLoading) return <MxLoading />;
  if (q.isError) return <MxError onRetry={() => q.refetch()} message={mx.zone.notFound} />;
  const data = q.data!;
  const zone = data.zone;
  const stateName = data.state.name;
  const statKeys = Object.keys(zone.stats);

  return (
    <div className="space-y-10">
      <nav aria-label={mx.common.breadcrumbLabel} className="text-sm text-muted-foreground">
        <Link to="/" className="hover:underline">{mx.common.breadcrumbHome}</Link>
        <span className="px-1.5" aria-hidden>›</span>
        <Link to="/requisitos/$cveEnt" params={{ cveEnt }} className="hover:underline">{stateName}</Link>
        <span className="px-1.5" aria-hidden>›</span>
        <span className="text-foreground">{zone.name}</span>
      </nav>

      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-serif text-3xl font-bold text-primary">{zone.name}, {stateName}</h1>
          <CoverageBadge coverage={data.state.legal_coverage} />
        </div>
        <Disclaimer />
      </header>

      <CoverageNotice coverage={data.state.legal_coverage} state={stateName} />

      {/* "What it costs to rent here" — three visually distinct treatments:
          (a) listing prices (user-published), (b) INEGI rented-share statistic, (c) legal requirements. */}
      <PriceBlock
        cveEnt={cveEnt}
        price={data.price_summary}
        rentedShare={zone.stats.pct_viviendas_alquiladas as MxStat | undefined}
        rentedShareSource={(s?: MxStat) => (s ? docTitle.get(s.source) : undefined)}
      />

      {/* Stats */}
      <section aria-labelledby="stats-title" className="space-y-3">
        <h2 id="stats-title" className="text-xl font-bold text-primary">{mx.zone.statsTitle}</h2>
        <p className="text-sm text-muted-foreground">{mx.zone.statsIntro}</p>
        {statKeys.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-muted-foreground">{mx.zone.statsEmpty}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {statKeys.map((k) => {
              const stat = zone.stats[k] as MxStat;
              const label = (mx.zone.stat as Record<string, string>)[k] ?? mx.zone.stat.other;
              const doc = docTitle.get(stat.source);
              return (
                <StatCard
                  key={k}
                  label={label}
                  value={formatInt(stat.value, lang)}
                  sourceLine={mx.zone.statSource(doc?.title ?? stat.source, stat.year)}
                  retrieved={doc?.retrieved ? mx.common.retrievedOn(formatDate(doc.retrieved, lang)) : undefined}
                />
              );
            })}
          </div>
        )}
        {zone.has_coords && zone.lat != null && zone.lon != null && zone.coord?.source ? (
          <figure className="space-y-2">
            <MxMap
              zones={[{
                cve_ent: cveEnt, cve_mun: cveMun, name: zone.name, lat: zone.lat, lon: zone.lon,
                has_coords: zone.has_coords, coord: zone.coord, listings_count: data.listings_count,
              } as MxMapZone]}
              selectedKey={zoneKey({ cve_ent: cveEnt, cve_mun: cveMun })}
              stateName={stateName}
            />
            <figcaption className="text-xs text-muted-foreground">{mx.zone.mapCaption}</figcaption>
          </figure>
        ) : (
          <p className="text-sm text-muted-foreground">{mx.zone.mapUnavailable}</p>
        )}
      </section>

      {/* Listings */}
      <ListingsSection cveEnt={cveEnt} cveMun={cveMun} zoneName={zone.name} listings={data.listings} />

      {/* Requirements summary */}
      <section className="space-y-3 rounded-xl border border-border bg-card p-5">
        <h2 className="text-xl font-bold text-primary">{mx.zone.requirementsTitle(stateName)}</h2>
        <p className="text-muted-foreground">
          {mx.zone.requirementsSummary(data.requirements_summary.count, Object.keys(data.requirements_summary.category_counts).length)}
        </p>
        <Button asChild variant="outline"><Link to="/requisitos/$cveEnt" params={{ cveEnt }}>{mx.zone.requirementsCta}</Link></Button>
      </section>
    </div>
  );
}

export function PriceBlock({
  cveEnt,
  price,
  rentedShare,
  rentedShareSource,
}: {
  cveEnt: string;
  price?: MxPriceSummary;
  rentedShare?: MxStat;
  rentedShareSource: (s?: MxStat) => { title: string; retrieved?: string } | undefined;
}) {
  const { mx, lang } = useMx();
  const p = mx.zone.price;
  const doc = rentedShareSource(rentedShare);

  return (
    <section aria-labelledby="price-title" className="space-y-4">
      <div className="space-y-1">
        <h2 id="price-title" className="text-xl font-bold text-primary">{p.title}</h2>
        <p className="text-sm text-muted-foreground">{p.intro}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* (a) Listing prices — user-published; blue "card" treatment with a provenance badge. */}
        <article className="flex flex-col gap-3 rounded-xl border-2 border-primary/30 bg-primary/5 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-primary">{p.listingsHeading}</h3>
          {price && price.has_stats && price.min != null && price.median != null && price.max != null ? (
            <>
              <span className="inline-flex w-fit items-center rounded-md bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
                {p.listingsBadge(price.count)}
              </span>
              <dl className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <dt className="text-xs text-muted-foreground">{p.min}</dt>
                  <dd className="font-bold tabular-nums text-foreground">{formatMXN(price.min, lang)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{p.median}</dt>
                  <dd className="text-lg font-bold tabular-nums text-primary">{formatMXN(price.median, lang)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{p.max}</dt>
                  <dd className="font-bold tabular-nums text-foreground">{formatMXN(price.max, lang)}</dd>
                </div>
              </dl>
              <p className="text-xs text-muted-foreground">{p.asOf(formatDate(price.as_of, lang))}</p>
            </>
          ) : price && price.count > 0 ? (
            <div className="rounded-lg border border-dashed border-primary/30 bg-background/60 p-3">
              <p className="font-medium text-foreground">{p.notEnoughTitle}</p>
              <p className="mt-1 text-sm text-muted-foreground">{p.notEnough(price.count, price.min_count_for_stats)}</p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{p.noListings}</p>
          )}
        </article>

        {/* (b) INEGI rented-share — statistic, NOT a price; muted "data" treatment with source + precision note. */}
        <article className="flex flex-col gap-2 rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{p.statHeading}</h3>
          {rentedShare ? (
            <>
              <p className="text-sm text-muted-foreground">{p.statLabel}</p>
              <p className="text-3xl font-bold tabular-nums text-foreground">{formatPct(rentedShare.value, lang)}</p>
              <p className="text-xs italic text-muted-foreground">{p.statCaveat}</p>
              <p className="text-xs text-muted-foreground">{p.statSource(doc?.title ?? rentedShare.source, rentedShare.year)}</p>
              {rentedShare.precision_baja && (
                <p className="mt-1 rounded-md border border-pending/40 bg-pending-soft px-2 py-1 text-xs text-pending">{p.lowPrecision}</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{p.statUnavailable}</p>
          )}
        </article>

        {/* (c) Legal requirements — the law; link out, no figures invented here. */}
        <article className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-card p-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-primary">{p.lawHeading}</h3>
          <p className="text-sm text-muted-foreground">{p.lawBody}</p>
          <Button asChild variant="outline" className="mt-auto w-fit">
            <Link to="/requisitos/$cveEnt" params={{ cveEnt }}>{p.lawCta}</Link>
          </Button>
        </article>
      </div>
    </section>
  );
}

function ListingsSection({ cveEnt, cveMun, zoneName, listings }: { cveEnt: string; cveMun: string; zoneName: string; listings: MxListing[] }) {
  const { mx, lang } = useMx();
  const [maxRent, setMaxRent] = useState("");
  const [bedrooms, setBedrooms] = useState("");

  const filtered = listings.filter((l) =>
    (!maxRent || l.monthly_rent_mxn <= Number(maxRent)) && (!bedrooms || l.bedrooms >= Number(bedrooms)));

  return (
    <section aria-labelledby="listings-title" className="space-y-4">
      <h2 id="listings-title" className="text-xl font-bold text-primary">{mx.zone.listingsTitle}</h2>

      {listings.length === 0 ? (
        <EmptyState
          icon={<Home className="h-6 w-6" />}
          title={mx.zone.listingsEmptyTitle}
          body={mx.zone.listingsEmptyBody}
          cta={<Button asChild><Link to="/publicar" search={{ cveEnt, cveMun }}>{mx.zone.listingsEmptyCta(zoneName)}</Link></Button>}
        />
      ) : (
        <>
          <fieldset className="flex flex-wrap items-end gap-3">
            <legend className="sr-only">{mx.zone.filtersLegend}</legend>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">{mx.zone.maxRent}</span>
              <input inputMode="decimal" value={maxRent} onChange={(e) => setMaxRent(e.target.value.replace(/[^\d.]/g, ""))}
                className="w-40 rounded-md border border-input bg-background px-3 py-2" />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">{mx.zone.bedrooms}</span>
              <select value={bedrooms} onChange={(e) => setBedrooms(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2">
                <option value="">{mx.zone.bedroomsAny}</option>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{mx.zone.bedroomsMin(n)}</option>)}
              </select>
            </label>
            {(maxRent || bedrooms) && (
              <Button variant="ghost" onClick={() => { setMaxRent(""); setBedrooms(""); }}>{mx.zone.clearFilters}</Button>
            )}
          </fieldset>
          {filtered.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-muted-foreground">{mx.zone.filtersNoResults(listings.length)}</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((l) => <ListingCard key={l.id} listing={l} />)}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ListingCard({ listing }: { listing: MxListing }) {
  const { mx, lang } = useMx();
  return (
    <Link to="/vivienda/$id" params={{ id: listing.id }}
      className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-accent/30">
      <div className="flex h-24 items-center justify-center rounded-lg bg-primary/5 text-primary/40" aria-hidden><Home className="h-8 w-8" /></div>
      <p className="text-lg font-bold text-foreground">{mx.listingCard.perMonth(formatMXN(listing.monthly_rent_mxn, lang))}</p>
      <p className="font-medium">{listing.title}</p>
      <p className="text-sm text-muted-foreground">
        {mx.listingCard.bedrooms(listing.bedrooms)} · {mx.listingCard.bathrooms(Number(listing.bathrooms))}
        {listing.area_m2 ? ` · ${mx.listingCard.area(String(listing.area_m2))}` : ""}
      </p>
      <p className="text-sm text-muted-foreground">{listing.colonia}</p>
      <span className="mt-1 inline-flex w-fit items-center rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">{mx.listingCard.userPublished}</span>
    </Link>
  );
}
