import { Link } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet, onWaking, type ResultKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function Shell({ children }: { children: ReactNode }) {
  const { t, mx, lang, setLang } = useI18n();
  const [waking, setWaking] = useState(false);
  useEffect(() => onWaking(setWaking), []);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const health = useQuery({ queryKey: ["mx-health", lang], queryFn: () => apiGet<{ disclaimer: string }>(`/mx/health?lang=${lang}`), staleTime: Infinity });
  const stored = useDisclaimer();
  const disclaimer = (stored?.lang === lang ? stored.text : undefined) ?? health.data?.disclaimer ?? mx.common.disclaimer;
  const nav = "px-3 py-2 rounded-md text-primary-foreground/85 hover:bg-primary-foreground/10";
  return (
    <div className="min-h-screen flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2 focus:bg-background">{mx.common.skipToContent}</a>
      <header className="bg-primary text-primary-foreground">
        <div className="mx-auto max-w-5xl px-4 py-4 flex flex-wrap items-center gap-3 justify-between">
          <Link to="/" className="font-serif text-lg font-bold">{mx.common.appName}</Link>
          <nav aria-label={mx.common.navLabel} className="flex flex-wrap items-center gap-1 text-[0.95rem]">
            <Link to="/" className={nav} activeOptions={{ exact: true }} activeProps={{ className: "bg-primary-foreground/15 font-semibold" }}>{mx.common.navSearch}</Link>
            <Link to="/publicar" className={nav} activeProps={{ className: "bg-primary-foreground/15 font-semibold" }}>{mx.common.navPublish}</Link>
            <Link to="/fuentes" className={nav} activeProps={{ className: "bg-primary-foreground/15 font-semibold" }}>{mx.common.navSources}</Link>
            <button onClick={() => setLang(lang === "en" ? "es" : "en")} aria-label={mx.common.langLabel}
              className="ml-2 rounded-md border border-primary-foreground/50 px-3 py-1.5 font-semibold hover:bg-primary-foreground/10">
              {mx.common.langToggle}
            </button>
          </nav>
        </div>
      </header>
      {waking && (
        <div role="status" className="bg-unknown-soft text-foreground border-b border-unknown/30">
          <div className="mx-auto max-w-5xl px-4 py-2 flex items-center gap-2 text-sm">
            <span className="h-3 w-3 rounded-full bg-unknown animate-pulse" aria-hidden /> {mx.common.waking}
          </div>
        </div>
      )}
      <main id="main" className="flex-1 mx-auto w-full max-w-5xl px-4 py-8 pb-28">{children}</main>
      <footer role="contentinfo" className="fixed bottom-0 inset-x-0 z-20 bg-foreground text-background">
        <div className="mx-auto max-w-5xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm min-h-10">
          <p className="flex-1 min-w-[16rem]">{disclaimer}</p>
          <a href="/us" className="shrink-0 underline underline-offset-2 opacity-80 hover:opacity-100">{mx.common.navPrevious}</a>
        </div>
      </footer>
    </div>
  );
}

let disclaimerStore: { lang: string; text: string } | undefined;
const dl = new Set<() => void>();
export function setDisclaimer(d?: string, lang?: string) { if (d && lang && (d !== disclaimerStore?.text || lang !== disclaimerStore?.lang)) { disclaimerStore = { lang, text: d }; dl.forEach((f) => f()); } }
function useDisclaimer() {
  const [, force] = useState(0);
  useEffect(() => { const f = () => force((x) => x + 1); dl.add(f); return () => { dl.delete(f); }; }, []);
  return disclaimerStore;
}

const badgeCls: Record<ResultKind, string> = {
  applies: "bg-applies-soft text-applies border-applies/40",
  superseded: "bg-superseded-soft text-superseded border-superseded/40",
  unknown: "bg-unknown-soft text-unknown border-unknown/40",
  not_yet_effective: "bg-future-soft text-future border-future/40",
  pending: "bg-pending-soft text-pending border-pending/40",
};
export function ResultBadge({ kind }: { kind: ResultKind }) {
  const { t } = useI18n();
  const label = kind === "unknown" ? t.unknownR : t[kind];
  return (
    <span aria-label={label} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-sm font-semibold ${badgeCls[kind] ?? badgeCls.unknown}`}>
      <span className="h-2 w-2 rounded-full bg-current" aria-hidden />{label}
    </span>
  );
}

export function StateMsg({ error, onRetry }: { error?: boolean; onRetry?: () => void }) {
  const { t } = useI18n();
  if (!error) return <p role="status" className="text-muted-foreground py-6">{t.loading}</p>;
  return (
    <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-4">
      <p>{t.error}</p>
      {onRetry && <button onClick={onRetry} className="mt-2 rounded-md bg-primary px-4 py-2 text-primary-foreground">{t.retry}</button>}
    </div>
  );
}
