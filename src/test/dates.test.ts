import { describe, expect, it } from "vitest";
import { formatDate, formatDatesInText } from "@/lib/dates";

describe("localized long dates", () => {
  it("formats date-only values without timezone shifts", () => {
    expect(formatDate("2027-07-01", "en")).toBe("July 1, 2027");
    expect(formatDate("2027-07-01", "es")).toBe("1 de julio de 2027");
  });
  it("localizes dates embedded in status lines", () => {
    expect(formatDatesInText("Effective 2027-07-01; reviewed Jan 2, 2026.", "es"))
      .toBe("Effective 1 de julio de 2027; reviewed 2 de enero de 2026.");
    expect(formatDatesInText("Vigente el 1 de julio de 2027", "en"))
      .toBe("Vigente el July 1, 2027");
  });
  it("does not rewrite invalid dates or non-date values", () => {
    expect(formatDate("2027-02-30", "en")).toBe("2027-02-30");
    expect(formatDatesInText("Rule A0113, 7–30 units", "en")).toBe("Rule A0113, 7–30 units");
  });
});