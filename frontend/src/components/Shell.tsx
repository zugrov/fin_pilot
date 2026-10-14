import { Link } from "react-router-dom";
import type { ReactNode } from "react";

const LINKS = [
  ["/overview", "Обзор"],
  ["/wallets", "Кошельки"],
  ["/sales", "Продажи"],
  ["/calendar", "Календарь"],
  ["/forecast", "Прогноз"],
  ["/import", "Импорт"],
  ["/billing", "Тариф"],
] as const;

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto min-h-screen w-full max-w-5xl px-4 py-6">
      <nav className="mb-6 flex flex-wrap gap-4 text-sm">
        {LINKS.map(([path, label]) => (
          <Link key={path} to={path}>
            {label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
