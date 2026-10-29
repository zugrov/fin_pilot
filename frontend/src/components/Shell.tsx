import { NavLink, Link } from "react-router-dom";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { NAV_GROUPS } from "../lib/navigation";
import { NavIcon } from "./system/NavIcon";

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" fill="none">
      <path
        d="M3 5h14M3 10h14M3 15h14"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function NavGroups({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Основная навигация" className="flex flex-col gap-4">
      {NAV_GROUPS.map((group) => (
        <div key={group.title}>
          <p className="px-3 pb-1 text-note uppercase tracking-wide text-ink-subtle">
            {group.title}
          </p>
          <ul>
            {group.items.map((item) => (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    [
                      "flex min-h-tap items-center gap-2 rounded-control px-3 text-body",
                      isActive
                        ? "bg-brand-soft font-medium text-brand"
                        : "text-rail-text hover:bg-rail-hover hover:text-ink",
                    ].join(" ")
                  }
                >
                  <NavIcon name={item.icon} />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Logo() {
  return (
    <span className="flex items-center gap-2">
      <span
        aria-hidden="true"
        className="grid h-7 w-7 shrink-0 place-items-center rounded-control bg-brand text-body font-bold text-white"
      >
        F
      </span>
      <span className="text-lg font-semibold text-ink">FinPilot</span>
    </span>
  );
}

export function Shell({
  children,
  header,
  title,
}: {
  children: ReactNode;
  header?: ReactNode;
  /** Заголовок страницы: рендерится в шапке, чтобы действия периода стояли рядом. */
  title?: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#fp-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:text-body"
      >
        Перейти к содержимому
      </a>

      {/* Светлое боковое меню: только десктоп. */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col overflow-y-auto border-r border-line bg-surface px-2 py-4 lg:flex">
        <Link to="/overview" className="mb-6 px-3" aria-label="FinPilot, на главную">
          <Logo />
        </Link>
        <NavGroups />
      </aside>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 border-b border-line bg-surface">
          <div className="flex flex-wrap items-center gap-3 px-page py-3">
            <button
              type="button"
              className="flex min-h-tap min-w-tap items-center justify-center rounded-control border border-line lg:hidden"
              aria-expanded={menuOpen}
              aria-controls="fp-mobile-menu"
              aria-label="Меню"
              onClick={() => setMenuOpen((prev) => !prev)}
            >
              <MenuIcon />
            </button>
            <Link to="/overview" className="lg:hidden" aria-label="FinPilot, на главную">
              <Logo />
            </Link>
            {title ? <h1 className="text-title">{title}</h1> : null}
            <div className="ml-auto min-w-0 flex-1">{header}</div>
          </div>
        </header>

        {menuOpen ? (
          <>
            <button
              type="button"
              aria-label="Закрыть меню"
              className="fixed inset-0 z-40 bg-ink/40 lg:hidden"
              onClick={() => setMenuOpen(false)}
            />
            <div
              id="fp-mobile-menu"
              ref={panelRef}
              className="fixed inset-y-0 left-0 z-50 w-64 overflow-y-auto bg-surface px-2 py-4 shadow-pop lg:hidden"
            >
              <div className="mb-4 flex items-center justify-between px-3">
                <Logo />
                <button
                  type="button"
                  className="flex min-h-tap min-w-tap items-center justify-center rounded-control text-rail-text"
                  onClick={() => setMenuOpen(false)}
                  aria-label="Закрыть меню"
                >
                  ✕
                </button>
              </div>
              <NavGroups onNavigate={() => setMenuOpen(false)} />
            </div>
          </>
        ) : null}

        <main id="fp-main" className="mx-auto w-full max-w-6xl px-page py-page">
          <div className="min-w-0 break-words">{children}</div>
        </main>
      </div>
    </div>
  );
}
