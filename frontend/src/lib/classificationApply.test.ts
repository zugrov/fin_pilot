import { describe, expect, it, vi } from "vitest";

import {
  applyRuleUntilDone,
  mergeApplyCounters,
  shouldAcceptPreviewResponse,
} from "./classificationApply";

describe("classificationApply", () => {
  it("ignores stale preview responses", () => {
    expect(shouldAcceptPreviewResponse(2, 2)).toBe(true);
    expect(shouldAcceptPreviewResponse(2, 1)).toBe(false);
  });

  it("merges counters across pages", () => {
    const merged = mergeApplyCounters(
      { applied: 1, skipped_locked: 0, skipped_categorized: 0, skipped_higher_priority: 0, total_matches: 1 },
      { applied: 2, skipped_locked: 1, skipped_categorized: 0, skipped_higher_priority: 0, total_matches: 2 },
    );
    expect(merged.applied).toBe(3);
    expect(merged.skipped_locked).toBe(1);
  });

  it("walks cursor until has_more false", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        applied: 1000,
        skipped_locked: 0,
        skipped_categorized: 0,
        skipped_higher_priority: 0,
        total_matches: 1000,
        has_more: true,
        cursor: { business_date: "2026-01-01", transaction_id: "a" },
      })
      .mockResolvedValueOnce({
        applied: 1,
        skipped_locked: 0,
        skipped_categorized: 0,
        skipped_higher_priority: 0,
        total_matches: 1,
        has_more: false,
        cursor: null,
      });
    const totals = await applyRuleUntilDone(fetchPage);
    expect(totals.applied).toBe(1001);
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(fetchPage.mock.calls[1][0]).toEqual({
      business_date: "2026-01-01",
      transaction_id: "a",
    });
  });
});
