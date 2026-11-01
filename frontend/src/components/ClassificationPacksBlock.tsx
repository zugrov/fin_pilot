import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  applyPack,
  disablePack,
  installPack,
  listPackCatalog,
  loadPackStatus,
  type PackCatalogEntry,
  type PackPreview,
  type PackStatus,
  previewPack,
} from "../api";

type Props = {
  companyId: string;
  canWrite: boolean;
  dateFrom: string;
  dateTo: string;
};

function statusLine(entry: PackStatus): string {
  if (!entry.installed) return "Не установлен";
  if (entry.disabled) return "Установлен, отключён";
  return `Установлен: активно правил ${entry.enabled_rule_count} из ${entry.rule_count}`;
}

export function ClassificationPacksBlock({ companyId, canWrite, dateFrom, dateTo }: Props) {
  const client = useQueryClient();
  const [preview, setPreview] = useState<{ key: string; body: PackPreview } | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [disableTarget, setDisableTarget] = useState<{ slug: string; version: string } | null>(
    null,
  );

  const catalog = useQuery({ queryKey: ["pack-catalog"], queryFn: listPackCatalog });
  const status = useQuery({
    queryKey: ["pack-status", companyId],
    queryFn: () => loadPackStatus(companyId),
    enabled: Boolean(companyId),
  });

  const statusFor = (entry: PackCatalogEntry, version: string): PackStatus | null =>
    status.data?.installed.find((row) => row.pack === entry.slug && row.version === version) ??
    null;

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["pack-status", companyId] });
    await client.invalidateQueries({ queryKey: ["rules", companyId] });
    await client.invalidateQueries({ queryKey: ["unclassified-summary", companyId] });
  };

  const runPreview = useMutation({
    mutationFn: (args: { slug: string; version: string }) =>
      previewPack(companyId, args.slug, args.version, dateFrom, dateTo),
    onSuccess: (body, args) => {
      setPreview({ key: `${args.slug}@${args.version}`, body });
      setError("");
      setMessage("");
    },
    onError: () => setError("Не удалось построить предпросмотр. Проверьте период и повторите."),
  });

  const runInstall = useMutation({
    mutationFn: (args: { slug: string; version: string }) =>
      installPack(companyId, args.slug, args.version),
    onSuccess: async (body) => {
      setError("");
      setMessage(`Установлено правил: ${body.created.length}.`);
      await refresh();
    },
    onError: () => setError("Не удалось установить набор. Повторите позже."),
  });

  const runApply = useMutation({
    mutationFn: (args: { slug: string; version: string }) =>
      applyPack(companyId, args.slug, args.version),
    onSuccess: async (body) => {
      setError("");
      setMessage(`Размечено операций: ${body.applied}.`);
      await refresh();
    },
    onError: () => setError("Не удалось применить набор."),
  });

  const runDisable = useMutation({
    mutationFn: (args: { slug: string; version: string }) =>
      disablePack(companyId, args.slug, args.version),
    onSuccess: async (body) => {
      setError("");
      setMessage(`Отключено правил: ${body.disabled_rule_ids.length}.`);
      await refresh();
    },
    onError: () => setError("Не удалось отключить набор."),
  });

  const busy =
    runPreview.isPending || runInstall.isPending || runApply.isPending || runDisable.isPending;

  if (catalog.isLoading) {
    return <p className="text-sm text-ink-muted">Загрузка наборов правил…</p>;
  }
  if (catalog.isError) {
    return <p className="text-sm text-danger">Не удалось загрузить наборы правил.</p>;
  }
  if (!catalog.data || catalog.data.packs.length === 0) {
    return <p className="text-sm text-ink-muted">Доступных наборов нет.</p>;
  }

  return (
    <div data-testid="packs-block">
      <p className="mb-3 text-sm text-ink-muted">
        Наборы правил размечивают операции пачкой. Установка не меняет категории, пока набор не
        применён.
      </p>
      {message ? <p className="mb-3 text-sm text-ink">{message}</p> : null}
      {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
      <ul className="space-y-3">
        {catalog.data.packs.map((entry) => {
          const current = statusFor(entry, entry.latest_version);
          const previewKey = `${entry.slug}@${entry.latest_version}`;
          return (
            <li key={entry.slug} className="rounded-control border border-line p-3">
              <p className="font-medium">{entry.display_name}</p>
              <p className="text-note text-ink-muted">
                {entry.slug} · версия {entry.latest_version} · правил {entry.rule_count}
              </p>
              <p className="text-note text-ink-muted">
                {current ? statusLine(current) : "Не установлен"}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="min-h-tap rounded-control border border-line px-3 text-note"
                  disabled={busy}
                  onClick={() =>
                    runPreview.mutate({ slug: entry.slug, version: entry.latest_version })
                  }
                >
                  Предпросмотр
                </button>
                <button
                  type="button"
                  className="min-h-tap rounded-control border border-line px-3 text-note"
                  disabled={!canWrite || busy || Boolean(current?.installed)}
                  onClick={() =>
                    runInstall.mutate({ slug: entry.slug, version: entry.latest_version })
                  }
                >
                  Установить
                </button>
                <button
                  type="button"
                  className="min-h-tap rounded-control border border-line px-3 text-note"
                  disabled={!canWrite || busy || !current?.installed}
                  onClick={() =>
                    runApply.mutate({ slug: entry.slug, version: entry.latest_version })
                  }
                >
                  Применить
                </button>
                <button
                  type="button"
                  className="min-h-tap rounded-control border border-line px-3 text-note"
                  disabled={!canWrite || busy || !current?.installed}
                  onClick={() =>
                    setDisableTarget({ slug: entry.slug, version: entry.latest_version })
                  }
                >
                  Отключить
                </button>
              </div>
              {preview && preview.key === previewKey ? (
                <div className="mt-3 text-sm">
                  <p className="text-ink-muted">
                    Операций в периоде: {preview.body.transaction_count}. Без категории после
                    набора: {preview.body.unmapped_count}.
                  </p>
                  <ul className="mt-1">
                    {preview.body.sections
                      .filter((sec) => sec.in !== "0.00" || sec.out !== "0.00")
                      .map((sec) => (
                        <li key={sec.code} className="fp-num">
                          {sec.code}: поступило {sec.in} ₽, списано {sec.out} ₽
                        </li>
                      ))}
                  </ul>
                  {preview.body.intersections_with_existing.length > 0 ? (
                    <p className="mt-2 text-warn">
                      Пересечений с вашими правилами:{" "}
                      {preview.body.intersections_with_existing.length}. Побеждает правило с
                      меньшим номером приоритета.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {disableTarget ? (
        <div
          className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
        >
          <div className="max-w-md rounded-card bg-white p-4 text-sm shadow-lg">
            <h3 className="mb-2 text-lg font-semibold">Отключить набор?</h3>
            <p className="mb-4 text-ink-muted">
              Отключение набора не снимает категории, уже проставленные операциям.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="min-h-tap rounded-control border border-line px-3"
                disabled={busy}
                onClick={() => setDisableTarget(null)}
              >
                Отмена
              </button>
              <button
                type="button"
                className="min-h-tap rounded-control bg-brand px-3 text-white disabled:opacity-50"
                disabled={busy}
                onClick={() => {
                  runDisable.mutate(disableTarget);
                  setDisableTarget(null);
                }}
              >
                Отключить
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
