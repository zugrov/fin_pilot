import type { ReactNode } from "react";

type Props = {
  title: string;
  /** Объяснение простыми словами: почему тут пусто и что это значит. */
  description: string;
  /** Обязательное действие: пустое состояние без выхода — тупик. */
  action?: ReactNode;
  tone?: "neutral" | "warn";
};

export function EmptyState({ title, description, action, tone = "neutral" }: Props) {
  const border = tone === "warn" ? "border-warn-line bg-warn-soft" : "border-line bg-surface";
  return (
    <section className={`rounded-card border p-card ${border}`}>
      <p className="text-body font-medium">{title}</p>
      <p className="mt-1 text-body text-ink-muted">{description}</p>
      {action ? <div className="mt-3">{action}</div> : null}
    </section>
  );
}
