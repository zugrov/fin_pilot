export type NavItem = { path: string; label: string };

export type NavGroup = { title: string; items: NavItem[] };

/**
 * Группы меню. Тексты ссылок менять нельзя: e2e ищут их по имени
 * (getByRole("link", { name: "…" })). Меняется только раскладка.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Деньги",
    items: [
      { path: "/overview", label: "Обзор" },
      { path: "/cashflow", label: "Деньги" },
      { path: "/receivables", label: "Дебиторка" },
      { path: "/wallets", label: "Кошельки" },
    ],
  },
  {
    title: "План",
    items: [
      { path: "/sales", label: "Продажи" },
      { path: "/calendar", label: "Календарь" },
      { path: "/forecast", label: "Прогноз" },
      { path: "/budgets", label: "Бюджет" },
    ],
  },
  {
    title: "Данные",
    items: [
      { path: "/import", label: "Импорт" },
      { path: "/classification", label: "Классификация" },
    ],
  },
  {
    title: "Прочее",
    items: [
      { path: "/alerts", label: "Алерты" },
      { path: "/telegram", label: "Telegram" },
      { path: "/billing", label: "Тариф" },
    ],
  },
];

export function allNavItems(): NavItem[] {
  return NAV_GROUPS.flatMap((group) => group.items);
}
