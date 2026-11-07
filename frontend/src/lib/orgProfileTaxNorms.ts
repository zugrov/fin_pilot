export type TaxNormValues = {
  usn_vat_exemption_threshold_rub?: string;
  computed_special_cap_5_rub?: string;
  computed_special_cap_7_rub?: string;
};

function formatRub(amount: string | undefined): string {
  if (!amount) {
    return "—";
  }
  const num = Number(amount);
  if (Number.isNaN(num)) {
    return amount;
  }
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(num);
}

export function priorYearBandLabels(values: TaxNormValues): Record<string, string> {
  const threshold = formatRub(values.usn_vat_exemption_threshold_rub);
  const cap5 = formatRub(values.computed_special_cap_5_rub);
  const cap7 = formatRub(values.computed_special_cap_7_rub);
  return {
    under_exemption_threshold: `До ${threshold} ₽`,
    from_threshold_to_cap_5: `От ${threshold} до ${cap5} ₽`,
    from_cap_5_to_cap_7: `От ${cap5} до ${cap7} ₽`,
    over_cap_7: `Свыше ${cap7} ₽`,
  };
}

export function formatThresholdLine(values: TaxNormValues): string {
  const threshold = formatRub(values.usn_vat_exemption_threshold_rub);
  return `Порог освобождения от обязанности по НДС при УСН: ${threshold} ₽ (по справочнику на выбранную дату).`;
}
