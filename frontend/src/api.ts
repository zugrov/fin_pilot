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
