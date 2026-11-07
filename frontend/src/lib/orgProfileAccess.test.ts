import { describe, expect, it } from "vitest";

import { isOrgProfileReadOnly } from "./orgProfileAccess";

describe("orgProfileAccess", () => {
  it("viewer readOnly при can_write false", () => {
    expect(isOrgProfileReadOnly(false)).toBe(true);
  });

  it("writer при can_write true", () => {
    expect(isOrgProfileReadOnly(true)).toBe(false);
  });

  it("до загрузки профиля не блокирует", () => {
    expect(isOrgProfileReadOnly(undefined)).toBe(false);
  });
});
