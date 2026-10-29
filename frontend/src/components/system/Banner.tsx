import type { ReactNode } from "react";

export type BannerTone = "warn" | "danger" | "info";

const TONE: Record<BannerTone, { wrap: string; title: string }> = {
  warn: {
    wrap: "border-warn-line bg-warn-soft text-warn",
    title: "Внимание",
  },
  danger: {
    wrap: "border-danger-line bg-danger-soft text-danger",
    title: "Ошибка",
  },
  info: {
    wrap: "border-info-line bg-info-soft text-info",
    title: "Справка",
  },
};

type Props = {
  tone?: BannerTone;
  /** Слово-маркер статуса: смысл не должен держаться только на цвете. */
  label?: string;
  children: ReactNode;
  action?: ReactNode;
};

export function Banner({ tone = "warn", label, children, action }: Props) {
  const style = TONE[tone];
  return (
    <div
      className={`rounded-card border p-card text-body ${style.wrap}`}
      role={tone === "danger" ? "alert" : "status"}
    >
      <p className="mb-1 font-medium">{label ?? style.title}</p>
      <div>{children}</div>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
