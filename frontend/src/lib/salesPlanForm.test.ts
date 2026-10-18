import { describe, expect, it } from "vitest";

import {
  applyAfterFailure,
  payloadKey,
  resolveSubmit,
  shouldBlockFieldEdit,
} from "./salesPlanForm";

describe("salesPlanForm", () => {
  it("reuses key while payload unchanged in unknown phase", () => {
    const payload = {
      companyId: "c1",
      recognitionDate: "2026-10-10",
      amountInc: "120.00",
      amountEx: "100.00",
      vat: "20.00",
      documentNumber: "",
      externalId: "",
    };
    const prior = { key: "k1", payload, phase: "unknown" as const };
    const resolved = resolveSubmit(prior, payload, () => "new");
    expect(resolved.kind).toBe("submit");
    if (resolved.kind === "submit") {
      expect(resolved.attempt.key).toBe("k1");
      expect(resolved.attempt.phase).toBe("executing");
    }
  });

  it("blocks submit when payload changes during unknown", () => {
    const prior = {
      key: "k1",
      payload: {
        companyId: "c1",
        recognitionDate: "2026-10-10",
        amountInc: "120.00",
        amountEx: "100.00",
        vat: "20.00",
        documentNumber: "",
        externalId: "",
      },
      phase: "unknown" as const,
    };
    const resolved = resolveSubmit(prior, { ...prior.payload, amountInc: "121.00" }, () => "new");
    expect(resolved.kind).toBe("blocked");
  });

  it("clears attempt on definite 422", () => {
    const attempt = {
      key: "k",
      payload: { companyId: "c1" },
      phase: "executing" as const,
    };
    expect(applyAfterFailure(attempt, 422, "validation_error")).toBeNull();
  });

  it("marks unknown on 500", () => {
    const attempt = {
      key: "k",
      payload: { companyId: "c1" },
      phase: "executing" as const,
    };
    const next = applyAfterFailure(attempt, 500, "");
    expect(next?.phase).toBe("unknown");
  });

  it("blocks fields while awaiting outcome", () => {
    expect(shouldBlockFieldEdit({ key: "k", payload: { companyId: "c" }, phase: "executing" })).toBe(
      true,
    );
    expect(shouldBlockFieldEdit(null)).toBe(false);
  });

  it("payloadKey distinguishes payloads", () => {
    expect(payloadKey({ a: 1 })).not.toBe(payloadKey({ a: 2 }));
  });
});
