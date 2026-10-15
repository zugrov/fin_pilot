export function yearPayLabel(annualPayable: string): string {
  const amount = annualPayable.trim();
  if (!/^\d+\.\d{2}$/.test(amount)) {
    throw new Error("сумма должна прийти с сервера");
  }
  const [rubles, kopecks] = amount.split(".");
  const shown = kopecks === "00" ? rubles : amount;
  return `Оплатить год — ${shown} ₽`;
}

export function renewPayLabel(amount: string, interval: "month" | "year"): string {
  const paid = interval === "year" ? yearPayLabel(amount) : monthPayLabel(amount);
  const period = interval === "year" ? "год" : "месяц";
  const price = paid.split("—")[1]?.trim();
  if (!price) {
    throw new Error("сумма должна прийти с сервера");
  }
  return `Продлить подписку на ${period} — ${price}`;
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
