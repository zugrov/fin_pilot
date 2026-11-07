import { describe, expect, it } from "vitest";

import { shouldPatchCurrentPeriodProfileCache } from "./orgProfileConfirmCache";

describe("orgProfileConfirmCache", () => {
  it("патчит кэш текущего месяца, если effective_from ≤ currentPeriod", () => {
    expect(shouldPatchCurrentPeriodProfileCache("2026-03-01", "2026-11-01")).toBe(true);
    expect(shouldPatchCurrentPeriodProfileCache("2026-11-01", "2026-11-01")).toBe(true);
  });

  it("не патчит кэш текущего месяца для будущей версии", () => {
    expect(shouldPatchCurrentPeriodProfileCache("2027-04-01", "2026-11-01")).toBe(false);
  });
});
