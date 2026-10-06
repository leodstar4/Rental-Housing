/**
 * Shared Renta MX UI primitives (docs/MX_UX.md §6, P0/P1).
 *
 * Rules enforced here:
 * - Legal text is never authored in the UI: FundamentoSheet shows the API's citation/quote verbatim.
 * - Empty lists render an honest EmptyState, never ghost/skeleton cards.
 * - Status is shown with icon + text + color, never color alone (WCAG).
 */
import { type ReactNode, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  FileText,
  Info,
  Inbox,
  Loader2,
} from "lucide-react";

import { type MxCoverage, type MxKind, type MxRequirementItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { shortHash } from "@/lib/mx-i18n";
import { formatDate } from "@/lib/dates";
import { useIsMobile } from "@/hooks/use-mobile";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/** Convenience hook: Renta MX copy + current language. */
export function useMx() {
  const { mx, lang } = useI18n();
  return { mx, lang };
}

// --------------------------------------------------------------------------- //
// Loading / error / empty
// --------------------------------------------------------------------------- //

export function MxLoading({ label }: { label?: string }) {
  const { mx } = useMx();
  return (
    <p role="status" aria-busy="true" className="flex items-center gap-2 py-8 text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label ?? mx.common.loading}
    </p>
  );
}

export function MxError({ onRetry, message }: { onRetry?: () => void; message?: string }) {
  const { mx } = useMx();
  return (
    <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
      <p className="text-foreground">{message ?? mx.common.error}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-3 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
          {mx.common.retry}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, body, cta, icon }: { title: string; body: string; cta?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-muted/30 px-6 py-12 text-center">
      <span className="rounded-full bg-muted p-3 text-muted-foreground" aria-hidden>{icon ?? <Inbox className="h-6 w-6" />}</span>
      <h3 className="text-lg font-semibold text-foreground">{title}</h3>
      <p className="max-w-prose text-sm text-muted-foreground">{body}</p>
      {cta && <div className="mt-2">{cta}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Coverage (verified state law vs federal-only). Icon + text, informative tone.
// --------------------------------------------------------------------------- //

export function CoverageBadge({ coverage }: { coverage: MxCoverage }) {
  const { mx } = useMx();
  const verified = coverage === "estatal_verificada";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-sm font-semibold ${
        verified ? "border-applies/40 bg-applies-soft text-applies" : "border-unknown/40 bg-unknown-soft text-unknown"
      }`}
    >
      {verified ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Info className="h-3.5 w-3.5" aria-hidden />}
      {verified ? mx.coverage.stateVerified : mx.coverage.federalOnly}
    </span>
  );
}

export function CoverageNotice({ coverage, state }: { coverage: MxCoverage; state: string }) {
  const { mx } = useMx();
  if (coverage !== "solo_federal") return null;
  return (
    <div className="flex gap-3 rounded-lg border border-unknown/30 bg-unknown-soft/60 p-4 text-sm text-foreground">
      <Info className="mt-0.5 h-5 w-5 shrink-0 text-unknown" aria-hidden />
      <div>
        <p className="font-semibold">{mx.coverage.federalOnlyTitle(state)}</p>
        <p className="mt-1 text-muted-foreground">{mx.coverage.federalOnlyBody}</p>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Requirement kind badge (law vs market practice)
// --------------------------------------------------------------------------- //

export function KindBadge({ kind }: { kind: MxKind }) {
  const { mx } = useMx();
  const label = mx.kind[kind];
  if (kind === "practica") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-pending/50 bg-pending-soft px-2 py-0.5 text-xs font-semibold text-pending">
        {label} · {mx.kind.practicaNotLaw}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
      {label}
    </span>
  );
}

// --------------------------------------------------------------------------- //
// SHA-256 chip: shows 8 chars, copyable, aria-label with the full hash.
// --------------------------------------------------------------------------- //

export function HashChip({ sha, label }: { sha: string; label?: string }) {
  const { mx } = useMx();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sha);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`${label ?? mx.common.sha256Label}: ${sha}`}
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/50 px-2 py-1 font-mono text-xs text-foreground hover:bg-muted"
    >
      {shortHash(sha)}
      {copied ? <Check className="h-3.5 w-3.5 text-applies" aria-hidden /> : <Copy className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />}
      <span className="sr-only" role="status">{copied ? mx.common.copied : ""}</span>
    </button>
  );
}

// --------------------------------------------------------------------------- //
// StatCard: one INEGI figure with its source line (never a value without source).
// --------------------------------------------------------------------------- //

export function StatCard({ label, value, sourceLine, retrieved }: { label: string; value: string; sourceLine: string; retrieved?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">{value}</p>
      <p className="mt-2 text-xs text-muted-foreground">{sourceLine}</p>
      {retrieved && <p className="text-xs text-muted-foreground">{retrieved}</p>}
    </div>
  );
}

export function StatNoData({ label }: { label: string }) {
  const { mx } = useMx();
  return (
    <div className="rounded-xl border border-dashed border-border bg-muted/20 p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-base italic text-muted-foreground">{mx.zone.statNoData}</p>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// FundamentoSheet: the API's citation + literal quote, verbatim (never reworded).
// --------------------------------------------------------------------------- //

export function FundamentoSheet({ item, open, onOpenChange }: { item: MxRequirementItem | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { mx, lang } = useMx();
  const isMobile = useIsMobile();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={isMobile ? "bottom" : "right"} className="w-full overflow-y-auto sm:max-w-lg">
        {item && (
          <>
            <SheetHeader className="text-left">
              <SheetTitle className="font-serif text-lg">{item.title}</SheetTitle>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  {item.level === "federal" ? mx.level.federal : mx.level.estatal}
                </span>
                <KindBadge kind={item.kind} />
                {item.applies_to_contract && (
                  <span className="rounded-md bg-applies-soft px-2 py-0.5 text-xs font-medium text-applies">{mx.fundamento.usedInContract}</span>
                )}
              </div>
            </SheetHeader>

            <div className="mt-4 space-y-5 text-sm">
              <section>
                <h3 className="font-semibold text-foreground">{mx.fundamento.plainSummary}</h3>
                <p className="mt-1 text-foreground">{item.summary}</p>
                <p className="mt-1 text-xs text-muted-foreground">{mx.fundamento.summaryCaveat}</p>
              </section>

              <section>
                <h3 className="font-semibold text-foreground">{mx.fundamento.citation}</h3>
                <p className="mt-1 font-medium text-foreground">{item.citation}</p>
              </section>

              <section>
                <h3 className="font-semibold text-foreground">{mx.fundamento.quoteLabel}</h3>
                <blockquote lang="es" className="mt-1 border-l-4 border-primary/40 bg-muted/40 py-2 pl-3 pr-2 font-serif text-foreground">
                  “{item.quote}”
                </blockquote>
                <p className="mt-1 flex items-center gap-1.5 text-xs text-applies">
                  <Check className="h-3.5 w-3.5" aria-hidden /> {mx.fundamento.quoteVerified}
                </p>
                {lang === "en" && <p className="text-xs text-muted-foreground">{mx.fundamento.quoteLangNote}</p>}
              </section>

              <section className="space-y-1 border-t border-border pt-4">
                <p className="font-semibold text-foreground">{item.doc_title}</p>
                <p className="text-muted-foreground">{mx.fundamento.publisher}: {item.publisher}</p>
                {item.retrieved_at && <p className="text-muted-foreground">{mx.common.retrievedOn(formatDate(item.retrieved_at, lang))}</p>}
                {item.last_reform && <p className="text-muted-foreground">{mx.common.lastReform(item.last_reform)}</p>}
                <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden /> {mx.common.openSource}
                  <span className="sr-only">{mx.common.openInNewTab}</span>
                </a>
                <p className="pt-2 font-mono text-xs text-muted-foreground">{mx.fundamento.requirementId}: {item.id}</p>
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

/** Small "see legal basis" button that opens a FundamentoSheet; manages its own state. */
export function FundamentoButton({ item }: { item: MxRequirementItem }) {
  const { mx } = useMx();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-sm font-medium text-foreground hover:bg-muted"
      >
        <FileText className="h-3.5 w-3.5" aria-hidden /> {mx.fundamento.button}
      </button>
      <FundamentoSheet item={item} open={open} onOpenChange={setOpen} />
    </>
  );
}

export function Disclaimer({ text }: { text?: string }) {
  const { mx } = useMx();
  return (
    <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {text ?? mx.common.disclaimer}
    </p>
  );
}
