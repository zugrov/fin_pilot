import { describe, expect, it } from "vitest";

import {
  orgProfileApiMessage,
  orgProfileFieldMessage,
  orgProfileMissingLabel,
  orgProfileSupportBanner,
} from "./orgProfileMessages";

describe("orgProfileMessages", () => {
  it("маппит коды API", () => {
    expect(orgProfileApiMessage("conflict")).toContain("ИНН");
    expect(orgProfileApiMessage("forbidden")).toContain("прав");
  });

  it("маппит field_errors", () => {
    expect(orgProfileFieldMessage("inn", "inn_checksum_mismatch")).toContain("контрольная сумма");
    expect(orgProfileFieldMessage("vat_status", "special_rates_requires_usn")).toContain("УСН");
  });

  it("support и missing", () => {
    expect(orgProfileSupportBanner("tax_system_not_supported")).toContain("не поддерживает");
    expect(orgProfileMissingLabel("org_form")).toContain("форма");
  });
});
