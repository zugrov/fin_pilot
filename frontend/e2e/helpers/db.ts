import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../backend");

function runDbAssert(args: string[]): unknown {
  const port = process.env.TEST_PG_PORT ?? "5432";
  const raw = execFileSync("uv", ["run", "python", "-m", "tests.e2e.db_assert", ...args], {
    cwd: backendRoot,
    env: { ...process.env, TEST_PG_PORT: port },
    encoding: "utf-8",
  });
  return JSON.parse(raw.trim()) as unknown;
}

export function countRevenueByDocument(companyId: string, documentNumber: string): number {
  const body = runDbAssert([
    "revenue-count",
    "--company-id",
    companyId,
    "--document-number",
    documentNumber,
  ]) as { count: number };
  return body.count;
}

export function countCompanyRevenue(companyId: string): number {
  const body = runDbAssert(["revenue-count", "--company-id", companyId]) as { count: number };
  return body.count;
}

export function revenueEntryIdByDocument(companyId: string, documentNumber: string): string | null {
  const body = runDbAssert([
    "revenue-entry-id",
    "--company-id",
    companyId,
    "--document-number",
    documentNumber,
  ]) as { id: string | null };
  return body.id;
}

export function countAuditForEntity(action: string, entityId: string): number {
  const body = runDbAssert([
    "audit-count",
    "--action",
    action,
    "--entity-id",
    entityId,
  ]) as { count: number };
  return body.count;
}

export function countMatchesForRevenue(revenueEntryId: string): number {
  const body = runDbAssert(["match-count", "--revenue-entry-id", revenueEntryId]) as {
    count: number;
  };
  return body.count;
}

export function latestMatchIdForRevenue(revenueEntryId: string): string | null {
  const body = runDbAssert(["latest-match-id", "--revenue-entry-id", revenueEntryId]) as {
    id: string | null;
  };
  return body.id;
}
