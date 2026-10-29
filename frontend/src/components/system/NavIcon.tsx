import type { JSX } from "react";

export type NavIconName =
  | "gauge"
  | "coins"
  | "clock"
  | "wallet"
  | "chart"
  | "calendar"
  | "trend"
  | "target"
  | "upload"
  | "tags"
  | "bell"
  | "send"
  | "card";

/** Контуры иконок 24x24: тонкие штрихи, читаются и в меню 240px, и на мобильном. */
const PATHS: Record<NavIconName, JSX.Element> = {
  gauge: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 12l4-4" />
      <path d="M7 12h.01M12 7v.01M17 12h.01" />
    </>
  ),
  coins: (
    <>
      <ellipse cx="9" cy="7" rx="6" ry="3" />
      <path d="M3 7v4c0 1.66 2.69 3 6 3s6-1.34 6-3V7" />
      <path d="M9 14v3c0 1.66 2.69 3 6 3s6-1.34 6-3v-4" />
      <path d="M15 10v4c0 1.66 2.69 3 6 3" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 3" />
    </>
  ),
  wallet: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
      <path d="M16 15h2" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V4" />
      <path d="M4 20h16" />
      <path d="M8 16v-5M13 16V8M18 16v-3" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 10h16M8 3v4M16 3v4" />
    </>
  ),
  trend: (
    <>
      <path d="M3 17l6-6 4 4 7-8" />
      <path d="M14 7h6v6" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
    </>
  ),
  tags: (
    <>
      <path d="M3 11V4a1 1 0 0 1 1-1h7l10 10-8 8L3 11z" />
      <path d="M7 7h.01" />
    </>
  ),
  bell: (
    <>
      <path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </>
  ),
  send: (
    <>
      <path d="M21 3L10 14" />
      <path d="M21 3l-7 18-4-7-7-4 18-7z" />
    </>
  ),
  card: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18" />
      <path d="M7 15h4" />
    </>
  ),
};

/** Иконка пункта меню. Декоративная: aria-hidden, смысл несёт текст ссылки. */
export function NavIcon({ name }: { name: NavIconName }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      {PATHS[name]}
    </svg>
  );
}
