const DEFAULT_API_BASE = "https://rental-housing-navigator-api.onrender.com";
/** Configurable with VITE_API_BASE (e.g. http://localhost:8000); falls back to the deployed API. */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE).replace(/\/+$/, "") || DEFAULT_API_BASE;

export type Lang = "en" | "es";
export type ResultKind = "applies" | "unknown" | "superseded" | "not_yet_effective" | "pending";

export interface Address {
  address_id: string;
  street: string;
  postal_city: string;
  state: string;
  city: string;
}

export interface Rule {
  team_rule_id: string;
  title: string;
  category: string;
  level: "state" | "city";
  result: ResultKind;
  explanation: string;
  plain_language?: { status_line?: string; what_it_means?: string; who_it_covers?: string; what_you_can_do?: string };
  citation?: string;
  source_url?: string;
  retrieved_at?: string;
  quoted_span?: string;
  effective_date?: string | null;
  status?: string;
  confidence?: number;
  conflict_flag?: boolean;
  conflict_note?: string | null;
  needs_review?: boolean;
  missing_facts?: string[];
  missing_facts_label?: string[];
  presumptions?: string[];
  superseded_by?: string | null;
  attested?: boolean;
  audio_url?: string | null;
}

export interface Fact { value?: unknown; range?: [number, number | null]; certainty?: string; source?: string; basis?: string }

export interface Lookup {
  address: Address;
  building_facts: { units?: Fact; year_built?: Fact; [k: string]: unknown };
  jurisdiction_stack: { state: string; city: string; match_quality?: string; matched_address?: string; coordinates?: { lat: number; lon: number } };
  as_of: string;
  disclaimer: string;
  category_order: string[];
  results: Record<string, Rule[]>;
  counts: Record<string, number>;
}

type Listener = (waking: boolean) => void;
const listeners = new Set<Listener>();
let pending = 0;
export function onWaking(l: Listener) { listeners.add(l); return () => { listeners.delete(l); }; }
function setWaking(delta: number) {
  pending += delta;
  listeners.forEach((l) => l(pending > 0));
}

/** HTTP error with the parsed FastAPI `detail` (string, list of pydantic errors or object). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly retryAfter: number | null;
  /** 4xx other than 429: retrying the same request will not help. */
  readonly fatal: boolean;
  constructor(status: number, detail: unknown, retryAfter: number | null = null) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
    this.fatal = !(status >= 500 || status === 429);
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    const body = (await res.json()) as { detail?: unknown } | null;
    detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
  } catch {
    /* non-JSON body */
  }
  const ra = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, detail, Number.isFinite(ra) && ra > 0 ? ra : null);
}

/** GET with retries on network errors, 5xx and 429 (safe: GETs are idempotent). */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 4; attempt++) {
    let flagged = false;
    const slowTimer = setTimeout(() => { flagged = true; setWaking(1); }, 2500);
    try {
      const ctrl = new AbortController();
      const timeout = setTimeout(() => ctrl.abort(), 70000);
      signal?.addEventListener("abort", () => ctrl.abort());
      const res = await fetch(API_BASE + path, { signal: ctrl.signal });
      clearTimeout(timeout);
      if (!res.ok) throw await toApiError(res);
      return (await res.json()) as T;
    } catch (e) {
      lastErr = e;
      if (signal?.aborted || (e instanceof ApiError && e.fatal)) throw e;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    } finally {
      clearTimeout(slowTimer);
      if (flagged) setWaking(-1);
    }
  }
  throw lastErr;
}

/**
 * POST JSON **without automatic retries**: repeating a POST would duplicate a listing or hit the
 * 409 of a double signature. It first wakes the server with GET /mx/health (which may retry), then
 * sends exactly one request with a 70 s timeout. Callers keep the form data so the user can retry.
 */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  await apiGet<MxHealth>("/mx/health");
  let flagged = false;
  const slowTimer = setTimeout(() => { flagged = true; setWaking(1); }, 2500);
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 70000);
  try {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw await toApiError(res);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
    clearTimeout(slowTimer);
    if (flagged) setWaking(-1);
  }
}

/** Pydantic-style validation error item (422 `detail[]`). */
export interface ApiFieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
  requirement_ids?: string[];
  requirement_id?: string;
  citation?: string;
  quote?: string;
}

/** 422 errors as a list (FastAPI sends a list; a few checks send a plain string). */
export function fieldErrors(e: unknown): ApiFieldError[] {
  if (!(e instanceof ApiError) || e.status !== 422) return [];
  if (Array.isArray(e.detail)) return e.detail as ApiFieldError[];
  if (typeof e.detail === "string") return [{ loc: [], msg: e.detail, type: "value_error" }];
  return [];
}

/** Dotted body path of a 422 error, e.g. ["body","inmueble","cp"] -> "inmueble.cp". */
export function errorField(err: ApiFieldError): string {
  return err.loc.filter((p) => p !== "body").join(".");
}

/** Code inside a 409 detail object ({code, msg}). */
export function conflictCode(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail as { code?: unknown } | null;
  return d && typeof d === "object" && typeof d.code === "string" ? d.code : null;
}

// --------------------------------------------------------------------------- //
// Renta MX (/mx/*) response types — mirror api/mx.py and mx/*.py.
// --------------------------------------------------------------------------- //

export type MxCoverage = "estatal_verificada" | "solo_federal";
export type MxRole = "arrendador" | "arrendatario" | "fiador";
export type MxKind = "ley" | "reglamento" | "norma" | "practica";
export const MX_ROLES: readonly MxRole[] = ["arrendador", "arrendatario", "fiador"];

export interface MxHealth {
  status: "ok" | "degradado";
  store: "efimero" | "sqlite" | "postgres";
  store_started_at: string;
  store_notice: string;
  listings: number;
  contracts: number;
  data: {
    documents: number; documents_ok: number; requirements_verified: number; requirements_failed: number;
    zones_states: number; zones_error: string | null; clauses: number; clauses_error: string | null;
  };
  disclaimer: string;
}

/** A zone statistic. Present only when its source is in the manifests; `precision_baja` when INEGI CV >= 30. */
export interface MxStat {
  value: number;
  source: string;
  year: number;
  field?: string;
  estimator?: string;
  unit?: string;
  cv?: number;
  ci90?: [number, number];
  precision_baja?: boolean;
}

/**
 * Honest price summary from user-published listings (`basis: "viviendas_publicadas"`), never a
 * scraped or invented price. `min`/`median`/`max` appear only when `has_stats` is true (count >=
 * `min_count_for_stats`); otherwise `reason` says why there is no price yet.
 */
export interface MxPriceSummary {
  count: number;
  currency: "MXN";
  basis: "viviendas_publicadas";
  min_count_for_stats: number;
  as_of: string;
  has_stats: boolean;
  reason?: string;
  min?: number;
  median?: number;
  max?: number;
}

export interface MxStateRow {
  cve_ent: string;
  name: string;
  abbr: string | null;
  nom_abrev_inegi?: string;
  legal_coverage: MxCoverage;
  listings_count: number;
  municipios: number;
  stats?: Record<string, MxStat>;
  price_summary?: MxPriceSummary;
}

export interface MxStates { count: number; states: MxStateRow[]; disclaimer: string }

export interface MxCoord {
  represents: string; // "cabecera_municipal" | "localidad_mas_poblada"
  cve_loc?: string;
  nom_loc?: string;
  latitud_dms?: string;
  longitud_dms?: string;
  source: string;
  year?: number;
  cabecera_source?: string | null;
}

export interface MxZone {
  cve_ent: string;
  cve_mun: string;
  name: string;
  name_source?: string;
  stats: Record<string, MxStat>;
  has_stats: boolean;
  has_coords: boolean;
  lat?: number;
  lon?: number;
  coord?: MxCoord;
}

export interface MxZoneSearchItem extends MxZone { listings_count: number; empty_state: boolean; price_summary?: MxPriceSummary }

export interface MxZones {
  cve_ent: string; state: string; legal_coverage: MxCoverage; q: string | null; count: number;
  zones: MxZoneSearchItem[]; disclaimer: string;
}

export interface MxRequirementsSummary {
  legal_coverage: MxCoverage;
  notice: string | null;
  count: number;
  counts: { estatal: number; federal: number; practica: number };
  category_counts: Record<string, number>;
}

export interface MxListing {
  id: string;
  created_at: string;
  cve_ent: string;
  cve_mun: string;
  cp: string;
  colonia: string;
  title: string;
  description: string;
  monthly_rent_mxn: number;
  deposit_mxn: number | null;
  bedrooms: number;
  bathrooms: number;
  area_m2: number | null;
  furnished: boolean;
  pets_allowed: boolean | null;
  available_from: string;
  contact_name: string;
  published_by: "usuario";
  verified_owner: false;
}

export interface MxZoneDetail {
  state: MxStateRow;
  zone: MxZone;
  listings: MxListing[];
  listings_count: number;
  empty_state: boolean;
  price_summary?: MxPriceSummary;
  requirements_summary: MxRequirementsSummary;
  listing_notice: string;
  disclaimer: string;
}

export interface MxListings {
  count: number; total_unfiltered: number; empty_state: boolean; listings: MxListing[];
  listing_notice: string; disclaimer: string;
}

export interface MxListingDetail extends MxListing { listing_notice: string; disclaimer: string }

export interface MxRequirementItem {
  id: string;
  level: "federal" | "estatal";
  jurisdiction: string;
  category: string;
  kind: MxKind;
  is_law: boolean;
  title: string;
  summary: string;
  summary_caveat: string;
  citation: string;
  quote: string;
  quote_lang: string;
  match_type: string;
  applies_to_contract: boolean;
  checks: { field: string; op: string; value: string }[];
  reviewed_by: string | null;
  doc_id: string;
  doc_title: string;
  publisher: string;
  url: string;
  retrieved_at: string;
  last_reform: string | null;
}

export interface MxRequirements extends MxRequirementsSummary {
  cve_ent: string;
  state: string;
  abbr: string | null;
  lang: Lang;
  categories: Record<string, MxRequirementItem[]>;
  disclaimer: string;
}

export interface MxSourceDoc {
  doc_id: string;
  title?: string;
  publisher?: string;
  jurisdiction?: string;
  url?: string;
  retrieved_at?: string;
  sha256?: string;
  text_sha256?: string | null;
  text_sha256_in_manifest?: boolean;
  last_reform?: string | null;
  text_extractor?: string | null;
  file_path?: string;
  text_path?: string | null;
  file_in_repo?: boolean;
  verification: string; // ok | hash_mismatch | missing_file | invalid
  warnings?: string[];
  errors?: string[];
}

export interface MxSources {
  count: number;
  docs: MxSourceDoc[];
  verification: Record<string, string>;
  requirements: { verified: number; failed: number };
  states_without_state_source: { cve_ent: string; name: string; abbr: string | null }[];
  disclaimer: string;
}

export interface MxPrivacy {
  title: string;
  responsable: string;
  finalidades: string[];
  datos_recabados: string[];
  conservacion: string;
  transferencias: string;
  legal_basis: MxRequirementItem[];
  legal_basis_status: string;
  disclaimer: string;
}

export interface MxOmittedClause {
  key: string;
  title: { es: string; en: string };
  reason: string; // sin_requisito_verificado | entidad_solo_federal | sin_fiador | sin_deposito_pactado
}

export interface MxContractForm {
  cve_ent: string;
  state: string;
  legal_coverage: MxCoverage;
  notice: string | null;
  requires_acknowledgement: boolean;
  roles: Record<MxRole, "requerido" | "opcional">;
  required_fields: Record<string, string[]>;
  clauses: { key: string; title: string; basis: "ley" | "acuerdo_partes"; requirement_ids: string[] }[];
  omitted_clauses: MxOmittedClause[];
  disclaimer: string;
}

export interface MxClause {
  n: number;
  ordinal: string;
  key: string;
  title: string;
  title_en: string;
  basis: "ley" | "acuerdo_partes";
  text: string;
  requirement_ids: string[];
}

export type MxSigState = "valida" | "invalida";
export type MxOverall = "pendiente" | "parcial" | "firmado" | "invalidado";

export interface MxSignatureStatus {
  overall: MxOverall;
  roles: Partial<Record<MxRole, "valida" | "invalida" | "pendiente">>;
  per_signature: MxSigState[];
  chain_ok: boolean;
  valid_count: number;
  required_count: number;
  sha256_current: string;
  sha256_at_creation: string;
  text_changed: boolean;
}

export interface MxPublicSignature {
  role: MxRole;
  full_name: string;
  email_masked: string;
  signed_at: string;
  signature_kind: "trazo" | "tecleada";
  signature_sha256: string;
  contract_sha256: string;
  evidence_sha256: string;
  prev_evidence_sha256: string | null;
  user_agent_sha256: string;
  status: MxSigState;
  signature_png_base64: string | null;
  typed_signature: string | null;
}

export interface MxParty { full_name: string; email_masked: string; email_sha256: string }

export interface MxContract {
  contract_id: string;
  template_version: string;
  created_at: string;
  cve_ent: string;
  cve_mun: string;
  estado: string;
  municipio: string;
  listing_id: string | null;
  coverage: MxCoverage;
  notice: string | null;
  text: string;
  text_lang: string;
  sha256: string;
  sha256_at_creation: string;
  clauses: MxClause[];
  omitted_clauses: MxOmittedClause[];
  legal_basis: MxRequirementItem[];
  required_fields: Record<string, string[]>;
  required_roles: MxRole[];
  supersedes: string | null;
  parties: Partial<Record<MxRole, MxParty>>;
  signatures: MxPublicSignature[];
  status: MxSignatureStatus;
  store_notice: string;
  disclaimer: string;
}

export interface MxContractCreated extends MxContract {
  sign_tokens: Partial<Record<MxRole, string>>;
  sign_tokens_notice: string;
}

export interface MxEvidenceRecord {
  role: MxRole;
  full_name: string;
  email_sha256: string;
  email_masked: string;
  contract_id: string;
  contract_sha256: string;
  signature_sha256: string;
  signature_kind: "trazo" | "tecleada";
  signed_at: string;
  user_agent: string;
  ip_hash: string;
  consent: boolean;
  consent_text: string;
  consent_text_sha256: string;
  prev_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface MxSignResponse {
  status: MxSignatureStatus;
  signatures: MxPublicSignature[];
  evidence: MxEvidenceRecord;
}

export interface MxEvidence {
  title: string;
  contract_id: string;
  template_version: string;
  created_at: string;
  sha256_current: string;
  sha256_at_creation: string;
  text: string;
  status: MxSignatureStatus;
  signatures: MxPublicSignature[];
  verify_hint: string;
  notes: string[];
  generated_at: string;
  disclaimer: string;
}

// Request bodies (POST)
export interface MxListingCreate {
  cve_ent: string; cve_mun: string; cp: string; colonia: string; title: string; description: string;
  monthly_rent_mxn: number; deposit_mxn: number | null; bedrooms: number; bathrooms: number; area_m2: number | null;
  furnished: boolean; pets_allowed: boolean | null; available_from: string; contact_name: string; contact_email: string;
  truthfulness_consent: true; privacy_consent: true;
}

export interface MxPartyIn { full_name: string; email: string }

export interface MxContractCreate {
  listing_id: string | null;
  cve_ent: string;
  cve_mun: string;
  inmueble: { calle: string; num_ext: string; num_int: string | null; colonia: string; cp: string };
  arrendador: MxPartyIn;
  arrendatario: MxPartyIn;
  fiador: MxPartyIn | null;
  monthly_rent_mxn: number;
  deposit_mxn: number;
  start_date: string;
  term_months: number;
  payment_day: number;
  lang: Lang;
  acknowledge_solo_federal: boolean;
}

export interface MxSignRequest {
  role: MxRole;
  full_name: string;
  email: string;
  signature_png_base64: string | null;
  typed_signature: string | null;
  method: "trazo" | "tecleada";
  consent: true;
  contract_sha256: string;
  token: string;
}
