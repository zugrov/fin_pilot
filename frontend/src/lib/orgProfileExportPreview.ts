export type ExportPreviewSnapshot = {
  money_channels?: string[] | null;
  industry_sphere?: string;
  accounting_source?: string;
  vat_status?: string;
  usn_tax_object?: string;
};

export type ExportPreviewLine = {
  title: string;
  period: string;
};

const PERIOD_MONTH = "календарный месяц";

function hasChannel(channels: string[] | null | undefined, code: string): boolean {
  return (channels ?? []).includes(code);
}

function sphereAllowsReceivables(sphere: string | undefined): boolean {
  return sphere === "trade" || sphere === "services" || sphere === "mixed";
}

function vatNeedsReports(status: string | undefined): boolean {
  return status === "vat_payer" || status === "special_rates_5_7";
}

/** Статический предпросмотр выгрузок FA-R03.2 по снимку профиля. */
export function buildExportPreviewLines(snapshot: ExportPreviewSnapshot): ExportPreviewLine[] {
  const lines: ExportPreviewLine[] = [];
  const channels = snapshot.money_channels ?? [];

  if (hasChannel(channels, "bank")) {
    lines.push(
      { title: "Банковская выписка (ClientBank)", period: PERIOD_MONTH },
      { title: "Карточка счёта 51", period: PERIOD_MONTH },
      { title: "Оборотно-сальдовая ведомость (ОСВ) по счетам", period: PERIOD_MONTH },
    );
  }

  if (hasChannel(channels, "acquiring")) {
    lines.push({
      title: "ОСВ или анализ счёта 57.03 (эквайринг)",
      period: PERIOD_MONTH,
    });
  }

  if (hasChannel(channels, "cash")) {
    lines.push({
      title: "Карточка счёта 50 и кассовые документы",
      period: PERIOD_MONTH,
    });
  }

  const accounting = snapshot.accounting_source;
  if (
    (accounting === "onec" || accounting === "cloud") &&
    sphereAllowsReceivables(snapshot.industry_sphere)
  ) {
    lines.push(
      { title: "ОСВ по счёту 62 (дебиторка)", period: PERIOD_MONTH },
      { title: "Карточка счёта 62 (при детальной сверке)", period: PERIOD_MONTH },
    );
  }

  if (vatNeedsReports(snapshot.vat_status)) {
    lines.push({
      title: "ОСВ / анализ счетов НДС (19, 68)",
      period: PERIOD_MONTH,
    });
  }

  if (snapshot.industry_sphere === "production" || snapshot.industry_sphere === "mixed") {
    lines.push({
      title: "ОСВ по счетам 20, 25, 26 (производство)",
      period: PERIOD_MONTH,
    });
  }

  if (snapshot.usn_tax_object === "income_minus_expense") {
    lines.push({
      title: "Расширенный набор строк ОСВ по расходным счетам (УСН Д-Р)",
      period: PERIOD_MONTH,
    });
  }

  return lines;
}
