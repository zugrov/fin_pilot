export const ORG_PROFILE_API_MESSAGES: Record<string, string> = {
  profile_validation_failed: "Проверьте выделенные поля. Данные не сохранены.",
  profile_confirm_incomplete: "Не хватает данных для подтверждения. Заполните поля из списка ниже.",
  profile_version_immutable:
    "Эта версия уже подтверждена и не редактируется. Создайте новую версию с даты изменения.",
  already_confirmed: "Версия уже подтверждена.",
  not_latest_version: "Редактировать или подтверждать можно только последнюю версию профиля.",
  draft_exists: "Сначала завершите или подтвердите текущий черновик.",
  effective_from_not_after_latest:
    "Дата новой версии должна быть позже предыдущей подтверждённой.",
  profile_version_conflict: "Версия с такой датой уже существует.",
  forbidden: "Недостаточно прав. Изменять профиль могут владелец и бухгалтер.",
  email_not_verified: "Подтвердите электронную почту, чтобы сохранять профиль.",
  csrf: "Сессия устарела. Обновите страницу и войдите снова.",
  idempotency_conflict: "Повторите действие с новым ключом запроса.",
  not_found: "Организация или версия профиля не найдена.",
  conflict: "Этот ИНН уже указан у другой организации в вашем пространстве. Проверьте ИНН или обратитесь к владельцу.",
};

export const ORG_PROFILE_FIELD_ERROR_MESSAGES: Record<string, string> = {
  invalid_value: "Выберите значение из списка.",
  special_rates_requires_usn: "Спец. ставки НДС 5/7% применимы только при УСН.",
  regime_requires_ip: "Выбранный режим налогообложения доступен только для ИП.",
  ooo_incompatible_with_ip_regime: "Для ООО этот режим недоступен.",
  with_deductions_requires_vat_payer: "Вычеты по НДС указывают только плательщики НДС.",
  special_without_requires_special_rates: "Режим без вычетов — только при спец. ставках 5/7%.",
  only_for_exemption: "Признак ст. 145 — только при статусе «освобождение».",
  incompatible_with_deductions: "Освобождение по ст. 145 несовместимо с вычетами по НДС.",
  only_for_vat_payer: "Ставка НДС по умолчанию — только для плательщика НДС.",
  invalid_rate: "Недопустимая ставка НДС.",
  only_for_usn: "Объект УСН заполняется только при системе УСН.",
  must_be_empty_for_new_org: "Для новой организации диапазон выручки прошлого года не указывают.",
  inn_not_digits: "ИНН должен состоять только из цифр.",
  inn_invalid_length: "ИНН: 10 цифр для организации или 12 для ИП.",
  inn_checksum_mismatch: "Не сходится контрольная сумма ИНН. Проверьте ввод.",
};

export const ORG_PROFILE_SUPPORT_MESSAGES: Record<string, string> = {
  tax_system_not_supported:
    "Текущая версия FinPilot не поддерживает выбранную систему налогообложения. Укажите УСН или ОСНО либо обратитесь в поддержку.",
  osno_book_csv_unsupported: "Для ОСНО нужна полноценная бухгалтерская выгрузка, а не книга/CSV.",
  org_form_unspecified: "Укажите организационно-правовую форму.",
  org_form_limited_support: "Для выбранной формы поддержка ограничена.",
  tax_system_unspecified: "Укажите систему налогообложения.",
  tax_system_limited_support: "Режим требует уточнения совместимости с продуктом.",
  accounting_source_unspecified: "Укажите источник учёта.",
  cloud_export_required: "Для облачной бухгалтерии нужна выгрузка в согласованном формате.",
  book_csv_limited: "Книга/CSV подходит для упрощённого контура; полная ОПиУ может быть недоступна.",
  osno_limited_vat: "При ОСНО блок НДС с вычетами в продукте ограничен на раннем этапе.",
};

const FIELD_LABELS: Record<string, string> = {
  org_form: "Организационно-правовая форма",
  tax_system: "Система налогообложения",
  usn_tax_object: "Объект УСН",
  vat_status: "НДС",
  vat_default_rate: "Ставка НДС",
  prices_include_vat: "Цены с НДС",
  prior_year_revenue_band: "Выручка прошлого года",
  accounting_source: "Источник учёта",
  money_channels: "Каналы денег",
  inn: "ИНН",
};

export function orgProfileApiMessage(code: string, fallback?: string): string {
  return ORG_PROFILE_API_MESSAGES[code] ?? fallback ?? "Не удалось сохранить профиль.";
}

export function orgProfileFieldMessage(field: string, code: string): string {
  if (code === "_confirm_minimum") {
    return `Укажите: ${FIELD_LABELS[field] ?? field}.`;
  }
  return ORG_PROFILE_FIELD_ERROR_MESSAGES[code] ?? "Проверьте поле.";
}

export function orgProfileSupportBanner(code: string | null | undefined): string | null {
  if (!code) {
    return null;
  }
  return ORG_PROFILE_SUPPORT_MESSAGES[code] ?? "Поддержка профиля ограничена — уточните настройки.";
}

export function orgProfileMissingLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
