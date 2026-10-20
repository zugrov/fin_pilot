import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { E2E_PASSWORD } from "./seed";

export { E2E_PASSWORD };

export type PolygonCompanyMeta = {
  id: string;
  name: string;
};

export type PolygonMeta = {
  ownerEmail: string;
  workspaceName: string;
  tenantId: string;
  frozenIso: string;
  companies: {
    services: PolygonCompanyMeta;
    retail: PolygonCompanyMeta;
    subscription: PolygonCompanyMeta;
  };
};

export type PolygonOracle = {
  period_from: string;
  period_to: string;
  revenue_label: string;
  group: { cash_total: string; revenue: string };
  companies: Record<
    string,
    {
      opening_balance: string;
      cash_total: string;
      operation_count: number;
      revenue_net_ex_vat: string;
    }
  >;
  plan_move_services: {
    amount: string;
    cash_total_unchanged: string;
    forecast_unpaid_before: string;
    forecast_unpaid_after: string;
    moved_expected: string;
    plan_marker_due: string;
    calendar_expected_after: string;
  };
};

const here = path.dirname(fileURLToPath(import.meta.url));

export function loadPolygonMeta(): PolygonMeta {
  const file = path.join(here, "polygon-meta.json");
  if (!fs.existsSync(file)) {
    throw new Error(
      "polygon-meta.json отсутствует. Запустите: cd backend && uv run python -m tests.e2e.prepare_polygon",
    );
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as PolygonMeta;
}

export function loadPolygonOracle(): PolygonOracle {
  const file = path.join(here, "polygon-oracle.json");
  if (!fs.existsSync(file)) {
    throw new Error(
      "polygon-oracle.json отсутствует. Запустите: cd backend && uv run python -m tests.synthetic_polygon.build",
    );
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as PolygonOracle;
}

export const POLYGON_CLOCK_ISO = "2026-11-01T06:00:00.000Z";
