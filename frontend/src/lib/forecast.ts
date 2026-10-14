export function gapDisplay(amount: string | null, status: string): string {
  if (status === "preliminary" || amount === null) {
    return "Нет данных о прогнозе";
  }
  if (amount === "0.00") {
    return "Дефицита в горизонте нет";
  }
  return `Дефицит: ${amount}`;
}
