import { describe, expect, it } from "vitest";

import {
  ORG_PROFILE_API_MESSAGES,
  ORG_PROFILE_FIELD_ERROR_MESSAGES,
  ORG_PROFILE_SUPPORT_MESSAGES,
  orgProfileApiMessage,
  orgProfileFieldMessage,
  orgProfileSupportBanner,
} from "./orgProfileMessages";

const VERSION_FLOW_CODES = [
  "draft_exists",
  "effective_from_not_after_latest",
  "profile_version_conflict",
  "not_latest_version",
] as const;

describe("orgProfileMessages API codes", () => {
  for (const code of Object.keys(ORG_PROFILE_API_MESSAGES)) {
    it(`маппит API ${code}`, () => {
      expect(orgProfileApiMessage(code).length).toBeGreaterThan(5);
    });
  }

  it.each(VERSION_FLOW_CODES)("текст версии %s", (code) => {
    expect(orgProfileApiMessage(code)).toMatch(/верси|черновик|дата/i);
  });
});

describe("orgProfileMessages field_errors", () => {
  for (const code of Object.keys(ORG_PROFILE_FIELD_ERROR_MESSAGES)) {
    it(`маппит field ${code}`, () => {
      expect(orgProfileFieldMessage("vat_status", code).length).toBeGreaterThan(5);
    });
  }
});

describe("orgProfileMessages support_code", () => {
  for (const code of Object.keys(ORG_PROFILE_SUPPORT_MESSAGES)) {
    it(`маппит support ${code}`, () => {
      const text = orgProfileSupportBanner(code);
      expect(text).not.toBeNull();
      expect(text!.length).toBeGreaterThan(10);
    });
  }

  it("null support — без баннера", () => {
    expect(orgProfileSupportBanner(null)).toBeNull();
  });
});
