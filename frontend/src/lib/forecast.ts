import { formatDate } from "./dates";
import { formatMoney } from "./money";

export const COMPANY_TIMEZONE_FALLBACK = "Europe/Moscow";

export function companyDate(timeZone: string, now = new Date()): string {
  const zone = timeZone || COMPANY_TIMEZONE_FALLBACK;
  try {
    return formatZoneDate(now, zone);
  } catch {
    if (zone === COMPANY_TIMEZONE_FALLBACK) {
      throw new Error("Некорректный часовой пояс");
    }
    return formatZoneDate(now, COMPANY_TIMEZONE_FALLBACK);
  }
}

export function forecastPath(companyId: string, asOf: string, scenario: string): string {
  const query = new URLSearchParams({ as_of: asOf, scenario });
  return `/api/v1/companies/${companyId}/forecast?${query.toString()}`;
}

export function groupForecastPath(tenantId: string, asOf: string, scenario: string): string {
  const query = new URLSearchParams({ as_of: asOf, scenario });
  return `/api/v1/workspaces/${tenantId}/forecast?${query.toString()}`;
}

export function matchesSelection(
  data: { company_id: string; as_of: string } | undefined,
  companyId: string | undefined,
  asOf: string,
): boolean {
  return Boolean(data && companyId && data.company_id === companyId && data.as_of === asOf);
}

export function forecastCaption(asOf: string): string {
  return `Расчёт на ${formatDate(asOf)}`;
}

export function gapDisplay(amount: string | null, status: string): string {
  if (status === "preliminary" || amount === null) {
    return "Нет данных о прогнозе";
  }
  if (amount === "0.00") {
    return "Дефицита в горизонте нет";
  }
  return `Дефицит: ${amount}`;
}

export function closingLabel(day: string, closing: string): string {
  return `Прогнозный остаток на ${formatDate(day)}: ${formatMoney(closing)}`;
}

export function unpaidLabel(amount: string, day: string): string {
  return `Неоплаченная выплата ${formatMoney(amount)} на ${formatDate(day)}`;
}

export function forecastErrorText(): string {
  return "Не удалось посчитать прогноз.";
}

function formatZoneDate(now: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const year = parts.find((item) => item.type === "year")?.value;
  const month = parts.find((item) => item.type === "month")?.value;
  const day = parts.find((item) => item.type === "day")?.value;
  if (!year || !month || !day) {
    throw new Error("bad date");
  }
  return `${year}-${month}-${day}`;
}
