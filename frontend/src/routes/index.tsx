import { createFileRoute } from "@tanstack/react-router";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { apiGet, type Address, type Fact, type Lookup, type Rule } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ResultBadge, StateMsg, setDisclaimer } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { CalendarIcon } from "lucide-react";
import { enUS, es } from "react-day-picker/locale";
import { formatDate } from "@/lib/dates";
import { Timeline } from "@/components/Timeline";
import { AudioPlayer } from "@/components/AudioPlayer";
import { WhyButton } from "@/components/WhyDrawer";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Address Lookup — Rental Housing Law Navigator" },
      { name: "description", content: "Search an address to see which rental housing rules apply today and what is about to change." },
      { property: "og:title", content: "Address Lookup — Rental Housing Law Navigator" },
      { property: "og:description", content: "Which housing rules apply at this address today, and what is about to change?" },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: LookupPage,
});

const DATES = ["2026-10-01", "2026-01-02", "2027-07-02"] as const;

function LookupPage() {
  const { t, lang } = useI18n();
  const [selected, setSelected] = useState<Address | null>(null);
  const [asOf, setAsOf] = useState("2026-10-01");
  const [search, setSearch] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const selectAddress = (address: Address) => {
    setSelected(address);
    setSearch(`${address.street}, ${address.city}`);
  };

  const lookup = useQuery({
    queryKey: ["lookup", selected?.address_id, asOf, lang],
    queryFn: () => {
      if (!selected) throw new Error("No address selected");
      return apiGet<Lookup>(`/lookup/${selected.address_id}?as_of=${asOf}&lang=${lang}`);
    },
    enabled: !!selected && /^\d{4}-\d{2}-\d{2}$/.test(asOf),
    placeholderData: (previous) => previous?.address.address_id === selected?.address_id ? keepPreviousData(previous) : undefined,
  });
  useEffect(() => setDisclaimer(lookup.data?.disclaimer, lang), [lookup.data, lang]);
  useEffect(() => {
    if (lookup.data?.address.address_id === selected?.address_id && lookup.data) {
      setSearch(`${lookup.data.address.street}, ${lookup.data.address.city}`);
    }
  }, [lookup.data, selected?.address_id]);

  const examples: Address[] = [
    { address_id: "A0016", street: "3515 FILLMORE ST", postal_city: "San Francisco", state: "CA", city: "San Francisco, CA" },
    { address_id: "A0489", street: "204 GRAND ST", postal_city: "Hoboken", state: "NJ", city: "Hoboken, NJ" },
    { address_id: "A0113", street: "3151 ETON AVE", postal_city: "Berkeley", state: "CA", city: "Berkeley, CA" },
    { address_id: "A0001", street: "6238 DE LONGPRE AVE", postal_city: "Los Angeles", state: "CA", city: "Los Angeles, CA" },
  ];

  return (
    <div className="space-y-8">
      <section className="space-y-5">
        <h1 className="text-3xl md:text-4xl font-bold text-primary max-w-3xl leading-tight">{t.tagline}</h1>
        <AddressSearch value={search} onChange={(value) => { setSearch(value); setSelected(null); }} onSelect={selectAddress} />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t.tryExamples}</span>
          {examples.map((e) => (
            <Button variant="outline" key={e.address_id} onClick={() => selectAddress(e)} className="rounded-full px-3 py-1 h-auto">
              {e.address_id} · {e.postal_city}
            </Button>
          ))}
        </div>
        <fieldset className="flex flex-wrap items-end gap-3">
          <legend className="sr-only">{t.asOf}</legend>
          <div className="flex flex-col text-sm font-semibold gap-1">
            <span>{t.asOf}</span>
            <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" aria-label={`${t.asOf}: ${formatDate(asOf, lang)}`}><CalendarIcon aria-hidden />{formatDate(asOf, lang)}</Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <Calendar mode="single" locale={lang === "es" ? es : enUS} captionLayout="dropdown" startMonth={new Date(1900, 0)} endMonth={new Date(2100, 11)} selected={new Date(`${asOf}T12:00:00`)} defaultMonth={new Date(`${asOf}T12:00:00`)} onSelect={(date) => {
                  if (!date) return;
                  setAsOf(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`);
                  setCalendarOpen(false);
                }} />
              </PopoverContent>
            </Popover>
          </div>
          {DATES.map((d, i) => (
            <Button variant="outline" key={d} onClick={() => setAsOf(d)} aria-pressed={asOf === d}
              className={`rounded-md border px-3 py-2 text-sm ${asOf === d ? "bg-primary text-primary-foreground border-primary" : "border-input hover:bg-accent"}`}>
               {i === 0 ? `${t.today} (${formatDate(d, lang)})` : formatDate(d, lang)}
             </Button>
          ))}
        </fieldset>
      </section>

      {selected && (lookup.data ? <ResultView data={lookup.data} refreshing={lookup.isFetching} /> : <StateMsg error={lookup.isError} onRetry={() => lookup.refetch()} />)}
      {selected && lookup.isError && lookup.data && <StateMsg error onRetry={() => lookup.refetch()} />}
    </div>
  );
}

function AddressSearch({ value: q, onChange, onSelect }: { value: string; onChange: (value: string) => void; onSelect: (a: Address) => void }) {
  const { t } = useI18n();
  const id = useId();
  const [deb, setDeb] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  useEffect(() => { const h = setTimeout(() => setDeb(q.trim()), 300); return () => clearTimeout(h); }, [q]);
  const res = useQuery({
    queryKey: ["addresses", deb],
    queryFn: () => apiGet<{ addresses: Address[] }>(`/addresses?q=${encodeURIComponent(deb)}&limit=20`),
    enabled: deb.length >= 2,
  });
  const list = res.data?.addresses ?? [];
  const pick = (a: Address) => { onSelect(a); setOpen(false); };
  return (
    <div className="relative max-w-2xl">
      <label htmlFor={id} className="block font-semibold mb-1">{t.searchLabel}</label>
      <input id={id} role="combobox" aria-expanded={open} aria-controls={id + "-list"} aria-autocomplete="list"
        value={q} placeholder={t.searchPlaceholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, list.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          if (e.key === "Enter" && list[active]) pick(list[active]);
          if (e.key === "Escape") setOpen(false);
        }}
        className="w-full rounded-md border-2 border-input px-4 py-3.5 text-lg focus:border-primary" />
      {open && deb.length >= 2 && (
        <ul id={id + "-list"} role="listbox" className="absolute z-10 mt-1 w-full max-h-80 overflow-auto rounded-md border bg-popover shadow-lg">
          {res.isFetching && !list.length && <li className="px-4 py-3 text-muted-foreground">{t.loading}</li>}
          {!res.isFetching && !list.length && <li className="px-4 py-3 text-muted-foreground">{t.noMatches}</li>}
          {list.map((a, i) => (
            <li key={a.address_id} role="option" aria-selected={i === active} onMouseDown={() => pick(a)}
              className={`px-4 py-2.5 cursor-pointer ${i === active ? "bg-accent" : ""}`}>
              <span className="font-semibold">{a.street}</span> <span className="text-muted-foreground">· {a.city}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function certaintyLabel(c: string | undefined, t: ReturnType<typeof useI18n>["t"]) {
  if (c === "exact") return t.exact;
  if (c === "parsed") return t.parsed;
  if (c === "range") return t.range;
  if (!c || c === "unknown") return t.unknown;
  return t.estimated;
}
function FactRow({ label, fact, value }: { label: string; fact?: Fact | undefined; value: string }) {
  const { t } = useI18n();
  const c = fact?.certainty;
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold">{value}{" "}
        <span className={`ml-1 rounded px-1.5 py-0.5 text-xs font-medium ${c === "exact" ? "bg-applies-soft text-applies" : !c || c === "unknown" ? "bg-superseded-soft text-superseded" : "bg-unknown-soft text-unknown"}`}>{certaintyLabel(c, t)}</span>
      </dd>
    </div>
  );
}

function ResultView({ data, refreshing }: { data: Lookup; refreshing: boolean }) {
  const { t, lang } = useI18n();
  const u = data.building_facts.units;
  const units = u?.range ? (u.range[1] == null ? `${u.range[0]}+` : u.range[0] === u.range[1] ? `${u.range[0]}` : `${u.range[0]}–${u.range[1]}`) : u?.value != null ? String(u.value) : "—";
  const yb = data.building_facts.year_built?.value as number | null | undefined;
  const c = data.jurisdiction_stack.coordinates;
  const order: string[] = ["applies", "not_yet_effective", "pending", "unknown", "superseded"];
  const counts = Object.entries(data.counts).filter(([, n]) => n > 0).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  return (
    <div className={`space-y-8 transition-opacity ${refreshing ? "opacity-60" : ""}`} aria-busy={refreshing}>
      <section className="rounded-lg border bg-card overflow-hidden md:grid md:grid-cols-[1fr_280px]">
        <div className="p-6 space-y-4">
          <div>
            <h2 className="text-2xl font-bold">{data.address.street}</h2>
            <p className="text-muted-foreground">{data.address.postal_city}, {data.address.state}</p>
          </div>
          <dl className="grid grid-cols-2 gap-4">
            <FactRow label={t.units} fact={u} value={units} />
            <FactRow label={t.yearBuilt} fact={data.building_facts.year_built} value={yb ? String(yb) : "—"} />
          </dl>
          <p className="text-sm"><span className="text-muted-foreground">{t.jurisdiction}: </span>
            <strong>{data.jurisdiction_stack.state} › {data.jurisdiction_stack.city}</strong></p>
           <p className="text-sm text-muted-foreground">{t.asOf}: {formatDate(data.as_of, lang)}</p>
        </div>
        {c && (
          <iframe title="Map" className="w-full h-56 md:h-full border-0 border-t md:border-t-0 md:border-l"
            src={`https://www.openstreetmap.org/export/embed.html?bbox=${c.lon - 0.006},${c.lat - 0.004},${c.lon + 0.006},${c.lat + 0.004}&layer=mapnik&marker=${c.lat},${c.lon}`} />
        )}
      </section>

      <Timeline addressId={data.address.address_id} />

      <div aria-label={t.resultLegend} className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {(["applies", "superseded", "unknown", "not_yet_effective", "pending"] as const).map(kind => (
          <ResultBadge key={kind} kind={kind} />
        ))}
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Summary">
        {counts.map(([k, n]) => (
          <span key={k} className="inline-flex items-center gap-2"><span className="font-bold text-lg">{n}</span><ResultBadge kind={k as Rule["result"]} /></span>
        ))}
      </div>

      {(() => { const firstAudio = data.category_order.flatMap((c) => data.results[c] ?? []).find((r) => r.audio_url)?.team_rule_id; return data.category_order.map((cat) => {
        const rules = data.results[cat] ?? [];
        if (!rules.length) return null;
        return (
          <section key={cat} className="space-y-4">
            <h2 className="text-xl font-bold border-b-2 border-primary pb-1 text-primary">{cat}</h2>
            {rules.map((r) => <RuleCard key={r.team_rule_id} r={r} addressId={data.address.address_id} asOf={data.as_of} firstAudio={r.team_rule_id === firstAudio} />)}
          </section>
        );
      }); })()}
    </div>
  );
}

function RuleCard({ r, addressId, asOf, firstAudio }: { r: Rule; addressId: string; asOf: string; firstAudio: boolean }) {
  const { t, lang } = useI18n();

  const pl = r.plain_language ?? {};
  return (
    <article className="rounded-lg border bg-card p-5 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ResultBadge kind={r.result} />
        <span className="text-xs uppercase tracking-wide text-muted-foreground">{r.level === "state" ? t.stateLevel : t.cityLevel} · {r.team_rule_id}</span>
        {r.conflict_flag && <span title={r.conflict_note ?? undefined} aria-label={`${t.conflict}${r.conflict_note ? ": " + r.conflict_note : ""}`} tabIndex={0} className="rounded border border-destructive/40 bg-destructive/5 px-2 py-0.5 text-xs font-semibold text-destructive cursor-help">{t.conflict}</span>}
        {r.needs_review && <span className="rounded border border-unknown/40 bg-unknown-soft px-2 py-0.5 text-xs font-semibold text-unknown">{t.lowConf}</span>}
        {r.attested && <span className="rounded border border-input bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">{t.attested}</span>}
      </div>
      <h3 className="text-lg font-bold font-sans">{r.title}</h3>
      {r.result === "superseded" && r.superseded_by && <p className="text-superseded font-medium">{t.supersededBy(r.superseded_by)}</p>}
      {r.result === "unknown" && !!r.missing_facts?.length && <p className="text-unknown font-medium">{t.dependsOn((r.missing_facts_label?.length ? r.missing_facts_label : r.missing_facts).join(", "))}</p>}
      {r.result === "not_yet_effective" && r.effective_date && <p className="text-future font-medium">{t.effectiveOn(formatDate(r.effective_date, lang))}</p>}
      {r.result === "pending" && <p className="text-pending font-medium">{t.pendingNote}</p>}
      {pl.status_line && <p className="font-bold">{pl.status_line}</p>}
      {pl.what_it_means && <p>{pl.what_it_means}</p>}
      {pl.who_it_covers && <p><span className="font-semibold">{t.whoCovers}: </span>{pl.who_it_covers}</p>}
      {pl.what_you_can_do && (
        <div className="rounded-md border-l-4 border-primary bg-highlight p-4">
          <p className="font-semibold text-primary">{t.whatYouCanDo}</p>
          <p>{pl.what_you_can_do}</p>
        </div>
      )}
      {r.audio_url && <AudioPlayer url={r.audio_url} showNote={firstAudio} />}
      <div className="flex justify-end"><WhyButton addressId={addressId} ruleId={r.team_rule_id} asOf={asOf.slice(0, 10)} /></div>
      <details className="group rounded-md border">
        <summary className="cursor-pointer px-4 py-2.5 font-semibold text-primary">{t.legalDetails}</summary>
        <div className="space-y-3 px-4 pb-4 text-[0.95rem]">
          {r.citation && <p><span className="font-semibold">{t.citation}: </span>{r.citation}</p>}
          {r.quoted_span && (
            <figure>
              <figcaption className="text-sm font-semibold text-muted-foreground">{t.exactText}</figcaption>
              <blockquote className="mt-1 border-l-4 border-input pl-4 italic">“{r.quoted_span}”</blockquote>
            </figure>
          )}
          <p className="flex flex-wrap gap-3 text-sm">
            {r.source_url && <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="text-primary underline">{t.source} ↗</a>}
            {r.retrieved_at && <span className="text-muted-foreground">{t.retrieved(formatDate(r.retrieved_at, lang))}</span>}
          </p>
          {typeof r.confidence === "number" && (
            <div className="flex items-center gap-2 text-sm">
              <span>{t.confidence}</span>
              <div className="h-2 w-32 rounded bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(r.confidence * 100)} aria-label={t.confidence}>
                <div className="h-2 rounded bg-primary" style={{ width: `${r.confidence * 100}%` }} />
              </div>
              <span>{Math.round(r.confidence * 100)}%</span>
            </div>
          )}
          {!!r.presumptions?.length && (
            <div><p className="font-semibold">{t.presumptions}</p><ul className="list-disc pl-5">{r.presumptions.map((p, i) => <li key={i}>{p}</li>)}</ul></div>
          )}
          <div><p className="font-semibold">{t.explanation}</p><p className="text-muted-foreground">{r.explanation}</p></div>
        </div>
      </details>
    </article>
  );
}
