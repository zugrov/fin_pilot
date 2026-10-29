import type { NavIconName } from "../components/system/NavIcon";

export type NavItem = { path: string; label: string; icon: NavIconName };

export type NavGroup = { title: string; items: NavItem[] };

/**
 * Группы меню. Тексты ссылок менять нельзя: e2e ищут их по имени
 * (getByRole("link", { name: "…" })). Меняется только раскладка.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Деньги",
    items: [
      { path: "/overview", label: "Обзор", icon: "gauge" },
      { path: "/cashflow", label: "Деньги", icon: "coins" },
      { path: "/receivables", label: "Дебиторка", icon: "clock" },
      { path: "/wallets", label: "Кошельки", icon: "wallet" },
    ],
  },
  {
    title: "План",
    items: [
      { path: "/sales", label: "Продажи", icon: "chart" },
      { path: "/calendar", label: "Календарь", icon: "calendar" },
      { path: "/forecast", label: "Прогноз", icon: "trend" },
      { path: "/budgets", label: "Бюджет", icon: "target" },
    ],
  },
  {
    title: "Данные",
    items: [
      { path: "/import", label: "Импорт", icon: "upload" },
      { path: "/classification", label: "Классификация", icon: "tags" },
    ],
  },
  {
    title: "Прочее",
    items: [
      { path: "/alerts", label: "Алерты", icon: "bell" },
      { path: "/telegram", label: "Telegram", icon: "send" },
      { path: "/billing", label: "Тариф", icon: "card" },
    ],
  },
];

export function allNavItems(): NavItem[] {
  return NAV_GROUPS.flatMap((group) => group.items);
}
