import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  apiGet,
  apiPost,
  fieldErrors,
  errorField,
  type MxListingCreate,
  type MxListing,
  type MxStates,
  type MxZones,
} from "@/lib/api";
import { Disclaimer, MxError, useMx } from "@/components/mx/MxShared";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/publicar")({
  head: () => ({ meta: [{ title: "Publicar vivienda — Renta MX" }] }),
  validateSearch: (s: Record<string, unknown>): { cveEnt?: string; cveMun?: string } => ({
    cveEnt: typeof s.cveEnt === "string" ? s.cveEnt : undefined,
    cveMun: typeof s.cveMun === "string" ? s.cveMun : undefined,
  }),
  component: PublishPage,
});

type FormState = {
  cve_ent: string; cve_mun: string; cp: string; colonia: string; title: string; description: string;
  monthly_rent_mxn: string; deposit_mxn: string; bedrooms: string; bathrooms: string; area_m2: string;
  furnished: boolean; pets_allowed: boolean; available_from: string; contact_name: string; contact_email: string;
  truthfulness_consent: boolean; privacy_consent: boolean;
};

const EMAIL_RE = /^[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;

function PublishPage() {
  const { cveEnt, cveMun } = Route.useSearch();
  const { mx, lang } = useMx();
  const states = useQuery({ queryKey: ["mx-states", lang], queryFn: () => apiGet<MxStates>(`/mx/states?lang=${lang}`), staleTime: 5 * 60_000 });

  const [f, setF] = useState<FormState>({
    cve_ent: cveEnt ?? "", cve_mun: cveMun ?? "", cp: "", colonia: "", title: "", description: "",
    monthly_rent_mxn: "", deposit_mxn: "", bedrooms: "1", bathrooms: "1", area_m2: "",
    furnished: false, pets_allowed: false, available_from: new Date().toISOString().slice(0, 10),
    contact_name: "", contact_email: "", truthfulness_consent: false, privacy_consent: false,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [created, setCreated] = useState<MxListing | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const munis = useQuery({
    queryKey: ["mx-zone-all", f.cve_ent, lang],
    queryFn: () => apiGet<MxZones>(`/mx/zones?cve_ent=${f.cve_ent}&limit=600&lang=${lang}`),
    enabled: !!f.cve_ent,
  });

  function validate(): Record<string, string> {
    const e: Record<string, string> = {};
    if (!f.cve_ent) e.cve_ent = mx.publish.errRequired;
    if (!f.cve_mun) e.cve_mun = mx.publish.errMunicipio;
    if (!/^\d{5}$/.test(f.cp)) e.cp = mx.publish.errCp;
    if (!f.colonia.trim()) e.colonia = mx.publish.errRequired;
    if (!f.title.trim()) e.title = mx.publish.errRequired;
    if (!(Number(f.monthly_rent_mxn) > 0)) e.monthly_rent_mxn = mx.publish.errRentPositive;
    if (!f.contact_name.trim()) e.contact_name = mx.publish.errRequired;
    if (!EMAIL_RE.test(f.contact_email)) e.contact_email = mx.publish.errEmail;
    if (!f.truthfulness_consent || !f.privacy_consent) e.consent = mx.publish.errConsent;
    return e;
  }

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    setSubmitError(null);
    if (Object.keys(e).length) { document.getElementById("err-summary")?.focus(); return; }
    const body: MxListingCreate = {
      cve_ent: f.cve_ent, cve_mun: f.cve_mun, cp: f.cp, colonia: f.colonia.trim(), title: f.title.trim(),
      description: f.description.trim(), monthly_rent_mxn: Number(f.monthly_rent_mxn),
      deposit_mxn: f.deposit_mxn ? Number(f.deposit_mxn) : null, bedrooms: Number(f.bedrooms),
      bathrooms: Number(f.bathrooms), area_m2: f.area_m2 ? Number(f.area_m2) : null,
      furnished: f.furnished, pets_allowed: f.pets_allowed, available_from: f.available_from,
      contact_name: f.contact_name.trim(), contact_email: f.contact_email.trim(),
      truthfulness_consent: true, privacy_consent: true,
    };
    setSubmitting(true);
    try {
      const res = await apiPost<MxListing>("/mx/listings", body);
      setCreated(res);
    } catch (err) {
      const fe = fieldErrors(err);
      if (fe.length) setErrors(Object.fromEntries(fe.map((x) => [errorField(x) || "form", x.msg])));
      else setSubmitError(mx.publish.errSubmit);
    } finally {
      setSubmitting(false);
    }
  }

  if (created) {
    return (
      <div className="mx-auto max-w-xl space-y-5 rounded-xl border border-applies/30 bg-applies-soft/40 p-6 text-center">
        <h1 className="font-serif text-2xl font-bold text-foreground">{mx.publish.successTitle}</h1>
        <p className="text-muted-foreground">{mx.publish.successBody}</p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button asChild><Link to="/vivienda/$id" params={{ id: created.id }}>{mx.publish.viewListing}</Link></Button>
          <Button variant="outline" onClick={() => { setCreated(null); setErrors({}); }}>{mx.publish.publishAnother}</Button>
        </div>
      </div>
    );
  }

  const errCount = Object.keys(errors).length;
  const err = (k: string) => errors[k] && <p id={`e-${k}`} className="mt-1 text-sm text-destructive">{errors[k]}</p>;
  const inputCls = (k: string) => `rounded-md border px-3 py-2 ${errors[k] ? "border-destructive" : "border-input"} bg-background`;

  return (
    <form onSubmit={onSubmit} noValidate className="mx-auto max-w-2xl space-y-6">
      <header className="space-y-2">
        <h1 className="font-serif text-3xl font-bold text-primary">{mx.publish.title}</h1>
        <p className="text-muted-foreground">{mx.publish.intro}</p>
      </header>

      {errCount > 0 && (
        <div id="err-summary" tabIndex={-1} role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <p className="font-semibold text-destructive">{mx.publish.errorSummaryTitle(errCount)}</p>
        </div>
      )}
      {submitError && <MxError message={submitError} />}

      <fieldset className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
        <legend className="px-1 font-semibold">{mx.publish.sectionLocation}</legend>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.stateLabel}</span>
          <select value={f.cve_ent} onChange={(e) => { set("cve_ent", e.target.value); set("cve_mun", ""); }} aria-invalid={!!errors.cve_ent} className={inputCls("cve_ent")}>
            <option value="">—</option>
            {(states.data?.states ?? []).map((s) => <option key={s.cve_ent} value={s.cve_ent}>{s.name}</option>)}
          </select>
          {err("cve_ent")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.municipioLabel}</span>
          <select value={f.cve_mun} onChange={(e) => set("cve_mun", e.target.value)} disabled={!f.cve_ent} aria-invalid={!!errors.cve_mun} className={inputCls("cve_mun")}>
            <option value="">—</option>
            {(munis.data?.zones ?? []).map((m) => <option key={m.cve_mun} value={m.cve_mun}>{m.name}</option>)}
          </select>
          {err("cve_mun")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.coloniaLabel}</span>
          <input value={f.colonia} onChange={(e) => set("colonia", e.target.value)} aria-invalid={!!errors.colonia} className={inputCls("colonia")} />
          {err("colonia")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.cpLabel}</span>
          <input inputMode="numeric" maxLength={5} value={f.cp} onChange={(e) => set("cp", e.target.value.replace(/\D/g, ""))} aria-invalid={!!errors.cp} className={inputCls("cp")} />
          {err("cp")}
        </label>
        <p className="sm:col-span-2 text-xs text-muted-foreground">{mx.publish.addressPrivacy}</p>
      </fieldset>

      <fieldset className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
        <legend className="px-1 font-semibold">{mx.publish.sectionProperty}</legend>
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-sm font-medium">{mx.publish.titleLabel}</span>
          <input value={f.title} onChange={(e) => set("title", e.target.value)} aria-invalid={!!errors.title} className={inputCls("title")} />
          {err("title")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.bedroomsLabel}</span>
          <input type="number" min={0} max={20} value={f.bedrooms} onChange={(e) => set("bedrooms", e.target.value)} className={inputCls("bedrooms")} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.bathroomsLabel}</span>
          <input type="number" min={0} max={20} step={0.5} value={f.bathrooms} onChange={(e) => set("bathrooms", e.target.value)} className={inputCls("bathrooms")} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.areaLabel}</span>
          <input inputMode="decimal" value={f.area_m2} onChange={(e) => set("area_m2", e.target.value.replace(/[^\d.]/g, ""))} className={inputCls("area_m2")} />
        </label>
        <div className="flex items-end gap-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.furnished} onChange={(e) => set("furnished", e.target.checked)} className="h-4 w-4" />{mx.publish.furnishedLabel}</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.pets_allowed} onChange={(e) => set("pets_allowed", e.target.checked)} className="h-4 w-4" />{mx.publish.petsLabel}</label>
        </div>
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-sm font-medium">{mx.publish.descriptionLabel}</span>
          <textarea value={f.description} onChange={(e) => set("description", e.target.value)} rows={3} maxLength={2000} className={inputCls("description")} />
          <span className="text-xs text-muted-foreground">{mx.publish.descriptionHint}</span>
        </label>
      </fieldset>

      <fieldset className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
        <legend className="px-1 font-semibold">{mx.publish.sectionTerms}</legend>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.rentLabel}</span>
          <input inputMode="decimal" value={f.monthly_rent_mxn} onChange={(e) => set("monthly_rent_mxn", e.target.value.replace(/[^\d.]/g, ""))} aria-invalid={!!errors.monthly_rent_mxn} className={inputCls("monthly_rent_mxn")} />
          {err("monthly_rent_mxn")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.depositLabel}</span>
          <input inputMode="decimal" value={f.deposit_mxn} onChange={(e) => set("deposit_mxn", e.target.value.replace(/[^\d.]/g, ""))} className={inputCls("deposit_mxn")} />
          <span className="text-xs text-muted-foreground">{mx.publish.depositHint}</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.sectionTerms}</span>
          <input type="date" value={f.available_from} onChange={(e) => set("available_from", e.target.value)} className={inputCls("available_from")} />
        </label>
      </fieldset>

      <fieldset className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
        <legend className="px-1 font-semibold">{mx.publish.sectionContact}</legend>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.landlordNameLabel}</span>
          <input autoComplete="name" value={f.contact_name} onChange={(e) => set("contact_name", e.target.value)} aria-invalid={!!errors.contact_name} className={inputCls("contact_name")} />
          {err("contact_name")}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">{mx.publish.landlordEmailLabel}</span>
          <input type="email" autoComplete="email" value={f.contact_email} onChange={(e) => set("contact_email", e.target.value)} aria-invalid={!!errors.contact_email} className={inputCls("contact_email")} />
          <span className="text-xs text-muted-foreground">{mx.publish.emailPublicNote}</span>
          {err("contact_email")}
        </label>
      </fieldset>

      <div className="space-y-3 rounded-xl border border-border bg-card p-5">
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={f.truthfulness_consent} onChange={(e) => set("truthfulness_consent", e.target.checked)} className="mt-0.5 h-4 w-4" />{mx.publish.truthfulnessConsent}</label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={f.privacy_consent} onChange={(e) => set("privacy_consent", e.target.checked)} className="mt-0.5 h-4 w-4" />{mx.publish.privacyConsent}</label>
        {err("consent")}
        <p className="text-xs text-muted-foreground">{mx.common.demoStorage}</p>
      </div>

      <Disclaimer />
      <Button type="submit" disabled={submitting} className="w-full sm:w-auto">
        {submitting ? mx.publish.submitting : mx.publish.submit}
      </Button>
    </form>
  );
}
