let csrfToken = "";
let tenantId = "";

export function setCsrf(value: string): void {
  csrfToken = value;
}

export function setTenant(value: string): void {
  tenantId = value;
}

export function authHeaders(): HeadersInit {
  const headers: Record<string, string> = {};
  if (csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  if (tenantId) {
    headers["X-Tenant-Id"] = tenantId;
  }
  return headers;
}
