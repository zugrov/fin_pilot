import { describe, expect, it } from "vitest";

import { WalletRequestError } from "../api";
import { fieldErrorsFromUnknown } from "./orgProfileErrors";

describe("orgProfileErrors", () => {
  it("разбирает field_errors из WalletRequestError", () => {
    const err = new WalletRequestError("msg", 400, "profile_validation_failed", {
      vat_status: ["special_rates_requires_usn"],
    });
    expect(fieldErrorsFromUnknown(err)).toEqual({
      vat_status: ["special_rates_requires_usn"],
    });
  });

  it("пусто для неизвестной ошибки", () => {
    expect(fieldErrorsFromUnknown(new Error("x"))).toEqual({});
  });
});
