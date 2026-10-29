import { companyDate } from "./forecast";
import { formatDate } from "./dates";
import { formatMoney } from "./money";

export function planFactPath(companyId: string, reportDate: string): string {
  const query = new URLSearchParams({ report_date: reportDate });
  return `/api/v1/companies/${companyId}/plan-fact?${query.toString()}`;
}

export function defaultReportDate(timeZone: string, now = new Date()): string {
  return companyDate(timeZone, now);
}

export function matchesPlanFact(
  data: { company_id: string; report_date: string } | undefined,
  companyId: string | undefined,
  reportDate: string,
): boolean {
  return Boolean(
    data && companyId && data.company_id === companyId && data.report_date === reportDate,
  );
}

export function calculationCaption(reportDate: string): string {
  return `Расчёт на ${formatDate(reportDate)}`;
}

export function basisLabel(basis: string): string {
  if (basis === "revenue") {
    return "Выручка без НДС";
  }
  if (basis === "cash") {
    return "Деньги";
  }
  return basis;
}

export function versionStatusLabel(status: string | null | undefined): string {
  if (status === "approved") {
    return "утверждён";
  }
  if (status === "draft") {
    return "черновик";
  }
  if (status === "archived") {
    return "архив";
  }
  return "нет версии";
}

export function monthLabel(
  year: number | null | undefined,
  month: number | null | undefined,
): string {
  if (!year || !month) {
    return "—";
  }
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function monthEnd(year: number, month: number): string {
  const end = new Date(Date.UTC(year, month, 0));
  const day = String(end.getUTCDate()).padStart(2, "0");
  const shownMonth = String(end.getUTCMonth() + 1).padStart(2, "0");
  return `${end.getUTCFullYear()}-${shownMonth}-${day}`;
}

export function amountText(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return formatMoney(value);
}

export function cashBudgetNote(cashStatus: string | undefined): string {
  if (cashStatus === "unavailable") {
    return "Денежный бюджет не задан";
  }
  return "";
}

export function salesFactNote(completeness: string | null | undefined): string {
  if (completeness === "known") {
    return "";
  }
  return "Факт по загруженным продажам. Полнота данных не подтверждена.";
}

export function interimNote(
  companyToday: string,
  reportDate: string,
  monthEndDate: string | null,
): string {
  if (!monthEndDate || companyToday < monthEndDate || reportDate < monthEndDate) {
    return "Промежуточный срез, не итог месяца.";
  }
  return "";
}

export function futureFactNote(companyToday: string, reportDate: string): string {
  if (reportDate > companyToday) {
    return (
      "Выбранная дата позже текущей даты фирмы. " +
      "Загруженные продажи не являются итогом этого периода."
    );
  }
  return "";
}

export function draftDisabledReason(): string {
  return "Создание черновика с этого экрана отключено. Прежняя кнопка задавала расход за октябрь.";
}

export function planFactText(status: string, fact: string | null, percent: string | null): string {
  if (status === "unavailable" || fact === null) {
    return "Нет данных о плане-факте";
  }
  if (status === "вне бюджета") {
    return "вне бюджета";
  }
  if (percent === null) {
    return status;
  }
  return `${status}: ${percent}`;
}

export function alertEmpty(status: string, count: number): string {
  if (count > 0) {
    return "";
  }
  if (status !== "ready") {
    return "Нет данных для уверенного вывода";
  }
  return "Открытых алертов нет";
}
