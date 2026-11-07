import type { OrganizationProfile } from "../api";
import { orgProfileMissingLabel } from "./orgProfileMessages";
import { snapshotToVatQuestion, type VatQuestionId } from "./orgProfileVat";

const VALUE_LABELS: Record<string, Record<string, string>> = {
  org_form: {
    unspecified: "Не выбрано",
    ip: "ИП",
    ooo: "ООО",
    ao: "АО",
  },
  tax_system: {
    unspecified: "Не выбрано",
    usn: "УСН",
    osno: "ОСНО",
    ausn: "АУСН",
    psn: "ПСН",
    eshn: "ЕСХН",
    self_employed: "Самозанятый",
  },
  usn_tax_object: {
    unspecified: "Не применимо",
    income: "Доходы",
    income_minus_expense: "Доходы минус расходы",
  },
  accounting_source: {
    unspecified: "Не выбрано",
    onec: "1С",
    cloud: "Облачная бухгалтерия",
    book_csv: "Книга / CSV",
  },
  industry_sphere: {
    unspecified: "Не выбрано",
    trade: "Торговля",
    services: "Услуги",
    production: "Производство",
    mixed: "Смешанная",
  },
  month_close_policy: {
    unknown: "Не выбрано",
    calendar_month_end: "Конец календарного месяца",
    manual: "Вручную",
    other: "Иное",
  },
  revenue_recognition_method: {
    unknown: "Не выбрано",
    accrual: "Начисление",
    cash: "Кассовый метод",
    other: "Иное",
  },
  prices_include_vat: {
    unknown: "Не знаю",
    yes: "Да",
    no: "Нет",
  },
  prior_year_revenue_band: {
    unknown: "Не указано",
    unspecified: "Не указано",
    under_exemption_threshold: "До порога освобождения",
    from_threshold_to_cap_5: "От порога до потолка 5%",
    from_cap_5_to_cap_7: "От потолка 5% до 7%",
    over_cap_7: "Свыше потолка 7%",
  },
};

const VAT_QUESTION_LABELS: Record<VatQuestionId, string> = {
  general_payer: "Да, общий порядок",
  usn_special: "Да, на УСН со ставкой 5% или 7%",
  exemption_145: "Нет, освобождён по ст. 145",
  not_applicable: "Нет, НДС не применяется",
  unknown: "Не знаю",
};

const MONEY_CHANNEL_LABELS: Record<string, string> = {
  bank: "Банк",
  acquiring: "Эквайринг",
  cash: "Касса",
  other: "Прочее",
  unspecified: "Не указано",
};

export function formatProfileValue(field: string, raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") {
    return "—";
  }
  return VALUE_LABELS[field]?.[raw] ?? raw;
}

export function formatMoneyChannels(channels: string[] | null | undefined): string {
  const list = (channels ?? []).filter((code) => code !== "unspecified");
  if (!list.length) {
    return "Не указано";
  }
  return list.map((code) => MONEY_CHANNEL_LABELS[code] ?? code).join(", ");
}

export function formatVatAnswer(profile: Pick<OrganizationProfile, "vat_status" | "vat_default_rate">): string {
  const question = snapshotToVatQuestion(profile);
  const base = VAT_QUESTION_LABELS[question];
  if (question === "general_payer" && profile.vat_default_rate) {
    return `${base} (${profile.vat_default_rate}%)`;
  }
  return base;
}

export type ProfileSummaryRow = { field: string; label: string; value: string };

export function profileSummaryRows(profile: OrganizationProfile): ProfileSummaryRow[] {
  const rows: ProfileSummaryRow[] = [
    { field: "org_form", label: orgProfileMissingLabel("org_form"), value: formatProfileValue("org_form", profile.org_form) },
    { field: "tax_system", label: orgProfileMissingLabel("tax_system"), value: formatProfileValue("tax_system", profile.tax_system) },
  ];
  if (profile.tax_system === "usn") {
    rows.push({
      field: "usn_tax_object",
      label: orgProfileMissingLabel("usn_tax_object"),
      value: formatProfileValue("usn_tax_object", profile.usn_tax_object),
    });
  }
  rows.push(
    { field: "vat_status", label: "НДС", value: formatVatAnswer(profile) },
    {
      field: "prices_include_vat",
      label: orgProfileMissingLabel("prices_include_vat"),
      value: formatProfileValue("prices_include_vat", profile.prices_include_vat),
    },
    {
      field: "accounting_source",
      label: orgProfileMissingLabel("accounting_source"),
      value: formatProfileValue("accounting_source", profile.accounting_source),
    },
    {
      field: "money_channels",
      label: orgProfileMissingLabel("money_channels"),
      value: formatMoneyChannels(profile.money_channels),
    },
    {
      field: "industry_sphere",
      label: "Сфера деятельности",
      value: formatProfileValue("industry_sphere", profile.industry_sphere),
    },
    {
      field: "month_close_policy",
      label: "Закрытие месяца",
      value: formatProfileValue("month_close_policy", profile.month_close_policy),
    },
    {
      field: "revenue_recognition_method",
      label: "Признание выручки",
      value: formatProfileValue("revenue_recognition_method", profile.revenue_recognition_method),
    },
  );
  return rows;
}
