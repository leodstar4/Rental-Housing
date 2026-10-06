import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Check, Download, Link2, Printer } from "lucide-react";

import {
  apiGet,
  apiPost,
  type MxContract,
  type MxEvidence,
  type MxRequirementItem,
  type MxRequirements,
  type MxRole,
  type MxSignResponse,
  type MxSignRequest,
} from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import { Disclaimer, FundamentoButton, HashChip, MxError, MxLoading, useMx } from "@/components/mx/MxShared";
import { SignaturePad, type SignatureValue } from "@/components/mx/SignaturePad";
import { buildSignLink, classifySignError, readSignLinkParams } from "@/lib/mx-sign";
import { shortHash } from "@/lib/mx-i18n";
import { formatDate } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export const Route = createFileRoute("/contrato/$id")({
  component: ContractPage,
});

const STATUS_TONE: Record<string, string> = {
  pendiente: "border-future/40 bg-future-soft text-future",
  parcial: "border-unknown/40 bg-unknown-soft text-unknown",
  firmado: "border-applies/40 bg-applies-soft text-applies",
  invalidado: "border-destructive/40 bg-destructive/5 text-destructive",
};

/** One-time sign tokens, read once from history.state (contract-form navigation) or the `#t=` hash. */
function useSignLinkContext() {
  // From the contract-form navigation: history.state.signTokens is the full per-role map (shown once).
  const [state] = useState<Partial<Record<MxRole, string>>>(
    () => (typeof history !== "undefined" ? ((history.state?.signTokens ?? {}) as Partial<Record<MxRole, string>>) : {}),
  );
  // From a per-role signing link `/contrato/{id}?rol=<rol>#t=<token>`: read once, then strip the
  // fragment from the address bar so the token does not linger in history or the Referer header.
  const [fromLink] = useState<{ role: MxRole | null; token: string | null }>(() => {
    if (typeof window === "undefined") return { role: null, token: null };
    const { role, token, hadFragmentToken } = readSignLinkParams(window.location.search, window.location.hash);
    if (hadFragmentToken) {
      history.replaceState(history.state, "", window.location.pathname + window.location.search);
    }
    return { role, token };
  });
  return { tokens: state, linkRole: fromLink.role, linkToken: fromLink.token };
}

function ContractPage() {
  const { id } = Route.useParams();
  const { mx, lang } = useMx();
  const { tokens, linkRole, linkToken } = useSignLinkContext();
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
  const pendingRoles = c.required_roles.filter((r) => st.roles[r] !== "valida");

  return (
    <div className="space-y-8" data-print-root>
      <nav aria-label={mx.common.breadcrumbLabel} className="text-sm text-muted-foreground print:hidden">
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
        <p className="hidden text-sm print:block">
          {mx.contract.hashLabel}: <span className="font-mono break-all">{st.sha256_current}</span>
        </p>
      </header>

      {(st.overall === "invalidado" || st.text_changed) && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <p className="flex items-center gap-2 font-semibold text-destructive"><AlertTriangle className="h-5 w-5" aria-hidden />{mx.contract.changedTitle}</p>
          <p className="mt-1 text-sm text-muted-foreground">{mx.contract.changedBody}</p>
          <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
            <div><dt className="inline font-medium">{mx.contract.signedHash}: </dt><dd className="inline font-mono break-all">{st.sha256_at_creation}</dd></div>
            <div><dt className="inline font-medium">{mx.contract.currentHash}: </dt><dd className="inline font-mono break-all">{st.sha256_current}</dd></div>
          </dl>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="order-2 space-y-6 lg:order-1">
          {/* Clauses */}
          <section className="space-y-4">
            <h2 className="text-xl font-bold text-primary">{mx.contract.clausesTitle}</h2>
            {c.clauses.map((cl) => (
              <article key={cl.n} className="rounded-lg border border-border bg-card p-4 print:break-inside-avoid">
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
                <div key={b.id} className="rounded-lg border border-border bg-card p-4 print:break-inside-avoid">
                  <p className="font-mono text-xs text-muted-foreground">[{b.id}] {b.citation}</p>
                  <blockquote lang="es" className="mt-1 border-l-4 border-primary/40 pl-3 font-serif text-foreground">“{b.quote}”</blockquote>
                  {/* The URL is printed as text so it survives on paper/PDF. */}
                  <p className="mt-1 break-all text-xs text-muted-foreground">
                    {b.doc_title} · <span className="print:after:content-[attr(data-url)]" data-url={b.url}>
                      <a href={b.url} target="_blank" rel="noreferrer" className="text-primary hover:underline print:hidden">{b.url}</a>
                    </span>
                  </p>
                </div>
              ))}
            </section>
          )}

          {/* Signature scope + verified legal basis */}
          <SignatureScope cveEnt={c.cve_ent} />

          {/* Signatures (print): render drawn/typed signatures */}
          {c.signatures.length > 0 && (
            <section className="hidden space-y-3 print:block">
              <h2 className="text-xl font-bold">{mx.contract.partiesTitle}</h2>
              {c.signatures.map((s) => (
                <div key={s.role + s.signed_at} className="break-inside-avoid border-b border-border py-2">
                  <p className="font-medium">{mx.contract.role[s.role]}: {s.full_name}</p>
                  {s.signature_png_base64 ? (
                    <img src={`data:image/png;base64,${s.signature_png_base64}`} alt="" className="mt-1 max-h-24" />
                  ) : s.typed_signature ? (
                    <p className="font-serif text-2xl italic">{s.typed_signature}</p>
                  ) : null}
                  <p className="text-xs text-muted-foreground">{mx.contract.sigSigned(formatDate(s.signed_at, lang))}</p>
                </div>
              ))}
            </section>
          )}

          {/* Sign form */}
          {pendingRoles.length > 0 && st.overall !== "invalidado" && (
            <div className="print:hidden">
              <SignSection
                contract={c}
                pendingRoles={pendingRoles}
                defaultRole={linkRole && pendingRoles.includes(linkRole) ? linkRole : pendingRoles[0]}
                tokens={tokens}
                linkToken={linkToken}
                linkRole={linkRole}
                onSigned={() => q.refetch()}
              />
            </div>
          )}
          {st.overall === "firmado" && (
            <section className="rounded-xl border border-applies/30 bg-applies-soft/40 p-5 print:hidden">
              <h2 className="flex items-center gap-2 font-semibold text-foreground"><Check className="h-5 w-5 text-applies" aria-hidden />{mx.contract.allSignedTitle}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{mx.contract.allSignedBody}</p>
            </section>
          )}
        </div>

        {/* Status panel */}
        <aside className="order-1 space-y-4 lg:order-2 lg:sticky lg:top-6 lg:self-start print:hidden">
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

          <SignLinksPanel contract={c} tokens={tokens} />

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold">{mx.contract.shareTitle}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{mx.contract.printHint}</p>
            <Button variant="outline" className="mt-2 w-full" onClick={() => window.print()}>
              <Printer className="h-4 w-4" aria-hidden /> {mx.contract.print}
            </Button>
            <EvidenceDownload contractId={c.contract_id} disabled={c.signatures.length === 0} />
          </div>
        </aside>
      </div>
      <Disclaimer />
    </div>
  );
}

/** Per-role signing links (token in the fragment). Shown only when we hold the one-time tokens. */
function SignLinksPanel({ contract, tokens }: { contract: MxContract; tokens: Partial<Record<MxRole, string>> }) {
  const { mx } = useMx();
  const [copied, setCopied] = useState<MxRole | null>(null);
  const roles = contract.required_roles.filter((r) => tokens[r]);
  if (roles.length === 0) return null;

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const copy = async (role: MxRole) => {
    try {
      await navigator.clipboard?.writeText(buildSignLink(origin, contract.contract_id, role, tokens[role]!));
      setCopied(role);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
      <h2 className="flex items-center gap-1.5 font-semibold"><Link2 className="h-4 w-4 text-primary" aria-hidden />{mx.contract.signLinksTitle}</h2>
      <p className="mt-1 text-xs text-muted-foreground">{mx.contract.signLinksBody}</p>
      <ul className="mt-3 space-y-2">
        {roles.map((r) => (
          <li key={r} className="flex items-center justify-between gap-2 text-sm">
            <span className="font-medium">{mx.contract.role[r]}</span>
            <Button variant="outline" size="sm" onClick={() => copy(r)} aria-label={mx.contract.signLinkFor(mx.contract.role[r])}>
              {copied === r ? <><Check className="h-3.5 w-3.5 text-applies" aria-hidden /> {mx.contract.signLinkCopied}</> : <>{mx.contract.copySignLink}</>}
            </Button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">{mx.contract.tokenShownOnce}</p>
      <p className="mt-1 text-xs font-medium text-muted-foreground">{mx.contract.noEmailsNotice}</p>
    </div>
  );
}

/** Honest signature-scope box, with the verified firma_electronica requirements (or a note if none). */
function SignatureScope({ cveEnt }: { cveEnt: string }) {
  const { mx, lang } = useMx();
  const q = useQuery({
    queryKey: ["mx-requirements", cveEnt, lang],
    queryFn: () => apiGet<MxRequirements>(`/mx/requirements?cve_ent=${cveEnt}&lang=${lang}`),
    staleTime: 5 * 60_000,
  });
  const items: MxRequirementItem[] = q.data?.categories?.firma_electronica ?? [];
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-5 print:break-inside-avoid">
      <h2 className="font-semibold">{mx.sign.scopeTitle}</h2>
      <p className="text-sm text-muted-foreground">{mx.sign.scopeBody}</p>
      <p className="text-sm text-muted-foreground">{mx.sign.scopeNotIncluded}</p>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{mx.sign.scopeSourcesTitle}</h3>
        {items.length > 0 ? (
          <ul className="space-y-2">
            {items.map((it) => (
              <li key={it.id} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium">{it.title}</p>
                <blockquote lang="es" className="mt-1 border-l-4 border-primary/40 pl-3 text-sm italic text-muted-foreground">“{it.quote}”</blockquote>
                <p className="mt-1 text-xs text-muted-foreground">{it.citation}</p>
                <div className="mt-2 print:hidden"><FundamentoButton item={it} /></div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{mx.sign.scopeNoSource}</p>
        )}
      </div>
    </section>
  );
}

/** Download the self-contained signature evidence record as JSON. */
function EvidenceDownload({ contractId, disabled }: { contractId: string; disabled: boolean }) {
  const { mx, lang } = useMx();
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const ev = await apiGet<MxEvidence>(`/mx/contracts/${contractId}/evidence?lang=${lang}`);
      const blob = new Blob([JSON.stringify(ev, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `constancia-${contractId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      /* a toast would need extra wiring; the button simply re-enables */
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="ghost" className="mt-1 w-full" onClick={download} disabled={disabled || busy}>
        <Download className="h-4 w-4" aria-hidden /> {mx.contract.downloadEvidence}
      </Button>
      <p className="mt-1 text-xs text-muted-foreground">{mx.contract.downloadEvidenceHint}</p>
    </>
  );
}

function SignSection({ contract, pendingRoles, defaultRole, tokens, linkToken, linkRole, onSigned }: {
  contract: MxContract;
  pendingRoles: MxRole[];
  defaultRole: MxRole;
  tokens: Partial<Record<MxRole, string>>;
  linkToken: string | null;
  linkRole: MxRole | null;
  onSigned: () => void;
}) {
  const { mx } = useMx();
  const [role, setRole] = useState<MxRole>(defaultRole);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [signature, setSignature] = useState<SignatureValue>(null);
  const [manualToken, setManualToken] = useState("");
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const sha = contract.status.sha256_current;

  // The effective token for this role: the per-role link token (if it matches), the full map from
  // the contract-form, or a token the user pasted.
  const effectiveToken =
    (linkRole === role && linkToken ? linkToken : null) ?? tokens[role] ?? manualToken.trim();
  const haveToken = Boolean((linkRole === role && linkToken) || tokens[role]);

  function validate(): string | null {
    if (!signature) return mx.sign.errEmptySignature;
    if (!consent) return mx.sign.errConsent;
    return null;
  }

  function requestSign(ev: FormEvent) {
    ev.preventDefault();
    const problem = validate();
    setError(problem);
    if (problem) return;
    setConfirmOpen(true);
  }

  async function doSign() {
    setConfirmOpen(false);
    setError(null);
    const body: MxSignRequest =
      signature!.kind === "trazo"
        ? {
            role, full_name: fullName.trim(), email: email.trim(),
            signature_png_base64: signature!.png, typed_signature: null, method: "trazo",
            consent: true, contract_sha256: sha, token: effectiveToken,
          }
        : {
            role, full_name: fullName.trim(), email: email.trim(),
            signature_png_base64: null, typed_signature: signature!.typed, method: "tecleada",
            consent: true, contract_sha256: sha, token: effectiveToken,
          };
    setSubmitting(true);
    try {
      await apiPost<MxSignResponse>(`/mx/contracts/${contract.contract_id}/sign`, body);
      onSigned();
      setFullName(""); setEmail(""); setSignature(null); setConsent(false); setManualToken("");
    } catch (err) {
      const { kind, message } = classifySignError(err);
      setError(
        kind === "token" ? mx.sign.errToken
          : kind === "hash_changed" ? mx.sign.errHashChanged
          : kind === "already_signed" ? mx.sign.errConflict(mx.contract.role[role])
          : kind === "name_mismatch" ? (message ?? mx.sign.nameMismatch(contract.parties[role]?.full_name ?? ""))
          : kind === "consent" ? mx.sign.errConsent
          : kind === "png" ? (message ?? mx.sign.errTooLarge)
          : kind === "validation" ? (message ?? mx.sign.errValidation)
          : mx.sign.errSubmit,
      );
    } finally {
      setSubmitting(false);
    }
  }

  const cls = "rounded-md border border-input bg-background px-3 py-2";
  return (
    <form onSubmit={requestSign} className="space-y-4 rounded-xl border border-primary/20 bg-primary/5 p-5">
      <h2 className="font-serif text-xl font-bold text-primary">{mx.sign.title}</h2>
      <p className="text-sm text-muted-foreground">{mx.sign.readFirst}</p>

      {error && <MxError message={error} />}

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{mx.sign.roleLegend}</legend>
        <div className="flex flex-wrap gap-2">
          {contract.required_roles.map((r) => {
            const already = contract.status.roles[r] === "valida";
            return (
              <label key={r} className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${already ? "opacity-50" : "cursor-pointer"} ${role === r ? "border-primary bg-primary/10" : "border-input"}`}>
                <input type="radio" name="role" value={r} checked={role === r} disabled={already} onChange={() => { setRole(r); setError(null); }} className="h-4 w-4" />
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

      {!haveToken && (
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Token</span>
          <input className={cls} value={manualToken} onChange={(e) => setManualToken(e.target.value)} />
          <span className="text-xs text-muted-foreground">{mx.contract.signLinksBody}</span>
        </label>
      )}

      {/* Signature capture: draw or type. */}
      <SignaturePad onChange={(v) => { setSignature(v); setError(null); }} disabled={submitting} />

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4" />
        {mx.sign.consent(shortHash(sha))}
      </label>

      <Button type="submit" disabled={submitting}>{submitting ? mx.sign.signing : mx.sign.submit}</Button>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{mx.sign.confirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>{mx.sign.confirmBody(mx.contract.role[role], shortHash(sha))}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            {/* Initial focus on the safe "review again" action. */}
            <AlertDialogCancel ref={cancelRef} autoFocus>{mx.sign.confirmNo}</AlertDialogCancel>
            <AlertDialogAction onClick={doSign}>{mx.sign.confirmYes}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  );
}
