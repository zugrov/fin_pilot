export function canPreview(status: string): boolean {
  return status === "active";
}

export function bindingCaption(status: string): string {
  if (status === "pending") {
    return "Ожидает подтверждения на сайте";
  }
  if (status === "active") {
    return "Привязка активна";
  }
  if (status === "revoked") {
    return "Привязка отозвана";
  }
  return "нет привязки";
}

export function tokenNotice(): string {
  return "Токен не содержит финансовых данных.";
}
