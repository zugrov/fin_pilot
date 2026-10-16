import { alertsPath, recalculateAlertsPath } from "./lib/alerts";
import { forecastPath, groupForecastPath } from "./lib/forecast";
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

export type Company = { id: string; name: string; status?: string; timezone?: string };

export type BillingSubscription = {
  status: string;
  company_limit: number;
  paid_through: string | null;
  paid_slots: number;
  occupied_slots: number;
  free_slots: number;
  current_interval: string | null;
};

export type PaymentView = {
  id: string;
  status: string;
  activated: boolean;
  amount: string;
  payment_id?: string;
};

export type Dashboard = {
  as_of: string;
  date_from: string;
  date_to: string;
  revenue_label: string;
  quality_flags: string[];
  values: {
    cash_total: string | null;
    opening_balance: string | null;
    cash_in: string | null;
    cash_out: string | null;
    available: string | null;
    revenue: string | null;
    net_cash_flow: string | null;
    operation_count: number | null;
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
  type?: string;
  coverage_through?: string | null;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  host?: string | null;
  folder?: string | null;
  sender?: string | null;
  username?: string | null;
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

export type PlanEvent = {
  id: string;
  direction: string;
  amount: string;
  remaining: string;
  due_date: string;
  expected_date: string;
  status: string;
  overdue: boolean;
  version: number;
};

export type Forecast = {
  company_id: string;
  as_of: string;
  status: string;
  opening: string | null;
  gap_date: string | null;
  gap_amount: string | null;
  points: { date: string; closing: string; inflows: string; outflows: string }[];
  contributions: { date: string; amount: string; direction: string }[];
};

export type GroupForecast = {
  as_of: string;
  status: string;
  group_opening: string | null;
  company_risks: {
    company_id: string;
    gap_amount: string | null;
    gap_date: string | null;
    status: string;
  }[];
};

export function loadCalendar(companyId: string) {
  return request<{ events: PlanEvent[] }>(`/api/v1/companies/${companyId}/calendar`);
}

export function createPlanEvent(companyId: string, amount: string, day: string) {
  return request<PlanEvent>(`/api/v1/companies/${companyId}/planned-cash`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      direction: "out",
      amount,
      due_date: day,
      expected_date: day,
      confidence: "expected",
      priority: "normal",
    }),
  });
}

export function moveExpected(eventId: string, version: number, expectedDate: string) {
  return request<PlanEvent>(`/api/v1/planned-cash/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify({ version, expected_date: expectedDate }),
  });
}

export function loadForecast(companyId: string, asOf: string, scenario = "base") {
  return request<Forecast>(forecastPath(companyId, asOf, scenario));
}

export function loadGroupForecast(asOf: string, scenario = "base") {
  return request<{ csrf_token: string; memberships: { tenant_id: string }[] }>(
    "/api/v1/auth/me",
  ).then((me) => {
    setCsrf(me.csrf_token);
    const tenant = me.memberships[0]?.tenant_id;
    if (!tenant) {
      throw new Error("Нет пространства");
    }
    setTenant(tenant);
    return request<GroupForecast>(groupForecastPath(tenant, asOf, scenario));
  });
}

export type PlanFactLine = {
  status: string;
  fact: string | null;
  percent: string | null;
  plan_to_date: string | null;
  delta: string | null;
  metric_type: string;
};

export type PlanFact = {
  quality_flags: string[];
  bases: { basis: string; status: string; lines: PlanFactLine[] }[];
};

export type BudgetDraft = { id: string; status: string };

export function loadPlanFact(companyId: string) {
  return request<PlanFact>(
    `/api/v1/companies/${companyId}/plan-fact?report_date=2026-10-31`,
  );
}

export function createBudget(companyId: string, amount: string) {
  return request<BudgetDraft>(`/api/v1/companies/${companyId}/budgets`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      name: "Год",
      year: 2026,
      basis: "cash",
      lines: [{ month: 10, metric_type: "cash_out", amount }],
    }),
  });
}

export function approveBudget(versionId: string) {
  return request<BudgetDraft>(`/api/v1/budgets/${versionId}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export type AlertItem = {
  id: string;
  type: string;
  status: string;
  calculated_on: string | null;
  evidence: Record<string, string | number | null>;
};

export type AlertList = {
  report_date: string | null;
  status: string;
  completeness?: string;
  quality_flags: string[];
  alerts: AlertItem[];
};

export function loadAlerts(companyId: string) {
  return request<AlertList>(alertsPath(companyId));
}

export function recalculateAlerts(companyId: string) {
  return request<AlertList>(recalculateAlertsPath(companyId), {
    method: "POST",
  });
}

export function ackAlert(alertId: string) {
  return request<AlertItem>(`/api/v1/alerts/${alertId}/ack`, { method: "POST" });
}

export type MailboxFields = {
  host: string;
  username: string;
  folder: string;
  sender: string;
  password: string;
};

export function createMailbox(companyId: string, walletId: string, fields: MailboxFields) {
  return request<Source>(`/api/v1/companies/${companyId}/sources`, {
    method: "POST",
    body: JSON.stringify({
      name: "Выписка",
      type: "email",
      namespace: `mail-${crypto.randomUUID().slice(0, 8)}`,
      format: "clientbank",
      dataset: "cash",
      wallet_id: walletId,
      mailbox: fields,
    }),
  });
}

export function testMailbox(companyId: string, sourceId: string) {
  return request<{ status: string; saved: boolean }>(
    `/api/v1/companies/${companyId}/sources/${sourceId}/test`,
    { method: "POST" },
  );
}

export function createSource(
  companyId: string,
  dataset: "cash" | "revenue" | "plan" | "budget",
  namespace: string,
) {
  const names = { revenue: "Продажи", plan: "План", budget: "Бюджет", cash: "Деньги" };
  return request<Source>(`/api/v1/companies/${companyId}/sources`, {
    method: "POST",
    body: JSON.stringify({
      name: names[dataset],
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

export type TelegramBinding = {
  status: string;
  id?: string;
  linked_at?: string | null;
};

export type TelegramToken = {
  token: string;
  expires_at: string;
  deep_link: string | null;
};

export type TelegramSubscription = {
  id: string;
  local_time: string;
  timezone: string;
  days_of_week: number[];
  mode: string;
  enabled: boolean;
  instant_alerts: boolean;
  quiet_start: string | null;
  quiet_end: string | null;
  privacy_level: string;
  company_scope: string[] | null;
};

export type TelegramPreview = {
  text: string;
  sent: boolean;
  content_hash: string;
};

export function createLinkToken() {
  return request<TelegramToken>("/api/v1/telegram/link-token", { method: "POST" });
}

export function loadBinding() {
  return request<TelegramBinding>("/api/v1/telegram/binding");
}

export function confirmBinding() {
  return request<TelegramBinding>("/api/v1/telegram/binding/confirm", { method: "POST" });
}

export function unlinkBinding() {
  return request<TelegramBinding>("/api/v1/telegram/binding", { method: "DELETE" });
}

export function loadSubscription() {
  return request<TelegramSubscription>("/api/v1/telegram/subscription");
}

export function saveSubscription(payload: {
  local_time: string;
  timezone: string;
  days_of_week: number[];
  mode: string;
  enabled: boolean;
  instant_alerts: boolean;
  privacy_level: string;
}) {
  return request<TelegramSubscription>("/api/v1/telegram/subscription", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function previewDigest() {
  return request<TelegramPreview>("/api/v1/telegram/digest-preview", { method: "POST" });
}

export function checkout(quoteId: string, idempotencyKey: string) {
  return request<{ confirmation_url: string | null; activated: boolean; payment_id?: string }>(
    "/api/v1/billing/checkout",
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ quote_id: quoteId, offer_accepted: true }),
    },
  );
}

export async function loadBillingSubscription() {
  await ensureWorkspace();
  return request<BillingSubscription>("/api/v1/billing/subscription");
}

export async function loadPayment(paymentId: string) {
  await ensureWorkspace();
  return request<PaymentView>(`/api/v1/billing/payments/${paymentId}`);
}

async function withWorkspace<T>(action: (tenantId: string) => Promise<T>): Promise<T> {
  const me = await request<{ csrf_token: string; memberships: { tenant_id: string }[] }>(
    "/api/v1/auth/me",
  );
  setCsrf(me.csrf_token);
  const tenantId = me.memberships[0]?.tenant_id;
  if (!tenantId) {
    throw new Error("Нет рабочего пространства");
  }
  setTenant(tenantId);
  return action(tenantId);
}

export function createCompany(name: string, idempotencyKey: string) {
  return withWorkspace((tenantId) =>
    request<Company>(`/api/v1/workspaces/${tenantId}/companies`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ name, kind: "company" }),
    }),
  );
}

export function activateCompany(companyId: string) {
  return request<{ company_id: string; status: string }>(
    `/api/v1/billing/companies/${companyId}/activate`,
    { method: "POST" },
  );
}
