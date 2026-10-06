import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider } from "@/lib/i18n";
import { getMxCopy } from "@/lib/mx-i18n";
import { ApiError } from "@/lib/api";
import {
  base64ByteLength,
  buildSignLink,
  classifySignError,
  readSignLinkParams,
} from "@/lib/mx-sign";

// SignaturePad only needs the I18nProvider; no router. The canvas 2d context is stubbed because
// jsdom's canvas is a no-op (getContext returns null by default), and so is toDataURL.
beforeStubCanvas();
function beforeStubCanvas() {
  const proto = HTMLCanvasElement.prototype as unknown as {
    getContext: () => unknown;
    toDataURL: () => string;
  };
  proto.getContext = () => ({
    clearRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    strokeStyle: "",
    lineWidth: 0,
    lineJoin: "",
    lineCap: "",
  });
  proto.toDataURL = () => "data:image/png;base64,iVBORw0KGgo=";
}

import { SignaturePad } from "@/components/mx/SignaturePad";

function wrap(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

afterEach(cleanup);

// --------------------------------------------------------------------------- //
// 1. Token in the fragment: read once, then strip from the address bar.
// --------------------------------------------------------------------------- //
describe("readSignLinkParams (token in the #fragment)", () => {
  it("reads role from ?rol= and token from #t=", () => {
    const r = readSignLinkParams("?rol=arrendatario", "#t=abc123");
    expect(r.role).toBe("arrendatario");
    expect(r.token).toBe("abc123");
    expect(r.hadFragmentToken).toBe(true);
  });

  it("ignores an invalid role and reports no token when the fragment is empty", () => {
    const r = readSignLinkParams("?rol=nope", "");
    expect(r.role).toBeNull();
    expect(r.token).toBeNull();
    expect(r.hadFragmentToken).toBe(false);
  });

  it("never reads the token from the query string", () => {
    const r = readSignLinkParams("?rol=fiador&t=leaked", "");
    expect(r.token).toBeNull();
  });

  it("round-trips through buildSignLink and keeps the token out of search", () => {
    const link = buildSignLink("https://x.app", "deadbeef", "arrendador", "tok EN/+=");
    const url = new URL(link);
    expect(url.search).toBe("?rol=arrendador");
    expect(url.searchParams.get("t")).toBeNull(); // token is only in the fragment
    const parsed = readSignLinkParams(url.search, url.hash);
    expect(parsed.role).toBe("arrendador");
    expect(parsed.token).toBe("tok EN/+=");
  });
});

/** Mirror of the fragment-stripping the page does after reading the one-time token. */
function stripFragmentAfterRead(search: string, hash: string): { stripped: string; token: string | null } {
  const { token, hadFragmentToken } = readSignLinkParams(search, hash);
  const stripped = hadFragmentToken ? `/contrato/x${search}` : `/contrato/x${search}${hash}`;
  return { stripped, token };
}

describe("fragment cleanup", () => {
  it("drops the #t= fragment from the visible URL but keeps the token in memory", () => {
    const { stripped, token } = stripFragmentAfterRead("?rol=arrendador", "#t=secret");
    expect(token).toBe("secret");
    expect(stripped).toBe("/contrato/x?rol=arrendador");
    expect(stripped).not.toContain("secret");
  });
});

// --------------------------------------------------------------------------- //
// 2. SignaturePad: cannot be submitted without consent — here we assert the pad
//    reports null until there is ink/text, so the parent keeps the submit guard.
// --------------------------------------------------------------------------- //
describe("SignaturePad", () => {
  it("reports null with no signature and a typed value once the user types", async () => {
    const onChange = vi.fn();
    wrap(<SignaturePad onChange={onChange} />);

    // Starts empty: no value emitted yet, or emitted as null.
    expect(onChange.mock.calls.every(([v]) => v === null)).toBe(true);

    // Switch to the typed tab (accessible radio) and type a name.
    const copy = getMxCopy("es");
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(copy.sign.methodType) }));
    onChange.mockClear();
    const input = screen.getByPlaceholderText(copy.sign.typedLabel);
    fireEvent.change(input, { target: { value: "Ana" } });
    expect(onChange.mock.calls.at(-1)?.[0]).toEqual({ kind: "tecleada", typed: "Ana" });

    // Clearing the text drops the value back to null (submit guard would block).
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange.mock.calls.at(-1)?.[0]).toBeNull();
  });
});

describe("base64ByteLength", () => {
  it("estimates decoded size and handles padding/data-url prefixes", () => {
    expect(base64ByteLength("iVBORw0KGgo=")).toBe(8);
    expect(base64ByteLength("data:image/png;base64,iVBORw0KGgo=")).toBe(8);
  });
});

// --------------------------------------------------------------------------- //
// 3. Error mapping: 409 → clear message kinds; 403/422 too.
// --------------------------------------------------------------------------- //
describe("classifySignError", () => {
  it("maps 409 already_signed and hash_changed to distinct kinds", () => {
    const already = new ApiError(409, { code: "already_signed", msg: "el rol arrendador ya firmó" });
    expect(classifySignError(already).kind).toBe("already_signed");

    const changed = new ApiError(409, { code: "hash_changed", msg: "el contrato cambió" });
    expect(classifySignError(changed).kind).toBe("hash_changed");
  });

  it("maps 403 to a token error", () => {
    expect(classifySignError(new ApiError(403, "token de firma inválido para ese rol")).kind).toBe("token");
  });

  it("maps 422 field errors (name, consent, png) to specific kinds", () => {
    const name = new ApiError(422, [{ loc: ["body", "full_name"], msg: "no coincide", type: "value_error" }]);
    expect(classifySignError(name).kind).toBe("name_mismatch");

    const png = new ApiError(422, [{ loc: ["body", "signature_png_base64"], msg: "muy grande", type: "value_error" }]);
    expect(classifySignError(png).kind).toBe("png");
  });

  it("falls back to generic for anything else", () => {
    expect(classifySignError(new Error("boom")).kind).toBe("generic");
    expect(classifySignError(new ApiError(500, null)).kind).toBe("generic");
  });
});
