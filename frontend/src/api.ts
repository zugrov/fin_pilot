import { alertsPath, recalculateAlertsPath } from "./lib/alerts";
import { planFactPath } from "./lib/budget";
import { forecastPath, groupForecastPath } from "./lib/forecast";
import { authHeaders, setCsrf, setTenant } from "./session";

export type ApiError = {
  code: string;
  message: string;
};

export class WalletRequestError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "WalletRequestError";
    this.status = status;
    this.code = code;
  }
}

async function walletRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const extra = authHeaders();
  Object.entries(extra).forEach(([key, value]) => headers.set(key, value));
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiError | null;
    throw new WalletRequestError(
      body?.message ?? "Запрос не выполнен",
      response.status,
      body?.code ?? "",
    );
  }
  return (await response.json()) as T;
}

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

export type WalletActiveOpening = { amount: string; effective_at: string };

export type Wallet = {
  id: string;
  company_id?: string;
  name: string;
  code: string | null;
  type: string;
  currency?: string;
  balance?: string | null;
  quality_flags?: string[];
  active_opening?: WalletActiveOpening | null;
};

export type OpeningBalanceResult = {
  id: string;
  wallet_id: string;
  effective_at: string;
  amount: string;
  status: string;
};

export type MatchLink = {
  cash_transaction_id: string;
  amount: string;
  label: string;
};

export type RevenueEntry = {
  id: string;
  company_id?: string;
  recognition_date: string;
  document_number: string | null;
  external_id?: string | null;
  amount_ex_vat: string | null;
  vat_amount?: string | null;
  amount_inc_vat: string;
  entry_type: string;
  status: string;
  matched_amount?: string;
  unallocated_amount?: string;
  match_links?: MatchLink[];
};

export type ClassificationEvidencePayload =
  | { status: "recorded"; rule_id: string; rule_version: number }
  | { status: "legacy_unknown" }
  | { status: "manual" };

export type CashTransactionRow = {
  id: string;
  company_id: string;
  business_date: string;
  direction: string;
  amount: string;
  currency: string;
  description: string;
  counterparty_name?: string;
  counterparty_inn?: string;
  category_id: string | null;
  status: string;
  version: number;
  locked_classification?: boolean;
  classification_origin?: string;
  classification_evidence?: ClassificationEvidencePayload | null;
  revenue_matched?: string;
  plan_matched?: string;
  revenue_unallocated?: string;
  plan_unallocated?: string;
};

export type CashCategoryRow = {
  id: string;
  code: string;
  name: string;
  cash_flow_section: string;
  direction: string;
};

export type ClassificationRuleRow = {
  id: string;
  name: string;
  priority: number;
  conditions: Record<string, string>;
  actions: { category_code: string };
  enabled: boolean;
  version: number;
};

export type ClassificationRuleWarning = {
  code: string;
  message: string;
  priority?: number;
  rule_ids?: string[];
  affected_transactions?: number;
};

export type ClassificationRuleCreateResult = ClassificationRuleRow & {
  warnings?: ClassificationRuleWarning[];
};

export type RulePreviewResult = {
  matches: { transaction_id: string; description: string; category_code: string }[];
  total_matches: number;
  truncated: boolean;
  skipped_locked: number;
  skipped_categorized: number;
  skipped_higher_priority: number;
  warnings?: ClassificationRuleWarning[];
};

export type RuleApplyResult = {
  applied: number;
  skipped_locked: number;
  skipped_categorized: number;
  skipped_higher_priority: number;
  total_matches: number;
  has_more: boolean;
  cursor: { business_date: string; transaction_id: string } | null;
  warnings?: ClassificationRuleWarning[];
};

export type UnclassifiedSummary = {
  period: { date_from: string; date_to: string };
  in: { count: number; amount: string };
  out: { count: number; amount: string };
};

export type UnclassifiedList = {
  transactions: CashTransactionRow[];
  has_more: boolean;
  cursor: { business_date: string; transaction_id: string } | null;
};

export type CashflowReport = {
  sections: { code: string; in: string; out: string }[];
  net_external: string;
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

export type ImportPreviewRow = {
  row_number: number;
  errors: string[];
  intent?: string;
  wallet_code?: string;
  currency?: string;
  company_timezone?: string;
  before?: { opening_id?: string; amount?: string; effective_at?: string } | null;
  after?: { amount?: string; effective_at?: string } | null;
};

export type ImportPreview = {
  id: string;
  status: string;
  counts: { new: number; repeated: number; changed: number; invalid: number };
  rows: ImportPreviewRow[];
  preview_token?: string;
  preview_revision?: number;
  commit_blocked?: boolean;
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

export function createWallet(
  companyId: string,
  body: {
    name: string;
    type: string;
    code: string;
    availability_type?: string;
  },
  idempotencyKey: string,
) {
  return walletRequest<Wallet>(`/api/v1/companies/${companyId}/wallets`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      availability_type: "spendable",
      minimum_reserve: "0.00",
      ...body,
    }),
  });
}

export function setWalletOpeningBalance(
  walletId: string,
  effectiveAt: string,
  amount: string,
  idempotencyKey: string,
) {
  return walletRequest<OpeningBalanceResult>(`/api/v1/wallets/${walletId}/opening-balance`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ effective_at: effectiveAt, amount }),
  });
}

export function loadRevenue(companyId: string) {
  return request<{ entries: RevenueEntry[] }>(`/api/v1/companies/${companyId}/revenue`);
}

export function createRevenue(
  companyId: string,
  body: {
    recognition_date: string;
    amount_inc_vat: string;
    amount_ex_vat: string;
    vat_amount: string;
    document_number?: string;
    external_id?: string;
  },
  idempotencyKey: string,
) {
  return walletRequest<RevenueEntry>(`/api/v1/companies/${companyId}/revenue`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      ...body,
      entry_type: "sale",
      vat_basis: "net",
    }),
  });
}

export function createRevenueCashMatch(
  companyId: string,
  revenueEntryId: string,
  cashTransactionId: string,
  amount: string,
  idempotencyKey: string,
) {
  return walletRequest<{
    id: string;
    company_id: string;
    revenue_entry_id: string;
    cash_transaction_id: string;
    amount: string;
  }>("/api/v1/revenue-cash-matches", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      company_id: companyId,
      revenue_entry_id: revenueEntryId,
      cash_transaction_id: cashTransactionId,
      amount,
    }),
  });
}

export function loadTransactions(companyId: string, status = "posted") {
  const query = new URLSearchParams({ status, limit: "100" });
  return request<{ transactions: CashTransactionRow[] }>(
    `/api/v1/companies/${companyId}/transactions?${query.toString()}`,
  );
}

export function loadSources(companyId: string) {
  return request<{ sources: Source[] }>(`/api/v1/companies/${companyId}/sources`);
}

export type PlanEvent = {
  id: string;
  company_id?: string;
  direction: string;
  amount: string;
  matched?: string;
  remaining: string;
  due_date: string;
  expected_date: string;
  status: string;
  overdue: boolean;
  version: number;
  match_links?: MatchLink[];
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

export function createPlanEvent(
  companyId: string,
  body: {
    direction: "in" | "out";
    amount: string;
    due_date: string;
    expected_date: string;
  },
  idempotencyKey: string,
) {
  return walletRequest<PlanEvent>(`/api/v1/companies/${companyId}/planned-cash`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      ...body,
      confidence: "expected",
      priority: "normal",
    }),
  });
}

export function createPlanPaymentMatch(
  companyId: string,
  eventId: string,
  cashTransactionId: string,
  amount: string,
  idempotencyKey: string,
) {
  return walletRequest<PlanEvent>("/api/v1/payment-matches", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      company_id: companyId,
      event_id: eventId,
      cash_transaction_id: cashTransactionId,
      amount,
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
  line_id?: string;
  month?: number;
  metric_type: string;
  status: string;
  fact: string | null;
  percent: string | null;
  plan_month?: string | null;
  plan_to_date: string | null;
  delta: string | null;
  period_from?: string;
  period_to?: string;
};

export type PlanFactBasis = {
  basis: string;
  status: string;
  version_id?: string | null;
  version_status?: string | null;
  year?: number;
  completeness?: string;
  lines: PlanFactLine[];
};

export type PlanFact = {
  company_id: string;
  report_date: string;
  quality_flags: string[];
  bases: PlanFactBasis[];
};

export function loadPlanFact(companyId: string, reportDate: string) {
  return request<PlanFact>(planFactPath(companyId, reportDate));
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
  dataset: "cash" | "revenue" | "plan" | "budget" | "balances",
  namespace: string,
) {
  const names = {
    revenue: "Продажи",
    plan: "План",
    budget: "Бюджет",
    cash: "Деньги",
    balances: "Остатки",
  };
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

export function commitImport(batchId: string, previewToken?: string) {
  const headers = new Headers(authHeaders());
  if (previewToken) {
    headers.set("Preview-Token", previewToken);
  }
  return request<ImportPreview>(`/api/v1/imports/${batchId}/commit`, { method: "POST", headers });
}

export function refreshImportPreview(batchId: string) {
  return request<ImportPreview>(`/api/v1/imports/${batchId}/refresh-preview`, { method: "POST" });
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

export function listClassificationRules(companyId: string) {
  return request<{ rules: ClassificationRuleRow[] }>(
    `/api/v1/companies/${companyId}/classification-rules`,
  );
}

export function createClassificationRule(
  companyId: string,
  body: {
    name: string;
    priority: number;
    conditions: Record<string, string>;
    category_code: string;
  },
  idempotencyKey: string,
) {
  return walletRequest<ClassificationRuleCreateResult>(
    `/api/v1/companies/${companyId}/classification-rules`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    },
  );
}

export function patchClassificationRule(
  ruleId: string,
  body: {
    company_id: string;
    enabled?: boolean;
    priority?: number;
    name?: string;
  },
) {
  return request<ClassificationRuleRow>(`/api/v1/rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function previewClassificationRule(ruleId: string, companyId: string) {
  return request<RulePreviewResult>(`/api/v1/rules/${ruleId}/preview`, {
    method: "POST",
    body: JSON.stringify({ company_id: companyId }),
  });
}

export function applyClassificationRulePage(
  ruleId: string,
  companyId: string,
  cursor: { business_date: string; transaction_id: string } | null,
) {
  const body: Record<string, string> = { company_id: companyId };
  if (cursor) {
    body.after_business_date = cursor.business_date;
    body.after_transaction_id = cursor.transaction_id;
  }
  return request<RuleApplyResult>(`/api/v1/rules/${ruleId}/apply`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function loadUnclassifiedSummary(companyId: string, dateFrom: string, dateTo: string) {
  const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
  return request<UnclassifiedSummary>(
    `/api/v1/companies/${companyId}/transactions/unclassified/summary?${query.toString()}`,
  );
}

export function loadUnclassifiedTransactions(
  companyId: string,
  params: {
    dateFrom: string;
    dateTo: string;
    limit: number;
    cursor: { business_date: string; transaction_id: string } | null;
  },
) {
  const query = new URLSearchParams({
    date_from: params.dateFrom,
    date_to: params.dateTo,
    limit: String(params.limit),
  });
  if (params.cursor) {
    query.set("after_business_date", params.cursor.business_date);
    query.set("after_transaction_id", params.cursor.transaction_id);
  }
  return request<UnclassifiedList>(
    `/api/v1/companies/${companyId}/transactions/unclassified?${query.toString()}`,
  );
}

export function listCashCategories(companyId: string) {
  return request<{ categories: CashCategoryRow[] }>(
    `/api/v1/companies/${companyId}/cash-categories`,
  );
}

export function classifyCashTransaction(
  transactionId: string,
  body: { version: number; category_id: string },
) {
  return request<CashTransactionRow>(`/api/v1/transactions/${transactionId}/classify`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function loadCashflow(companyId: string, dateFrom: string, dateTo: string) {
  const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
  return request<CashflowReport>(`/api/v1/companies/${companyId}/cashflow?${query.toString()}`);
}
