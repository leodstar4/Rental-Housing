import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiGet, type MxRequirements, type MxRequirementItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { setDisclaimer } from "@/components/Shell";
import {
  CoverageNotice,
  Disclaimer,
  FundamentoButton,
  KindBadge,
  MxError,
  MxLoading,
  useMx,
} from "@/components/mx/MxShared";
import { MX_CATEGORY_ORDER, type MxCopy } from "@/lib/mx-i18n";

export const Route = createFileRoute("/requisitos/$cveEnt")({
  component: RequirementsPage,
});

function RequirementsPage() {
  const { cveEnt } = Route.useParams();
  const { mx, lang } = useMx();
  const [showPractice, setShowPractice] = useState(false);

  const q = useQuery({
    queryKey: ["mx-requirements", cveEnt, lang],
    queryFn: () => apiGet<MxRequirements>(`/mx/requirements?cve_ent=${cveEnt}&lang=${lang}`),
  });
  useEffect(() => setDisclaimer(q.data?.disclaimer, lang), [q.data, lang]);

  if (q.isLoading) return <MxLoading />;
  if (q.isError) return <MxError onRetry={() => q.refetch()} message={mx.requirements.notFound} />;
  const data = q.data!;
  const stateName = data.state;

  // Order the categories per the UX blueprint; keep only those with items.
  const cats = MX_CATEGORY_ORDER.filter((c) => (data.categories[c]?.length ?? 0) > 0);

  return (
    <div className="space-y-8">
      <nav aria-label={mx.common.breadcrumbLabel} className="text-sm text-muted-foreground">
        <Link to="/" className="hover:underline">{mx.common.breadcrumbHome}</Link>
        <span className="px-1.5" aria-hidden>›</span>
        <span className="text-foreground">{stateName}</span>
      </nav>

      <header className="space-y-3">
        <h1 className="font-serif text-3xl font-bold text-primary">{mx.requirements.title(stateName)}</h1>
        <p className="max-w-prose text-muted-foreground">{mx.requirements.intro}</p>
        <Disclaimer />
      </header>

      <CoverageNotice coverage={data.legal_coverage} state={stateName} />

      {/* Category index */}
      {cats.length > 0 && (
        <nav aria-label={mx.category.jumpTo} className="flex flex-wrap gap-2">
          {cats.map((c) => (
            <a key={c} href={`#cat-${c}`} className="rounded-full border border-border bg-card px-3 py-1 text-sm hover:bg-accent">
              {mx.category[c]} <span className="text-muted-foreground">({data.categories[c].length})</span>
            </a>
          ))}
        </nav>
      )}

      <label className="flex w-fit items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm">
        <input type="checkbox" checked={showPractice} onChange={(e) => setShowPractice(e.target.checked)} className="h-4 w-4" />
        {mx.kind.showPractice}
      </label>

      {cats.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center text-muted-foreground">{mx.requirements.empty}</p>
      ) : (
        cats.map((cat) => {
          const items = data.categories[cat].filter((it) => showPractice || it.kind !== "practica");
          if (!items.length) return null;
          const estatal = items.filter((it) => it.level === "estatal");
          const federal = items.filter((it) => it.level === "federal");
          return (
            <section key={cat} id={`cat-${cat}`} className="scroll-mt-24 space-y-4">
              <h2 className="border-b-2 border-primary pb-1 text-xl font-bold text-primary">{mx.category[cat]}</h2>
              {estatal.length > 0 && <SubGroup title={mx.level.stateSection(stateName)} items={estatal} />}
              {federal.length > 0 && <SubGroup title={mx.level.federalSection} items={federal} />}
            </section>
          );
        })
      )}
    </div>
  );
}

function SubGroup({ title, items }: { title: string; items: MxRequirementItem[] }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {items.map((it) => <RequirementItem key={it.id} item={it} />)}
    </div>
  );
}

function RequirementItem({ item }: { item: MxRequirementItem }) {
  const { mx } = useMx();
  const [reviewed, setReviewed] = useState(false);
  const practica = item.kind === "practica";
  return (
    <article className={`rounded-lg border bg-card p-4 ${practica ? "border-dashed border-pending/40" : "border-border"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <KindBadge kind={item.kind} />
        {item.applies_to_contract && <span className="rounded-md bg-applies-soft px-2 py-0.5 text-xs font-medium text-applies">{mx.fundamento.usedInContract}</span>}
      </div>
      <h4 className="mt-2 text-lg font-semibold">{item.title}</h4>
      <p className="mt-1 text-sm text-foreground">{item.summary}</p>
      {practica && <p className="mt-1 text-xs text-muted-foreground">{mx.kind.practicaHelp}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} className="h-4 w-4" />
          {mx.requirements.markReviewed}
        </label>
        <FundamentoButton item={item} />
      </div>
    </article>
  );
}
