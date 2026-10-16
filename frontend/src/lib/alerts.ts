export function alertsPath(companyId: string): string {
  return `/api/v1/companies/${companyId}/alerts`;
}

export function recalculateAlertsPath(companyId: string): string {
  return `/api/v1/companies/${companyId}/alerts/recalculate`;
}

export function savedCalculationCaption(reportDate: string | null): string {
  if (!reportDate) {
    return "Сохранённого расчёта нет";
  }
  return `Последний расчёт на ${reportDate}`;
}

export function completenessCaption(completeness: string | null | undefined): string {
  if (completeness === "unknown") {
    return "Полнота не определена для сохранённого расчёта";
  }
  return "";
}
