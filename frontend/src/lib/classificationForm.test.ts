import { describe, expect, it } from "vitest";

import {
  buildConditionsPayload,
  formatRuleConditionsHuman,
  validateRuleCreate,
  EMPTY_RULE_DRAFT,
  type RuleCreatePayload,
} from "./classificationForm";
import { applyAfterFailure, resolveSubmit, writeFailureMessage } from "./salesPlanForm";

describe("classificationForm", () => {
  it("formats conditions in Russian", () => {
    const text = formatRuleConditionsHuman({
      description_contains: "Оплата",
      counterparty_inn: "7700000202",
      direction: "in",
      amount_min: "100.00",
      amount_max: "500.00",
    });
    expect(text).toContain("Оплата");
    expect(text).toContain("ИНН 7700000202");
    expect(text).toContain("Поступление");
    expect(text).toContain("100.00");
  });

  it("rejects empty conditions", () => {
    const result = validateRuleCreate({
      ...EMPTY_RULE_DRAFT,
      name: "Test",
      categoryCode: "operating",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("хотя бы одно условие");
    }
  });

  it("rejects invalid inn and amount range", () => {
    const badInn = validateRuleCreate({
      ...EMPTY_RULE_DRAFT,
      name: "Test",
      categoryCode: "operating",
      conditions: {
        ...EMPTY_RULE_DRAFT.conditions,
        counterpartyInn: "123",
        direction: "in",
      },
    });
    expect(badInn.ok).toBe(false);

    const badRange = validateRuleCreate({
      ...EMPTY_RULE_DRAFT,
      name: "Test",
      categoryCode: "operating",
      conditions: {
        ...EMPTY_RULE_DRAFT.conditions,
        direction: "in",
        amountMin: "500.00",
        amountMax: "100.00",
      },
    });
    expect(badRange.ok).toBe(false);
  });

  it("builds payload with at least one condition", () => {
    const payload = buildConditionsPayload({
      descriptionContains: "Bulk",
      counterpartyInn: "",
      direction: "in",
      amountMin: "",
      amountMax: "",
    });
    expect(payload).toEqual({ description_contains: "Bulk", direction: "in" });
  });

  it("reuses idempotency key after unknown create outcome", () => {
    const payload: RuleCreatePayload = {
      companyId: "c1",
      name: "Rule",
      priority: 10,
      categoryCode: "operating",
      conditions: { direction: "in" },
    };
    const prior = { key: "rule-key-1", payload, phase: "unknown" as const };
    const resolved = resolveSubmit(prior, payload, () => "new-key");
    expect(resolved.kind).toBe("submit");
    if (resolved.kind === "submit") {
      expect(resolved.attempt.key).toBe("rule-key-1");
    }
  });

  it("appends unknown-outcome hint for write failures", () => {
    const msg = writeFailureMessage("Сбой сети.", 0, "");
    expect(msg).toContain("повторите отправку");
    expect(msg).toContain("Сбой сети.");
  });

  it("clears create attempt on 422 validation", () => {
    const attempt = {
      key: "rule-key-2",
      payload: { companyId: "c1" },
      phase: "executing" as const,
    };
    expect(applyAfterFailure(attempt, 422, "validation_error")).toBeNull();
  });
});
