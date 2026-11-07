import { describe, expect, it } from "vitest";

import { defaultEffectiveFromMonth } from "./orgProfileEffectiveFrom";

describe("orgProfileEffectiveFrom", () => {
  it("считает первое число следующего месяца в TZ компании", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    expect(defaultEffectiveFromMonth("Europe/Moscow", now)).toBe("2026-04-01");
  });

  it("переходит на следующий год в декабре", () => {
    const now = new Date("2026-12-10T12:00:00Z");
    expect(defaultEffectiveFromMonth("Europe/Moscow", now)).toBe("2027-01-01");
  });
});
