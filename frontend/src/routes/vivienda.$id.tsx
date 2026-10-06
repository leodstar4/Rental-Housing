import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  apiGet,
  apiPost,
  fieldErrors,
  errorField,
  type MxListingDetail,
  type MxContractCreate,
  type MxContractCreated,
} from "@/lib/api";
import { setDisclaimer } from "@/components/Shell";
import { CoverageBadge, Disclaimer, MxError, MxLoading, useMx } from "@/components/mx/MxShared";
import { formatMXN } from "@/lib/mx-i18n";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/vivienda/$id")({
  component: ListingPage,
});

function ListingPage() {
  const { id } = Route.useParams();
  const { mx, lang } = useMx();
  const [showForm, setShowForm] = useState(false);
  const q = useQuery({ queryKey: ["mx-listing", id, lang], queryFn: () => apiGet<MxListingDetail>(`/mx/listings/${id}?lang=${lang}`) });
  if (q.isLoading) return <MxLoading />;
  if (q.isError) return <MxError onRetry={() => q.refetch()} message={mx.listing.notFound} />;
  const l = q.data!;

  return (
    <div className="space-y-8">
      <Link to="/zona/$cveEnt/$cveMun" params={{ cveEnt: l.cve_ent, cveMun: l.cve_mun }} className="text-sm text-primary hover:underline">
        ← {mx.listing.backToZone(l.colonia)}
      </Link>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <article className="space-y-5">
          <header>
            <h1 className="font-serif text-3xl font-bold text-foreground">{l.title}</h1>
            <p className="mt-2 text-2xl font-bold text-primary">{mx.listingCard.perMonth(formatMXN(l.monthly_rent_mxn, lang))}</p>
          </header>
          <dl className="grid grid-cols-2 gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-3">
            <Def label={mx.publish.bedroomsLabel} value={String(l.bedrooms)} />
            <Def label={mx.publish.bathroomsLabel} value={String(l.bathrooms)} />
            {l.area_m2 && <Def label={mx.publish.areaLabel} value={`${l.area_m2} m²`} />}
            <Def label={mx.publish.furnishedLabel} value={l.furnished ? mx.listing.furnished : mx.listing.notFurnished} />
            <Def label={mx.publish.petsLabel} value={l.pets_allowed ? mx.listing.petsYes : mx.listing.petsNo} />
            {l.deposit_mxn != null && <Def label={mx.listing.requestedDeposit} value={formatMXN(l.deposit_mxn, lang)} />}
          </dl>
          {l.description && (
            <section>
              <h2 className="font-semibold">{mx.listing.description}</h2>
              <p className="mt-1 whitespace-pre-line text-foreground">{l.description}</p>
            </section>
          )}
          <section>
            <h2 className="font-semibold">{mx.listing.location}</h2>
            <p className="mt-1 text-foreground">{l.colonia} · C.P. {l.cp}</p>
            <p className="text-sm text-muted-foreground">{mx.listing.exactAddressHidden}</p>
          </section>
          <span className="inline-flex w-fit items-center rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">{mx.listingCard.userPublished}</span>
        </article>

        <aside className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold">{mx.listing.startContract}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{mx.listing.startContractHelp}</p>
            <Button className="mt-3 w-full" onClick={() => setShowForm((v) => !v)}>{mx.listing.startContract}</Button>
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold">{mx.listing.beforeRentingTitle(l.cve_ent)}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{mx.listing.beforeRentingBody}</p>
            <Button asChild variant="outline" className="mt-3 w-full"><Link to="/requisitos/$cveEnt" params={{ cveEnt: l.cve_ent }}>{mx.listing.beforeRentingCta}</Link></Button>
          </div>
        </aside>
      </div>

      {showForm && <ContractForm listing={l} />}
      <Disclaimer />
    </div>
  );
}

function Def({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function ContractForm({ listing }: { listing: MxListingDetail }) {
  const { mx } = useMx();
  const navigate = useNavigate();
  const [withFiador, setWithFiador] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [v, setV] = useState({
    arrendadorNombre: "", arrendadorEmail: "", arrendatarioNombre: "", arrendatarioEmail: "",
    fiadorNombre: "", fiadorEmail: "",
    calle: "", numExt: "", numInt: "", colonia: listing.colonia, cp: listing.cp,
    rent: String(listing.monthly_rent_mxn), deposit: listing.deposit_mxn != null ? String(listing.deposit_mxn) : "0",
    startDate: new Date().toISOString().slice(0, 10), term: "12", paymentDay: "1",
  });
  const s = <K extends keyof typeof v>(k: K, val: (typeof v)[K]) => setV((p) => ({ ...p, [k]: val }));

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    setErrors({});
    setSubmitError(null);
    const body: MxContractCreate = {
      listing_id: listing.id, cve_ent: listing.cve_ent, cve_mun: listing.cve_mun,
      inmueble: { calle: v.calle.trim(), num_ext: v.numExt.trim(), num_int: v.numInt.trim() || null, colonia: v.colonia.trim(), cp: v.cp },
      arrendador: { full_name: v.arrendadorNombre.trim(), email: v.arrendadorEmail.trim() },
      arrendatario: { full_name: v.arrendatarioNombre.trim(), email: v.arrendatarioEmail.trim() },
      fiador: withFiador ? { full_name: v.fiadorNombre.trim(), email: v.fiadorEmail.trim() } : null,
      monthly_rent_mxn: Number(v.rent), deposit_mxn: Number(v.deposit), start_date: v.startDate,
      term_months: Number(v.term), payment_day: Number(v.paymentDay), lang: "es", acknowledge_solo_federal: true,
    };
    setSubmitting(true);
    try {
      const res = await apiPost<MxContractCreated>("/mx/contracts", body);
      // Pass the one-time sign tokens to the contract page via history state.
      navigate({ to: "/contrato/$id", params: { id: res.contract_id }, state: { signTokens: res.sign_tokens } as never });
    } catch (err) {
      const fe = fieldErrors(err);
      if (fe.length) setErrors(Object.fromEntries(fe.map((x) => [errorField(x) || "form", x.msg])));
      else setSubmitError(mx.contractForm.errGenerate);
    } finally {
      setSubmitting(false);
    }
  }

  const err = (k: string) => errors[k] && <p className="mt-1 text-sm text-destructive">{errors[k]}</p>;
  const cls = "rounded-md border border-input bg-background px-3 py-2";

  return (
    <form onSubmit={onSubmit} className="space-y-6 rounded-xl border border-primary/20 bg-primary/5 p-5">
      <h2 className="font-serif text-2xl font-bold text-primary">{mx.contractForm.title}</h2>
      {submitError && <MxError message={submitError} />}
      {errors.form && <MxError message={errors.form} />}

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="font-semibold">{mx.contractForm.stepParties}</legend>
        <Field label={mx.contractForm.landlordSection + " · " + mx.contractForm.fullName}><input className={cls} value={v.arrendadorNombre} onChange={(e) => s("arrendadorNombre", e.target.value)} />{err("arrendador.full_name")}</Field>
        <Field label={mx.contractForm.email}><input type="email" className={cls} value={v.arrendadorEmail} onChange={(e) => s("arrendadorEmail", e.target.value)} />{err("arrendador.email")}</Field>
        <Field label={mx.contractForm.tenantSection + " · " + mx.contractForm.fullName}><input className={cls} value={v.arrendatarioNombre} onChange={(e) => s("arrendatarioNombre", e.target.value)} />{err("arrendatario.full_name")}</Field>
        <Field label={mx.contractForm.email}><input type="email" className={cls} value={v.arrendatarioEmail} onChange={(e) => s("arrendatarioEmail", e.target.value)} />{err("arrendatario.email")}</Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={withFiador} onChange={(e) => setWithFiador(e.target.checked)} className="h-4 w-4" />{mx.contractForm.includeGuarantor}</label>
        {withFiador && <>
          <Field label={mx.contractForm.guarantorSection + " · " + mx.contractForm.fullName}><input className={cls} value={v.fiadorNombre} onChange={(e) => s("fiadorNombre", e.target.value)} />{err("fiador.full_name")}</Field>
          <Field label={mx.contractForm.email}><input type="email" className={cls} value={v.fiadorEmail} onChange={(e) => s("fiadorEmail", e.target.value)} />{err("fiador.email")}</Field>
        </>}
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="font-semibold">{mx.contractForm.stepProperty}</legend>
        <Field label="Calle"><input className={cls} value={v.calle} onChange={(e) => s("calle", e.target.value)} />{err("inmueble.calle")}</Field>
        <Field label="Número exterior"><input className={cls} value={v.numExt} onChange={(e) => s("numExt", e.target.value)} />{err("inmueble.num_ext")}</Field>
        <Field label="Número interior (opcional)"><input className={cls} value={v.numInt} onChange={(e) => s("numInt", e.target.value)} /></Field>
        <Field label={mx.publish.coloniaLabel}><input className={cls} value={v.colonia} onChange={(e) => s("colonia", e.target.value)} />{err("inmueble.colonia")}</Field>
        <Field label={mx.contractForm.cp}><input inputMode="numeric" maxLength={5} className={cls} value={v.cp} onChange={(e) => s("cp", e.target.value.replace(/\D/g, ""))} />{err("inmueble.cp")}</Field>
        <Field label={mx.contractForm.monthlyRent}><input inputMode="decimal" className={cls} value={v.rent} onChange={(e) => s("rent", e.target.value.replace(/[^\d.]/g, ""))} />{err("monthly_rent_mxn")}</Field>
        <Field label={mx.contractForm.deposit}><input inputMode="decimal" className={cls} value={v.deposit} onChange={(e) => s("deposit", e.target.value.replace(/[^\d.]/g, ""))} />{err("deposit_mxn")}</Field>
        <Field label={mx.contractForm.startDate}><input type="date" className={cls} value={v.startDate} onChange={(e) => s("startDate", e.target.value)} />{err("start_date")}</Field>
        <Field label={mx.contractForm.termMonths}><input type="number" min={1} max={120} className={cls} value={v.term} onChange={(e) => s("term", e.target.value)} />{err("term_months")}</Field>
        <Field label={mx.contractForm.paymentDay}><input type="number" min={1} max={28} className={cls} value={v.paymentDay} onChange={(e) => s("paymentDay", e.target.value)} />{err("payment_day")}</Field>
      </fieldset>

      <p className="text-sm text-muted-foreground">{mx.contractForm.generatedHow}</p>
      <Button type="submit" disabled={submitting}>{submitting ? mx.contractForm.generating : mx.contractForm.generate}</Button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}
