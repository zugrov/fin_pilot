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
