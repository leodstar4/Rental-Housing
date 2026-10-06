import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Check } from "lucide-react";

import {
  apiGet,
  apiPost,
  conflictCode,
  fieldErrors,
  type MxContract,
  type MxRole,
  type MxSignResponse,
  type MxSignRequest,
} from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import { Disclaimer, HashChip, MxError, MxLoading, useMx } from "@/components/mx/MxShared";
import { shortHash } from "@/lib/mx-i18n";
import { formatDate } from "@/lib/dates";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/contrato/$id")({
  component: ContractPage,
});

const STATUS_TONE: Record<string, string> = {
  pendiente: "border-future/40 bg-future-soft text-future",
  parcial: "border-unknown/40 bg-unknown-soft text-unknown",
  firmado: "border-applies/40 bg-applies-soft text-applies",
  invalidado: "border-destructive/40 bg-destructive/5 text-destructive",
};

function ContractPage() {
  const { id } = Route.useParams();
  const { mx, lang } = useMx();
  // One-time sign tokens handed over by the contract-form navigation (never persisted server-side plain).
  const signTokens = (Route.useRouteContext() as never) && ((history.state?.signTokens ?? {}) as Partial<Record<MxRole, string>>);
  const q = useQuery({
    queryKey: ["mx-contract", id, lang],
    queryFn: () => apiGet<MxContract>(`/mx/contracts/${id}?lang=${lang}`),
    refetchOnWindowFocus: true,
  });
  useEffect(() => setDisclaimer(q.data?.disclaimer, lang), [q.data, lang]);

  if (q.isLoading) return <MxLoading />;
  if (q.isError) return <MxError onRetry={() => q.refetch()} message={mx.contract.notFound} />;
  const c = q.data!;
  const st = c.status;
  const signedRoles = new Set(c.signatures.map((s) => s.role));
  const pendingRoles = c.required_roles.filter((r) => st.roles[r] !== "valida");

  return (
    <div className="space-y-8">
      <nav aria-label={mx.common.breadcrumbLabel} className="text-sm text-muted-foreground">
        <Link to="/" className="hover:underline">{mx.common.breadcrumbHome}</Link>
        <span className="px-1.5" aria-hidden>›</span>
        <span className="text-foreground">{mx.contract.title}</span>
      </nav>

      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-serif text-3xl font-bold text-primary">{mx.contract.title}</h1>
          <span className={`rounded-full border px-3 py-0.5 text-sm font-semibold ${STATUS_TONE[st.overall]}`}>{mx.contract.status[st.overall]}</span>
        </div>
        <p className="text-sm text-muted-foreground">{mx.contract.signaturesProgress(st.valid_count, st.required_count)}</p>
      </header>

      {st.overall === "invalidado" && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <p className="flex items-center gap-2 font-semibold text-destructive"><AlertTriangle className="h-5 w-5" aria-hidden />{mx.contract.changedTitle}</p>
          <p className="mt-1 text-sm text-muted-foreground">{mx.contract.changedBody}</p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="order-2 space-y-6 lg:order-1">
          {/* Clauses */}
          <section className="space-y-4">
            <h2 className="text-xl font-bold text-primary">{mx.contract.clausesTitle}</h2>
            {c.clauses.map((cl) => (
              <article key={cl.n} className="rounded-lg border border-border bg-card p-4">
                <h3 className="font-serif font-bold">{mx.contract.clauseNumber(cl.n)}. {cl.title}</h3>
                <p className="mt-1 whitespace-pre-line font-serif text-foreground">{cl.text}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {cl.requirement_ids.length ? `${mx.contract.clauseBasis}: ${cl.requirement_ids.join(", ")}` : mx.contract.clauseNoBasis}
                </p>
              </article>
            ))}
          </section>

          {/* Legal basis annex */}
          {c.legal_basis.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-xl font-bold text-primary">{mx.contract.legalBasisTitle}</h2>
              <p className="text-sm text-muted-foreground">{mx.contract.legalBasisIntro}</p>
              {c.legal_basis.map((b) => (
                <div key={b.id} className="rounded-lg border border-border bg-card p-4">
                  <p className="font-mono text-xs text-muted-foreground">[{b.id}] {b.citation}</p>
                  <blockquote lang="es" className="mt-1 border-l-4 border-primary/40 pl-3 font-serif text-foreground">“{b.quote}”</blockquote>
                </div>
              ))}
            </section>
          )}

          {/* Sign form */}
          {pendingRoles.length > 0 && (
            <SignSection contract={c} pendingRoles={pendingRoles} signTokens={signTokens} onSigned={() => q.refetch()} />
          )}
          {st.overall === "firmado" && (
            <section className="rounded-xl border border-applies/30 bg-applies-soft/40 p-5">
              <h2 className="flex items-center gap-2 font-semibold text-foreground"><Check className="h-5 w-5 text-applies" aria-hidden />{mx.contract.allSignedTitle}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{mx.contract.allSignedBody}</p>
            </section>
          )}
        </div>

        {/* Status panel */}
        <aside className="order-1 space-y-4 lg:order-2 lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold">{mx.contract.partiesTitle}</h2>
            <ul className="mt-2 space-y-2 text-sm">
              {c.required_roles.map((r) => {
                const sig = c.signatures.find((s) => s.role === r);
                const state = st.roles[r];
                return (
                  <li key={r} className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0">
                    <span className="font-medium">{mx.contract.role[r]}</span>
                    <span className={state === "valida" ? "text-applies" : state === "invalida" ? "text-destructive line-through" : "text-muted-foreground"}>
                      {state === "valida" && sig ? mx.contract.sigSigned(formatDate(sig.signed_at, lang)) : state === "invalida" ? mx.contract.sigInvalidated : mx.contract.sigPending}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="text-sm font-medium">{mx.contract.hashLabel}</p>
            <div className="mt-2"><HashChip sha={st.sha256_current} label={mx.contract.hashLabel} /></div>
            <p className="mt-2 text-xs text-muted-foreground">{mx.contract.hashHelp}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold">{mx.contract.shareTitle}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{mx.contract.shareBody}</p>
            <Button variant="outline" className="mt-2 w-full" onClick={() => navigator.clipboard?.writeText(window.location.href)}>{mx.contract.copyLink}</Button>
            <Button variant="ghost" className="mt-1 w-full" onClick={() => window.print()}>{mx.contract.print}</Button>
          </div>
        </aside>
      </div>
      <Disclaimer />
    </div>
  );
}

function SignSection({ contract, pendingRoles, signTokens, onSigned }: {
  contract: MxContract; pendingRoles: MxRole[]; signTokens: Partial<Record<MxRole, string>>; onSigned: () => void;
}) {
  const { mx } = useMx();
  const [role, setRole] = useState<MxRole>(pendingRoles[0]);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [typed, setTyped] = useState("");
  const [token, setToken] = useState("");
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sha = contract.status.sha256_current;

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    if (!consent) { setError(mx.sign.errConsent); return; }
    if (!typed.trim()) { setError(mx.sign.errEmptySignature); return; }
    const effectiveToken = token || signTokens[role] || "";
    const body: MxSignRequest = {
      role, full_name: fullName.trim(), email: email.trim(), signature_png_base64: null,
      typed_signature: typed.trim(), method: "tecleada", consent: true, contract_sha256: sha, token: effectiveToken,
    };
    setSubmitting(true);
    try {
      await apiPost<MxSignResponse>(`/mx/contracts/${contract.contract_id}/sign`, body);
      onSigned();
      setFullName(""); setEmail(""); setTyped(""); setConsent(false); setToken("");
    } catch (err) {
      const code = conflictCode(err);
      if (code === "already_signed") setError(mx.sign.errConflict(mx.contract.role[role]));
      else if (code === "hash_changed") setError(mx.sign.errHashChanged);
      else if (fieldErrors(err).length) setError(fieldErrors(err)[0].msg);
      else setError(mx.sign.errSubmit);
    } finally {
      setSubmitting(false);
    }
  }

  const cls = "rounded-md border border-input bg-background px-3 py-2";
  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-primary/20 bg-primary/5 p-5">
      <h2 className="font-serif text-xl font-bold text-primary">{mx.sign.title}</h2>
      <p className="text-sm text-muted-foreground">{mx.sign.readFirst}</p>

      <div className="rounded-lg border border-border bg-card p-4 text-sm">
        <p className="font-semibold">{mx.sign.scopeTitle}</p>
        <p className="mt-1 text-muted-foreground">{mx.sign.scopeBody}</p>
        <p className="mt-1 text-muted-foreground">{mx.sign.scopeNotIncluded}</p>
      </div>

      {error && <MxError message={error} />}

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{mx.sign.roleLegend}</legend>
        <div className="flex flex-wrap gap-2">
          {contract.required_roles.map((r) => {
            const already = contract.status.roles[r] === "valida";
            return (
              <label key={r} className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${already ? "opacity-50" : "cursor-pointer"} ${role === r ? "border-primary bg-primary/10" : "border-input"}`}>
                <input type="radio" name="role" value={r} checked={role === r} disabled={already} onChange={() => setRole(r)} className="h-4 w-4" />
                {mx.contract.role[r]}{already ? ` · ${mx.sign.roleAlreadySigned}` : ""}
              </label>
            );
          })}
        </div>
      </fieldset>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">{mx.sign.fullName}</span>
        <input className={cls} value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
        <span className="text-xs text-muted-foreground">{mx.sign.fullNameHint}</span>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">{mx.sign.email}</span>
        <input type="email" className={cls} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
      </label>

      {!signTokens[role] && (
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Token de firma</span>
          <input className={cls} value={token} onChange={(e) => setToken(e.target.value)} />
          <span className="text-xs text-muted-foreground">Lo recibió quien generó el contrato.</span>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">{mx.sign.typedLabel}</span>
        <input className={`${cls} font-serif text-lg italic`} value={typed} onChange={(e) => setTyped(e.target.value)} />
        {typed && <span className="mt-1 rounded-md border border-dashed border-border px-3 py-2 font-serif text-2xl italic">{typed}</span>}
      </label>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4" />
        {mx.sign.consent(shortHash(sha))}
      </label>

      <Button type="submit" disabled={submitting}>{submitting ? mx.sign.signing : mx.sign.submit}</Button>
    </form>
  );
}
