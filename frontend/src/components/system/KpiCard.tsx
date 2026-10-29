import type { ReactNode } from "react";

import { Amount } from "./Amount";
import { StatusChip, type ChipTone } from "./StatusChip";

type Props = {
  /** Заголовок-роль показателя: «Деньги на счетах», «Дебиторка». */
  title: string;
  /** Значение показателя. null → «Нет данных». */
  value: string | null | undefined;
  /** Подпись под значением: период, пояснение. */
  caption?: string;
  /** Тон акцента: подкрашивает левую полосу и значение. */
  tone?: "neutral" | "inflow" | "outflow" | "warn" | "info";
  /** Всегда видимые второстепенные строки (проверяются e2e). */
  meta?: ReactNode;
  /** Подробности: свёрнуты в «Подробнее», чтобы карточка не росла. */
  detail?: ReactNode;
  /** Чип статуса в шапке карточки. */
  chip?: { label: string; tone: ChipTone };
  /** Ссылка или кнопка внизу. */
  action?: ReactNode;
  /** Дополнительное пояснение (мелким шрифтом). */
  hint?: string;
  /** Идентификатор значения для e2e. */
  testId?: string;
  /** Непустое значение не в рублях (например, число операций). */
  valueText?: string | null;
};

const TONE_ACCENT: Record<NonNullable<Props["tone"]>, string> = {
  neutral: "border-l-line",
  inflow: "border-l-inflow",
  outflow: "border-l-outflow",
  warn: "border-l-warn",
  info: "border-l-info",
};

/**
 * Карточка показателя. Значение всегда через Amount: табличные цифры,
 * «Нет данных» вместо нуля, минус U+2212.
 */
export function KpiCard({
  title,
  value,
  caption,
  tone = "neutral",
  meta,
  detail,
  chip,
  action,
  hint,
  testId,
  valueText,
}: Props) {
  return (
    <section
      className={`flex h-full flex-col rounded-card border border-line border-l-4 bg-surface p-card shadow-card ${TONE_ACCENT[tone]}`}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-label text-ink-muted">{title}</h2>
        {chip ? <StatusChip tone={chip.tone}>{chip.label}</StatusChip> : null}
      </div>
      <p className="mt-1">
        {valueText ? (
          <span className="fp-num text-kpi" data-testid={testId}>
            {valueText}
          </span>
        ) : (
          <Amount value={value} size="kpi" align="left" testId={testId} />
        )}
      </p>
      {caption ? <p className="mt-0.5 text-note text-ink-muted">{caption}</p> : null}
      {meta ? <div className="mt-1 text-note text-ink-muted">{meta}</div> : null}
      {/* Пункт а: подробности свёрнуты, чтобы карточка оставалась компактной. */}
      {detail ? (
        <details className="mt-auto pt-2 text-body text-ink-muted">
          <summary className="cursor-pointer text-note text-ink-muted marker:text-ink-subtle">
            Подробнее
          </summary>
          <div className="mt-1">{detail}</div>
        </details>
      ) : null}
      {hint ? <p className="mt-2 text-note text-ink-subtle">{hint}</p> : null}
      {action ? <div className="mt-2 text-body">{action}</div> : null}
    </section>
  );
}
