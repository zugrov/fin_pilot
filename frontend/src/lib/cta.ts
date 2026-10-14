export function yearPayLabel(annualPayable: string): string {
  const amount = annualPayable.trim();
  if (!/^\d+\.\d{2}$/.test(amount)) {
    throw new Error("сумма должна прийти с сервера");
  }
  const [rubles, kopecks] = amount.split(".");
  const shown = kopecks === "00" ? rubles : amount;
  return `Оплатить год — ${shown} ₽`;
}

export function monthPayLabel(monthly: string): string {
  const amount = monthly.trim();
  if (!/^\d+\.\d{2}$/.test(amount)) {
    throw new Error("сумма должна прийти с сервера");
  }
  const [rubles, kopecks] = amount.split(".");
  const shown = kopecks === "00" ? rubles : amount;
  return `Оплатить месяц — ${shown} ₽`;
}
