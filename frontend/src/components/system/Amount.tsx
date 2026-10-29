import { MISSING_VALUE, formatMoney } from "../../lib/money";

export type AmountTone = "auto" | "neutral";

type Props = {
  /** Денежная строка из API. null → «Нет данных», а не нуль. */
  value: string | null | undefined;
  /** auto: отрицательные красным; neutral: всегда обычным цветом. */
  tone?: AmountTone;
  /** Подпись вместо «Нет данных». */
  missing?: string;
  /** Размер: обычный в таблицах, крупный в карточках показателей. */
  size?: "body" | "kpi" | "note";
  /** Выравнивание. В таблицах суммы всегда справа. */
  align?: "left" | "right";
  className?: string;
  /** Имя для e2e: сырое значение доступно как data-value. */
  testId?: string;
};

/** Единственное место, где форматируются и раскрашиваются суммы. */
export function Amount({
  value,
  tone = "auto",
  missing = MISSING_VALUE,
  size = "body",
  align = "right",
  className = "",
  testId,
}: Props) {
  const text = formatMoney(value, missing);
  const isMissing = text === missing;
  const isNegative = !isMissing && text.startsWith("\u2212");
  const negativeTone = tone === "auto" && isNegative;

  const sizeClass =
    size === "kpi" ? "text-kpi" : size === "note" ? "text-note text-ink-subtle" : "text-body";
  const alignClass = align === "right" ? "text-right" : "text-left";
  const toneClass = negativeTone ? "text-outflow" : isMissing ? "text-ink-subtle" : "";

  return (
    <span
      className={`fp-num ${sizeClass} ${alignClass} ${toneClass} ${className}`.trim()}
      data-testid={testId}
      data-value={value ?? ""}
    >
      {text}
    </span>
  );
}
