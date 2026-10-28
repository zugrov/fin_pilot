import { Link } from "react-router-dom";
import type { ReactNode } from "react";

const LINKS = [
  ["/overview", "Обзор"],
  ["/cashflow", "Деньги"],
  ["/wallets", "Кошельки"],
  ["/sales", "Продажи"],
  ["/calendar", "Календарь"],
  ["/classification", "Классификация"],
  ["/forecast", "Прогноз"],
  ["/budgets", "Бюджет"],
  ["/alerts", "Алерты"],
  ["/import", "Импорт"],
  ["/telegram", "Telegram"],
  ["/billing", "Тариф"],
] as const;

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto min-h-screen w-full max-w-5xl px-4 py-6">
      <nav className="mb-6 flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {LINKS.map(([path, label]) => (
          <Link key={path} to={path}>
            {label}
          </Link>
        ))}
      </nav>
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}
