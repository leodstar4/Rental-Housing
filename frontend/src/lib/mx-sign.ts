/**
 * Renta MX — pure helpers for the signature flow (no DOM-heavy logic here, so they are easy to
 * unit-test offline).
 *
 * Regla cero / firma simple:
 * - The per-role signing link carries the one-time token in the URL *fragment* (`#t=…`), never in
 *   the query string and never logged. `readSignLinkParams` reads it, returns it in memory and the
 *   caller then strips the fragment with history.replaceState so it does not linger in the bar,
 *   history or the Referer header.
 * - PNG limits mirror mx/signatures.py (validate_png): ≤ 150 KB, ≤ 1200×600 px, real PNG header.
 *   We check them client-side before sending so the user gets an instant message; the server
 *   re-validates authoritatively.
 */
import type { ApiError, MxRole } from "./api";
import { conflictCode, fieldErrors } from "./api";

export const MX_SIGN_ROLES = ["arrendador", "arrendatario", "fiador"] as const;

/** PNG limits — must match mx/signatures.py (validate_png). */
export const PNG_MAX_BYTES = 150 * 1024;
export const PNG_MAX_W = 1200;
export const PNG_MAX_H = 600;
/** The backend caps signature_png_base64 at 200 000 chars (SignRequest). */
export const PNG_B64_MAX_CHARS = 200_000;

function isRole(v: unknown): v is MxRole {
  return typeof v === "string" && (MX_SIGN_ROLES as readonly string[]).includes(v);
}

export interface SignLinkParams {
  /** Role preselected from `?rol=`, if valid. */
  role: MxRole | null;
  /** One-time token read from the `#t=` fragment, if present. */
  token: string | null;
  /** True when the fragment carried a token and should be stripped from the address bar. */
  hadFragmentToken: boolean;
}

/**
 * Parse a signing link `/contrato/{id}?rol=<rol>#t=<token>`.
 * `search` is `location.search` (e.g. "?rol=arrendador"), `hash` is `location.hash` ("#t=abc").
 * Pure: does not touch history — the caller strips the fragment after reading.
 */
export function readSignLinkParams(search: string, hash: string): SignLinkParams {
  let role: MxRole | null = null;
  try {
    const rol = new URLSearchParams(search.replace(/^\?/, "")).get("rol");
    if (isRole(rol)) role = rol;
  } catch {
    /* malformed search */
  }
  let token: string | null = null;
  const frag = hash.replace(/^#/, "");
  try {
    const t = new URLSearchParams(frag).get("t");
    if (t && t.trim()) token = t.trim();
  } catch {
    /* malformed fragment */
  }
  return { role, token, hadFragmentToken: token !== null };
}

/** Build the per-role signing link (token in the fragment). Base is an absolute URL (window.origin). */
export function buildSignLink(origin: string, contractId: string, role: MxRole, token: string): string {
  return `${origin}/contrato/${contractId}?rol=${encodeURIComponent(role)}#t=${encodeURIComponent(token)}`;
}

/** Approximate decoded byte length of a base64 string (without allocating the bytes). */
export function base64ByteLength(b64: string): number {
  const data = b64.includes(",") ? b64.slice(b64.indexOf(",") + 1) : b64;
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((data.length * 3) / 4) - padding);
}

export type SignErrorKind =
  | "token"
  | "hash_changed"
  | "already_signed"
  | "name_mismatch"
  | "consent"
  | "png"
  | "validation"
  | "generic";

/**
 * Classify a failed POST /sign so the UI can show a clear, specific message:
 * 403 → bad token · 409 hash_changed → contract changed · 409 already_signed → role already signed ·
 * 422 → name/consent/png/validation. Returns the kind and the server message when useful.
 */
export function classifySignError(err: unknown): { kind: SignErrorKind; message?: string } {
  const e = err as ApiError | undefined;
  if (e && typeof e === "object" && "status" in e) {
    if (e.status === 403) return { kind: "token" };
    if (e.status === 409) {
      const code = conflictCode(err);
      if (code === "hash_changed") return { kind: "hash_changed" };
      if (code === "already_signed") return { kind: "already_signed" };
      return { kind: "generic" };
    }
    if (e.status === 422) {
      const fe = fieldErrors(err);
      const first = fe[0];
      if (first) {
        const field = first.loc.filter((p) => p !== "body").join(".");
        if (field === "full_name") return { kind: "name_mismatch", message: first.msg };
        if (field === "consent") return { kind: "consent", message: first.msg };
        if (field === "signature_png_base64") return { kind: "png", message: first.msg };
        return { kind: "validation", message: first.msg };
      }
      return { kind: "validation" };
    }
  }
  return { kind: "generic" };
}
