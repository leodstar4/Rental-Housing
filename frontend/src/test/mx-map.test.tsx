import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { I18nProvider } from "@/lib/i18n";

// jsdom has no WebGL; MxMap only builds the map (and requests markers) when a WebGL context is
// available. Stub getContext so hasWebGL() is true for these tests.
beforeAll(() => {
  (HTMLCanvasElement.prototype as unknown as { getContext: () => unknown }).getContext = () => ({});
  if (!("WebGLRenderingContext" in window)) {
    (window as unknown as { WebGLRenderingContext: unknown }).WebGLRenderingContext = function () {};
  }
});

// --------------------------------------------------------------------------- //
// Mock @tanstack/react-router's Link so MxMap renders without a router context.
// --------------------------------------------------------------------------- //
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to, params, ...rest }: { children: React.ReactNode; to?: string; params?: unknown }) => {
    void to;
    void params;
    return <a {...(rest as Record<string, unknown>)}>{children}</a>;
  },
  createFileRoute: () => (opts: unknown) => opts,
}));

// Record every maplibre Marker construction so we can count the markers requested.
const markerCalls: Array<[number, number]> = [];

vi.mock("maplibre-gl", () => {
  class Marker {
    el: unknown;
    constructor(opts?: { element?: unknown }) {
      this.el = opts?.element;
    }
    setLngLat(coords: [number, number]) {
      markerCalls.push(coords);
      return this;
    }
    addTo() {
      return this;
    }
    remove() {}
  }
  class LngLatBounds {
    extend() {
      return this;
    }
  }
  class NavigationControl {}
  class MxMapMock {
    on(event: string, cb: () => void) {
      if (event === "load") cb();
      return this;
    }
    addControl() {
      return this;
    }
    fitBounds() {}
    easeTo() {}
    jumpTo() {}
    remove() {}
  }
  return { default: { Map: MxMapMock, Marker, LngLatBounds, NavigationControl } };
});

// maplibre's CSS import is a side-effect only.
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));

import { MxMap, isMappable, type MxMapZone } from "@/components/mx/MxMap";
import { fold } from "@/routes/mapa";

function wrap(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

const withCoord: MxMapZone = {
  cve_ent: "09",
  cve_mun: "015",
  name: "Cuauhtémoc",
  lat: 19.44,
  lon: -99.14,
  has_coords: true,
  coord: { represents: "cabecera_municipal", source: "INEGI Marco Geoestadístico 2020" },
  listings_count: 2,
};

const withoutCoord: MxMapZone = {
  cve_ent: "09",
  cve_mun: "099",
  name: "Zona sin coordenada",
  has_coords: false,
  coord: null,
  listings_count: 0,
};

afterEach(() => {
  markerCalls.length = 0;
  cleanup();
});

describe("isMappable (regla cero)", () => {
  it("requires has_coords, lat/lon and a coord source", () => {
    expect(isMappable(withCoord)).toBe(true);
    expect(isMappable(withoutCoord)).toBe(false);
    expect(isMappable({ ...withCoord, coord: { represents: "x", source: "" } })).toBe(false);
    expect(isMappable({ ...withCoord, lat: undefined })).toBe(false);
  });
});

describe("MxMap", () => {
  it("requests exactly one marker and lists the coordinate-less zone apart", async () => {
    wrap(<MxMap zones={[withCoord, withoutCoord]} stateName="Ciudad de México" />);

    // The map build runs in an effect; the mocked Map fires "load" synchronously but the dynamic
    // import resolves on a microtask — wait for the marker to be requested.
    await vi.waitFor(() => expect(markerCalls).toHaveLength(1));
    expect(markerCalls[0]).toEqual([-99.14, 19.44]);

    // The zone without an official coordinate appears under the "sin coordenada" heading.
    const withoutSection = screen.getByRole("heading", { name: /Sin coordenada oficial/i }).closest("div")!;
    expect(within(withoutSection).getByText("Zona sin coordenada")).toBeInTheDocument();

    // The mappable zone shows what the coordinate represents and its source.
    expect(screen.getByText(/cabecera municipal/i)).toBeInTheDocument();
    expect(screen.getByText(/INEGI Marco Geoestadístico 2020/)).toBeInTheDocument();
  });
});

describe("fold (accent/case-insensitive search)", () => {
  it("matches 'cuauhtemoc' against 'Cuauhtémoc'", () => {
    expect(fold("Cuauhtémoc").includes(fold("cuauhtemoc"))).toBe(true);
    expect(fold("Álvaro Obregón").includes(fold("alvaro"))).toBe(true);
    expect(fold("Tláhuac").includes(fold("xyz"))).toBe(false);
  });
});
