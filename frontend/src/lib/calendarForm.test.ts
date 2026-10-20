import { describe, expect, it } from "vitest";

import {
  directionLabel,
  EMPTY_PLAN_DRAFT,
  validateMatchAmount,
  validatePlanCreate,
} from "./calendarForm";

describe("calendarForm", () => {
  it("rejects empty plan draft", () => {
    expect(validatePlanCreate(EMPTY_PLAN_DRAFT).ok).toBe(false);
    expect(validatePlanCreate({ ...EMPTY_PLAN_DRAFT, amount: "10.00" }).ok).toBe(false);
  });

  it("accepts valid plan draft", () => {
    const result = validatePlanCreate({
      amount: "1500.00",
      dueDate: "2026-10-15",
      expectedDate: "2026-10-20",
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.amount).toBe("1500.00");
    }
  });

  it("labels direction in Russian", () => {
    expect(directionLabel("in")).toBe("Поступление");
    expect(directionLabel("out")).toBe("Списание");
  });

  it("validates match amount format", () => {
    expect(validateMatchAmount("1.00").ok).toBe(true);
    expect(validateMatchAmount("").ok).toBe(false);
  });
});
