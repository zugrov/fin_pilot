import type { ReactNode } from "react";

export type ChipTone = "ok" | "warn" | "danger" | "neutral" | "unavailable";

const TONE_CLASS: Record<ChipTone, string> = {
  ok: "border-inflow-line bg-inflow-soft text-inflow",
  warn: "border-warn-line bg-warn-soft text-warn",
  danger: "border-danger-line bg-danger-soft text-danger",
  neutral: "border-line bg-canvas text-ink",
  unavailable: "border-line bg-canvas text-ink-subtle",
};

type Props = {
  /** Слово статуса — обязательно: цвет дополняет, но не заменяет его. */
  children: ReactNode;
  tone?: ChipTone;
  /** Для динамических статусов: скринридер объявит изменение. */
  live?: boolean;
};

export function StatusChip({ children, tone = "neutral", live = false }: Props) {
  return (
    <span
      className={`inline-flex min-h-[24px] items-center rounded-full border px-2 text-note ${TONE_CLASS[tone]}`}
      role={live ? "status" : undefined}
    >
      {children}
    </span>
  );
}
