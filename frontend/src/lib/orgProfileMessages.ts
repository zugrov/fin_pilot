const API_MESSAGES: Record<string, string> = {
  profile_validation_failed: "Проверьте выделенные поля. Данные не сохранены.",
  profile_confirm_incomplete: "Не хватает данных для подтверждения.",
  profile_version_immutable:
    "Эта версия уже подтверждена. Создайте новую версию с даты изменения.",
  already_confirmed: "Версия уже подтверждена.",
  not_latest_version: "Редактировать можно только последнюю версию профиля.",
  forbidden: "Недостаточно прав. Изменять профиль могут владелец и бухгалтер.",
  email_not_verified: "Подтвердите электронную почту, чтобы сохранять профиль.",
  csrf: "Сессия устарела. Обновите страницу и войдите снова.",
  idempotency_conflict: "Повторите действие с новым ключом запроса.",
  conflict: "Этот ИНН уже указан у другой организации в вашем пространстве.",
  not_found: "Организация или версия профиля не найдена.",
};

const FIELD_CODES: Record<string, string> = {
  invalid_value: "Выберите значение из списка.",
  special_rates_requires_usn: "Спец. ставки НДС 5/7% применимы только при УСН.",
  regime_requires_ip: "Выбранный режим доступен только для ИП.",
  ooo_incompatible_with_ip_regime: "Для ООО этот режим недоступен.",
  with_deductions_requires_vat_payer: "Вычеты по НДС указывают только плательщики НДС.",
  inn_not_digits: "ИНН должен состоять только из цифр.",
  inn_invalid_length: "ИНН: 10 цифр для организации или 12 для ИП.",
  inn_checksum_mismatch: "Не сходится контрольная сумма ИНН. Проверьте ввод.",
};

const SUPPORT_BANNERS: Record<string, string> = {
  tax_system_not_supported:
    "Текущая версия FinPilot не поддерживает выбранную систему налогообложения.",
  osno_book_csv_unsupported: "Для ОСНО нужна полноценная бухгалтерская выгрузка.",
  org_form_unspecified: "Укажите организационно-правовую форму.",
  cloud_export_required: "Для облачной бухгалтерии нужна выгрузка в согласованном формате.",
};

const FIELD_LABELS: Record<string, string> = {
  org_form: "Организационно-правовая форма",
  tax_system: "Система налогообложения",
  usn_tax_object: "Объект УСН",
  vat_status: "НДС",
  accounting_source: "Источник учёта",
  money_channels: "Каналы денег",
};

export function orgProfileApiMessage(code: string, fallback?: string): string {
  return API_MESSAGES[code] ?? fallback ?? "Не удалось сохранить профиль.";
}

export function orgProfileFieldMessage(field: string, code: string): string {
  if (code === "_confirm_minimum") {
    return `Укажите: ${FIELD_LABELS[field] ?? field}.`;
  }
  return FIELD_CODES[code] ?? "Проверьте поле.";
}

export function orgProfileSupportBanner(code: string | null | undefined): string | null {
  if (!code) {
    return null;
  }
  return SUPPORT_BANNERS[code] ?? "Поддержка профиля ограничена — уточните настройки.";
}

export function orgProfileMissingLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
