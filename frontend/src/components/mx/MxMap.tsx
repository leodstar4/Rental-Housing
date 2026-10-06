/**
 * MxMap — interactive OpenStreetMap view of Renta MX zones (docs/MX_UX.md, Fase 1).
 *
 * Rules enforced here (regla cero):
 * - A marker is painted ONLY when `has_coords === true` AND `coord?.source` exists; a zone without
 *   an official INEGI coordinate is never placed on the map — it is listed apart under
 *   "Sin coordenada oficial".
 * - The popup states what the coordinate represents (cabecera municipal / localidad más poblada)
 *   and its source. We never invent a point.
 * - Client-only: maplibre-gl (and its CSS) are imported dynamically inside an effect because
 *   TanStack Start renders on the server; maplibre needs `window`/WebGL.
 * - Accessibility: the map carries an aria-label and there is always a keyboard-navigable list of
 *   buttons synchronized with the markers (select in the list → highlight/center the marker and
 *   vice versa). If WebGL is unavailable, only the list is shown with a notice.
 * - Respects prefers-reduced-motion (no animated flyTo).
 */
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { MapPin, MapPinOff } from "lucide-react";

import { useMx } from "@/components/mx/MxShared";

/** Minimal shape MxMap needs; compatible with MxZoneSearchItem from @/lib/api. */
export interface MxMapCoord {
  represents?: string; // "cabecera_municipal" | "localidad_mas_poblada"
  source: string;
  cabecera_source?: string | null;
}
export interface MxMapZone {
  cve_ent: string;
  cve_mun: string;
  name: string;
  lat?: number;
  lon?: number;
  has_coords: boolean;
  coord?: MxMapCoord | null;
  listings_count: number;
  price_hint?: string;
}

/** A zone is mappable only with an official coordinate that has a source (regla cero). */
export function isMappable(z: MxMapZone): boolean {
  return z.has_coords === true && z.lat != null && z.lon != null && !!z.coord?.source;
}

export function zoneKey(z: { cve_ent: string; cve_mun: string }): string {
  return `${z.cve_ent}-${z.cve_mun}`;
}

function hasWebGL(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

interface MxMapProps {
  zones: MxMapZone[];
  selectedKey?: string | null;
  onSelect?: (z: MxMapZone) => void;
  /** Readable state name, for the aria-label. */
  stateName?: string;
}

/** Client-only maplibre map; renders the list fallback on the server and when WebGL is absent. */
export function MxMap({ zones, selectedKey, onSelect, stateName }: MxMapProps) {
  const { mx, lang } = useMx();
  const mapped = zones.filter(isMappable);
  const unmapped = zones.filter((z) => !isMappable(z));

  const [webgl, setWebgl] = useState(false);
  const [ready, setReady] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Keep live handles without re-rendering. `markers` maps zoneKey -> maplibre Marker.
  const mapRef = useRef<unknown>(null);
  const markersRef = useRef<Map<string, { el: HTMLButtonElement; marker: unknown }>>(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    setWebgl(hasWebGL());
  }, []);

  // Build the map once WebGL is confirmed and there is at least one mappable zone.
  useEffect(() => {
    if (!webgl || !containerRef.current || mapped.length === 0) return;
    let disposed = false;
    let cleanup: (() => void) | undefined;

    (async () => {
      const maplibregl = (await import("maplibre-gl")).default;
      await import("maplibre-gl/dist/maplibre-gl.css");
      if (disposed || !containerRef.current) return;

      const bounds = new maplibregl.LngLatBounds();
      for (const z of mapped) bounds.extend([z.lon as number, z.lat as number]);

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: {
          version: 8,
          sources: {
            osm: {
              type: "raster",
              tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
              tileSize: 256,
              maxzoom: 19,
              attribution: mx.map.attribution,
            },
          },
          layers: [{ id: "osm", type: "raster", source: "osm" }],
        },
        center: mapped.length === 1 ? [mapped[0].lon as number, mapped[0].lat as number] : [-99.13, 19.43],
        zoom: mapped.length === 1 ? 12 : 9,
        attributionControl: { compact: false },
        // Keep interactions but no inertia flourishes; respect reduced motion below.
      });
      mapRef.current = map;
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

      map.on("load", () => {
        if (disposed) return;
        if (mapped.length > 1) {
          map.fitBounds(bounds, { padding: 48, maxZoom: 13, animate: false });
        }
        setReady(true);
      });

      for (const z of mapped) {
        const el = document.createElement("button");
        el.type = "button";
        el.className =
          "flex h-6 w-6 items-center justify-center rounded-full border-2 border-background bg-primary text-primary-foreground shadow-md transition-transform hover:scale-110 focus:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring";
        el.innerHTML = '<span style="display:block;width:8px;height:8px;border-radius:9999px;background:currentColor"></span>';
        el.setAttribute("aria-label", z.name);
        el.title = z.name;
        el.addEventListener("click", () => onSelectRef.current?.(z));

        const marker = new maplibregl.Marker({ element: el }).setLngLat([z.lon as number, z.lat as number]).addTo(map);
        markersRef.current.set(zoneKey(z), { el, marker });
      }

      cleanup = () => {
        markersRef.current.forEach(({ marker }) => (marker as { remove: () => void }).remove());
        markersRef.current.clear();
        map.remove();
      };
    })().catch(() => {
      // If maplibre fails to load, fall back to the list (webgl stays false visually via `ready`).
      if (!disposed) setWebgl(false);
    });

    return () => {
      disposed = true;
      cleanup?.();
      mapRef.current = null;
      setReady(false);
    };
    // Rebuild only when the set of mappable zones changes (by key) or WebGL flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [webgl, mapped.map(zoneKey).join("|"), lang]);

  // Reflect the external selection on the map: highlight the marker and recenter (no animation
  // when the user prefers reduced motion).
  useEffect(() => {
    if (!ready || !selectedKey) return;
    const map = mapRef.current as { easeTo: (o: object) => void; jumpTo: (o: object) => void } | null;
    const hit = markersRef.current.get(selectedKey);
    markersRef.current.forEach(({ el }, key) => {
      el.setAttribute("data-selected", String(key === selectedKey));
      el.style.transform = key === selectedKey ? "scale(1.25)" : "";
    });
    if (map && hit) {
      const z = mapped.find((m) => zoneKey(m) === selectedKey);
      if (z) {
        const center = { center: [z.lon as number, z.lat as number] as [number, number], zoom: 12 };
        prefersReducedMotion() ? map.jumpTo(center) : map.easeTo({ ...center, duration: 600 });
      }
    }
  }, [selectedKey, ready, mapped]);

  const showMap = webgl && mapped.length > 0;

  return (
    <div className="space-y-4">
      {showMap ? (
        <div
          ref={containerRef}
          role="application"
          aria-label={mx.map.ariaLabel(stateName ?? "")}
          className="h-[420px] w-full overflow-hidden rounded-xl border border-border"
        />
      ) : (
        mapped.length > 0 && (
          <p role="status" className="rounded-lg border border-unknown/30 bg-unknown-soft/50 p-4 text-sm text-foreground">
            {mx.map.webglUnavailable}
          </p>
        )
      )}

      {/* Alternative, keyboard-navigable list synchronized with the markers. */}
      <nav aria-label={mx.map.listLabel} className="space-y-4">
        {mapped.length > 0 && (
          <div className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <MapPin className="h-4 w-4 text-primary" aria-hidden /> {mx.map.withCoords}
            </h3>
            <ul className="grid gap-2 sm:grid-cols-2">
              {mapped.map((z) => (
                <li key={zoneKey(z)}>
                  <ZoneButton
                    z={z}
                    selected={zoneKey(z) === selectedKey}
                    onSelect={onSelect}
                    representsLabel={representsLabel(z, mx)}
                    sourceLine={coordSourceLine(z, mx)}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}

        {unmapped.length > 0 && (
          <div className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
              <MapPinOff className="h-4 w-4" aria-hidden /> {mx.map.withoutCoordsTitle}
            </h3>
            <p className="text-xs text-muted-foreground">{mx.map.withoutCoordsHelp}</p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {unmapped.map((z) => (
                <li key={zoneKey(z)}>
                  <ZoneButton z={z} selected={false} onSelect={onSelect} muted />
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>
    </div>
  );
}

function representsLabel(z: MxMapZone, mx: ReturnType<typeof useMx>["mx"]): string | null {
  const r = z.coord?.represents;
  if (!r) return null;
  const map = mx.map.represents as Record<string, string>;
  return map[r] ?? mx.map.represents.other;
}

function coordSourceLine(z: MxMapZone, mx: ReturnType<typeof useMx>["mx"]): string | null {
  return z.coord?.source ? mx.map.coordSource(z.coord.source) : null;
}

function ZoneButton({
  z,
  selected,
  onSelect,
  muted,
  representsLabel,
  sourceLine,
}: {
  z: MxMapZone;
  selected: boolean;
  onSelect?: (z: MxMapZone) => void;
  muted?: boolean;
  representsLabel?: string | null;
  sourceLine?: string | null;
}) {
  const { mx } = useMx();
  return (
    <div
      className={`flex flex-col gap-1 rounded-lg border p-3 transition-colors ${
        selected ? "border-primary bg-primary/5" : muted ? "border-dashed border-border bg-muted/20" : "border-border bg-card"
      }`}
    >
      <button
        type="button"
        onClick={() => onSelect?.(z)}
        aria-pressed={selected}
        className="flex items-center justify-between gap-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="font-medium text-foreground">{z.name}</span>
        <span className="shrink-0 text-xs text-muted-foreground">{mx.map.listings(z.listings_count)}</span>
      </button>
      {z.price_hint && <p className="text-sm font-semibold text-primary">{z.price_hint}</p>}
      {representsLabel && <p className="text-xs text-muted-foreground">{representsLabel}</p>}
      {sourceLine && <p className="text-xs text-muted-foreground">{sourceLine}</p>}
      <Link
        to="/zona/$cveEnt/$cveMun"
        params={{ cveEnt: z.cve_ent, cveMun: z.cve_mun }}
        className="w-fit text-sm text-primary underline-offset-2 hover:underline"
      >
        {mx.map.viewZone} →
      </Link>
    </div>
  );
}
