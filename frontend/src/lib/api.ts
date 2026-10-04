export const API_BASE = "https://rental-housing-navigator-api.onrender.com";

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

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 4; attempt++) {
    let slowTimer: ReturnType<typeof setTimeout> | undefined;
    let flagged = false;
    slowTimer = setTimeout(() => { flagged = true; setWaking(1); }, 2500);
    try {
      const ctrl = new AbortController();
      const timeout = setTimeout(() => ctrl.abort(), 70000);
      signal?.addEventListener("abort", () => ctrl.abort());
      const res = await fetch(API_BASE + path, { signal: ctrl.signal });
      clearTimeout(timeout);
      if (!res.ok) {
        if (res.status >= 500 || res.status === 429) throw new Error(`HTTP ${res.status}`);
        const e = new Error(`HTTP ${res.status}`);
        (e as Error & { fatal?: boolean }).fatal = true;
        throw e;
      }
      return (await res.json()) as T;
    } catch (e) {
      lastErr = e;
      if (signal?.aborted || (e as { fatal?: boolean }).fatal) throw e;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    } finally {
      clearTimeout(slowTimer);
      if (flagged) setWaking(-1);
    }
  }
  throw lastErr;
}
