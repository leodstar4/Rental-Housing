import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { I18nProvider } from "@/lib/i18n";
import type { MxPriceSummary, MxStat } from "@/lib/api";

// PriceBlock renders a shadcn Button with `asChild` -> @tanstack/react-router Link; mock the
// router so it renders without a router context (same approach as mx-map.test.tsx).
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to, params, ...rest }: { children: React.ReactNode; to?: string; params?: unknown }) => {
    void to;
    void params;
    return <a {...(rest as Record<string, unknown>)}>{children}</a>;
  },
  createFileRoute: () => (opts: unknown) => opts,
}));

import { PriceBlock } from "@/routes/zona.$cveEnt.$cveMun";

function wrap(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

const rentedShare: MxStat = { value: 24.1, source: "D-MX-INEGI-01", year: 2020, cv: 12 };
const lowPrecisionShare: MxStat = { ...rentedShare, cv: 35, precision_baja: true };
const noSource = () => undefined;

function summary(partial: Partial<MxPriceSummary>): MxPriceSummary {
  return {
    count: 0,
    currency: "MXN",
    basis: "viviendas_publicadas",
    min_count_for_stats: 3,
    as_of: "2026-10-05T12:00:00Z",
    has_stats: false,
    ...partial,
  };
}

afterEach(cleanup);

describe("PriceBlock (three honest treatments)", () => {
  it("shows an honest empty state and NO figures when there are no listings", () => {
    wrap(<PriceBlock cveEnt="09" price={summary({ count: 0, reason: "insufficient_sample" })} rentedShare={rentedShare} rentedShareSource={() => ({ title: "Censo INEGI 2020" })} />);
    // No listing price figures: the min/median/max labels are absent.
    expect(screen.queryByText(/Mediana/)).not.toBeInTheDocument();
    expect(screen.getByText(/No one has listed|Nadie ha publicado/)).toBeInTheDocument();
    // The INEGI statistic is still shown, clearly as a statistic (not a price).
    expect(screen.getByText("24.1%")).toBeInTheDocument();
    expect(screen.getByText(/estadístico del INEGI, no un precio|INEGI statistic, not a price/)).toBeInTheDocument();
    // The legal-requirements link is always present.
    expect(screen.getByText(/Ver requisitos legales|See legal requirements/)).toBeInTheDocument();
  });

  it("explains why there is no price with fewer than three listings", () => {
    wrap(<PriceBlock cveEnt="09" price={summary({ count: 2, reason: "insufficient_sample" })} rentedShareSource={noSource} />);
    expect(screen.queryByText(/Mediana|Median/)).not.toBeInTheDocument();
    expect(screen.getByText(/suficientes anuncios|Not enough listings/)).toBeInTheDocument();
    // No INEGI stat passed -> honest "no data" line, never a placeholder figure.
    expect(screen.getByText(/No hay un dato oficial|no official rented-homes/)).toBeInTheDocument();
  });

  it("shows min / median / max and the provenance badge when there are >= 3 listings", () => {
    const price = summary({ count: 4, has_stats: true, min: 8000, median: 11000, max: 16000 });
    wrap(<PriceBlock cveEnt="09" price={price} rentedShare={rentedShare} rentedShareSource={() => ({ title: "Censo INEGI 2020" })} />);
    expect(screen.getByText(/Publicado por usuarios|Posted by Renta MX users/)).toBeInTheDocument();
    // Formatted MXN amounts (locale grouping, no decimals).
    expect(screen.getByText(/8,000/)).toBeInTheDocument();
    expect(screen.getByText(/11,000/)).toBeInTheDocument();
    expect(screen.getByText(/16,000/)).toBeInTheDocument();
  });

  it("flags low-precision INEGI estimates", () => {
    wrap(<PriceBlock cveEnt="09" price={summary({ count: 0 })} rentedShare={lowPrecisionShare} rentedShareSource={() => ({ title: "Censo INEGI 2020" })} />);
    expect(screen.getByText(/Precisión baja|Low precision/)).toBeInTheDocument();
  });
});
