export function mailboxCaption(source: { type?: string } | null | undefined): string {
  if (source == null || source.type !== "email") {
    return "Почтового ящика нет";
  }
  return "Почтовый ящик";
}

export function coverageCaption(coverage: string | null | undefined): string {
  if (!coverage) {
    return "Покрытие нет данных";
  }
  return `Покрытие ${coverage}`;
}

export function showsMailboxSecret(payload: {
  password?: string;
  encrypted_credentials?: string;
}): boolean {
  return Boolean(payload.password || payload.encrypted_credentials);
}

export function pollResultCaption(message: string): string {
  if (message === "Опрос почты выключен") {
    return message;
  }
  return "Вход проверен, письма не сохранены";
}
