import { authHeaders, setCsrf, setTenant } from "./session";

export type ApiError = {
  code: string;
  message: string;
};

export type TariffExample = {
  companies: number;
  monthly: string;
  annual_list: string;
  annual_payable: string;
  savings: string;
  monthly_equivalent: string;
};

export type Tariff = {
  currency: string;
  annual_discount_percent: string | null;
  annual_billing_enabled: boolean;
  examples: TariffExample[];
};

export type Quote = {
  id: string;
  payable_amount: string;
  interval: string;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const extra = authHeaders();
  Object.entries(extra).forEach(([key, value]) => headers.set(key, value));
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiError | null;
    throw new Error(body?.message ?? "Запрос не выполнен");
  }
  return (await response.json()) as T;
}

export function register(email: string, password: string, name: string) {
  return request<{ status: string; message: string }>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export function verifyEmail(token: string) {
  return request<{ status: string }>("/api/v1/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function login(email: string, password: string) {
  const payload = await request<{ csrf_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setCsrf(payload.csrf_token);
  return payload;
}

export function forgotPassword(email: string) {
  return request<{ message: string }>("/api/v1/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function resetPassword(token: string, password: string) {
  return request<{ status: string }>("/api/v1/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

export async function ensureWorkspace(): Promise<void> {
  const me = await request<{
    csrf_token: string;
    memberships: { tenant_id: string }[];
  }>("/api/v1/auth/me");
  setCsrf(me.csrf_token);
  if (me.memberships.length > 0) {
    setTenant(me.memberships[0].tenant_id);
    return;
  }
  const created = await request<{ id: string }>("/api/v1/workspaces", {
    method: "POST",
    body: JSON.stringify({ name: "Рабочее пространство" }),
  });
  setTenant(created.id);
}

export function loadTariff() {
  return request<Tariff>("/api/v1/billing/tariff");
}

export function createQuote(companies: number, interval: "month" | "year") {
  return request<Quote>("/api/v1/billing/quote", {
    method: "POST",
    body: JSON.stringify({ companies, interval }),
  });
}

export type Company = { id: string; name: string };

export type Dashboard = {
  revenue_label: string;
  quality_flags: string[];
  values: {
    cash_total: string | null;
    available: string | null;
    revenue: string | null;
    net_cash_flow: string | null;
  };
  drilldown_refs: { revenue_entry_ids: string[] };
};

export type Wallet = { id: string; name: string; code: string | null; type: string };

export type RevenueEntry = {
  id: string;
  recognition_date: string;
  document_number: string | null;
  amount_ex_vat: string | null;
  amount_inc_vat: string;
  entry_type: string;
  status: string;
};

export type Source = {
  id: string;
  name: string;
  dataset: string;
  format: string;
  namespace: string;
};

export type ImportPreview = {
  id: string;
  status: string;
  counts: { new: number; repeated: number; changed: number; invalid: number };
  rows: { row_number: number; errors: string[] }[];
};

export function listCompanies() {
  return request<{ csrf_token: string; memberships: { tenant_id: string }[] }>(
    "/api/v1/auth/me",
  ).then(async (me) => {
    setCsrf(me.csrf_token);
    const tenant = me.memberships[0]?.tenant_id;
    if (!tenant) {
      return { companies: [] as Company[] };
    }
    setTenant(tenant);
    return request<{ companies: Company[] }>(`/api/v1/workspaces/${tenant}/companies`);
  });
}

export function loadDashboard(companyId: string) {
  const period = "date_from=2026-10-01&date_to=2026-10-31";
  return request<Dashboard>(`/api/v1/companies/${companyId}/dashboard?${period}`);
}

export function loadWallets(companyId: string) {
  return request<{ wallets: Wallet[] }>(`/api/v1/companies/${companyId}/wallets`);
}

export function loadRevenue(companyId: string) {
  return request<{ entries: RevenueEntry[] }>(`/api/v1/companies/${companyId}/revenue`);
}

export function createRevenue(companyId: string, amountInc: string, amountEx: string, vat: string) {
  return request<RevenueEntry>(`/api/v1/companies/${companyId}/revenue`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      recognition_date: new Date().toISOString().slice(0, 10),
      amount_ex_vat: amountEx,
      vat_amount: vat,
      amount_inc_vat: amountInc,
      entry_type: "sale",
      vat_basis: "net",
    }),
  });
}

export function loadSources(companyId: string) {
  return request<{ sources: Source[] }>(`/api/v1/companies/${companyId}/sources`);
}

export function createSource(companyId: string, dataset: "cash" | "revenue", namespace: string) {
  return request<Source>(`/api/v1/companies/${companyId}/sources`, {
    method: "POST",
    body: JSON.stringify({
      name: dataset === "revenue" ? "Продажи" : "Деньги",
      type: "file",
      namespace,
      format: "csv",
      dataset,
    }),
  });
}

export async function uploadImport(companyId: string, connectionId: string, file: File) {
  const body = new FormData();
  body.set("connection_id", connectionId);
  body.set("upload", file);
  const headers = new Headers(authHeaders());
  headers.set("Idempotency-Key", crypto.randomUUID());
  const response = await fetch(`/api/v1/companies/${companyId}/imports`, {
    method: "POST",
    body,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as ApiError | null;
    throw new Error(payload?.message ?? "Файл не принят");
  }
  return (await response.json()) as ImportPreview;
}

export function commitImport(batchId: string) {
  return request<ImportPreview>(`/api/v1/imports/${batchId}/commit`, { method: "POST" });
}

export function checkout(quoteId: string, idempotencyKey: string) {
  return request<{ confirmation_url: string | null; activated: boolean }>(
    "/api/v1/billing/checkout",
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ quote_id: quoteId, offer_accepted: true }),
    },
  );
}
