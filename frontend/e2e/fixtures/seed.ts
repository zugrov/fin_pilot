import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_PASSWORD = "long-password-1";

export type SeedMeta = {
  ownerEmail: string;
  workspaceName: string;
  companyAName: string;
  companyBName: string;
  companyAId: string;
  companyBId: string;
  frozenDate: string;
};

const here = path.dirname(fileURLToPath(import.meta.url));

export function loadSeedMeta(): SeedMeta {
  const file = path.join(here, "seed-meta.json");
  if (!fs.existsSync(file)) {
    throw new Error(
      "seed-meta.json отсутствует. Запустите: cd backend && uv run python -m tests.e2e.prepare",
    );
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as SeedMeta;
}

export const FIXTURES = path.resolve(here, "../../../backend/tests/fixtures/imports");
export const E2E_FIXTURES = path.resolve(here, "../../../backend/tests/e2e/fixtures");
