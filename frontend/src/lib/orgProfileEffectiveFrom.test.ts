import { describe, expect, it } from "vitest";

import { defaultEffectiveFromMonth, monthInputMinAfterVersion } from "./orgProfileEffectiveFrom";

describe("orgProfileEffectiveFrom", () => {
  it("считает первое число следующего месяца в TZ компании", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    expect(defaultEffectiveFromMonth("Europe/Moscow", now)).toBe("2026-04-01");
  });

  it("переходит на следующий год в декабре", () => {
    const now = new Date("2026-12-10T12:00:00Z");
    expect(defaultEffectiveFromMonth("Europe/Moscow", now)).toBe("2027-01-01");
  });

  it("min month после версии", () => {
    expect(monthInputMinAfterVersion("2026-06-01")).toBe("2026-07");
    expect(monthInputMinAfterVersion("2026-12-01")).toBe("2027-01");
  });
});
