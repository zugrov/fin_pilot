import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  confirmBinding,
  createLinkToken,
  listCompanies,
  loadBinding,
  loadSubscription,
  previewDigest,
  saveSubscription,
  unlinkBinding,
  type TelegramSubscription,
} from "../api";
import { Shell } from "../components/Shell";
import { bindingCaption, canPreview, tokenNotice } from "../lib/telegram";

export function TelegramPage() {
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const binding = useQuery({
    queryKey: ["telegram-binding"],
    queryFn: loadBinding,
    enabled: Boolean(companies.data),
  });
  const status = binding.data?.status ?? "";
  const subscription = useQuery({
    queryKey: ["telegram-subscription"],
    queryFn: loadSubscription,
    enabled: canPreview(status),
  });
  const preview = useQuery({
    queryKey: ["telegram-preview"],
    queryFn: previewDigest,
    enabled: canPreview(status),
  });
  const issue = useMutation({ mutationFn: createLinkToken });
  const confirm = useMutation({
    mutationFn: confirmBinding,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["telegram-binding"] });
    },
  });
  const unlink = useMutation({
    mutationFn: unlinkBinding,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["telegram-binding"] });
      await client.invalidateQueries({ queryKey: ["telegram-subscription"] });
      await client.invalidateQueries({ queryKey: ["telegram-preview"] });
    },
  });

  const isLoading = companies.isLoading || (Boolean(companies.data) && binding.isLoading);
  const isError = companies.isError || binding.isError;
  const isEmpty = binding.data?.status === "none" && issue.data === undefined;

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Telegram</h1>
      {isLoading ? <p>Загрузка</p> : null}
      {isError ? <p className="text-red-700">Не удалось загрузить привязку.</p> : null}
      {isEmpty ? <p className="mb-3 text-sm text-slate-600">{bindingCaption("none")}</p> : null}
      {binding.data && binding.data.status !== "none" ? (
        <p className="mb-3 text-sm">{bindingCaption(binding.data.status)}</p>
      ) : null}
      <button
        type="button"
        className="rounded border px-3 py-2"
        onClick={() => issue.mutate()}
      >
        Получить токен
      </button>
      {issue.isError ? <p className="mt-2 text-red-700">Токен не выпущен.</p> : null}
      {issue.data ? (
        <section className="mt-4 max-w-full rounded-xl border bg-white p-4">
          <p className="text-sm">{tokenNotice()}</p>
          <p className="mt-2 break-all font-mono text-sm">{issue.data.token}</p>
          <p className="mt-2 text-sm text-slate-600">Действует до {issue.data.expires_at}</p>
          {issue.data.deep_link ? (
            <p className="mt-2 break-all text-sm">{issue.data.deep_link}</p>
          ) : null}
        </section>
      ) : null}
      {status === "pending" ? (
        <button
          type="button"
          className="mt-4 rounded border px-3 py-2"
          onClick={() => confirm.mutate()}
        >
          Подтвердить привязку
        </button>
      ) : null}
      {status === "active" || status === "pending" ? (
        <button
          type="button"
          className="mt-4 ml-3 rounded border px-3 py-2"
          onClick={() => unlink.mutate()}
        >
          Отвязать
        </button>
      ) : null}
      {confirm.isError ? (
        <p className="mt-2 text-red-700">Привязку не удалось подтвердить.</p>
      ) : null}
      {subscription.data ? (
        <SubscriptionForm
          value={subscription.data}
          onSaved={() => {
            void client.invalidateQueries({ queryKey: ["telegram-subscription"] });
            void client.invalidateQueries({ queryKey: ["telegram-preview"] });
          }}
        />
      ) : null}
      {canPreview(status) && preview.isLoading ? (
        <p className="mt-4">Загрузка предпросмотра</p>
      ) : null}
      {canPreview(status) && preview.isError ? (
        <p className="mt-4 text-red-700">Предпросмотр недоступен.</p>
      ) : null}
      {preview.data ? (
        <section className="mt-4 max-w-full rounded-xl border bg-white p-4">
          <p className="mb-2 text-sm text-slate-600">
            Предпросмотр. Сообщение в Telegram не отправлено.
          </p>
          <pre className="whitespace-pre-wrap break-words text-sm">{preview.data.text}</pre>
        </section>
      ) : null}
    </Shell>
  );
}

function SubscriptionForm({
  value,
  onSaved,
}: {
  value: TelegramSubscription;
  onSaved: () => void;
}) {
  const [localTime, setLocalTime] = useState(value.local_time);
  const [timezone, setTimezone] = useState(value.timezone);
  const [mode, setMode] = useState(value.mode);
  const [privacy, setPrivacy] = useState(value.privacy_level);
  const [enabled, setEnabled] = useState(value.enabled);
  const [instant, setInstant] = useState(value.instant_alerts);
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () =>
      saveSubscription({
        local_time: localTime,
        timezone,
        days_of_week: value.days_of_week,
        mode,
        enabled,
        instant_alerts: instant,
        privacy_level: privacy,
      }),
    onSuccess: () => {
      setError("");
      onSaved();
    },
    onError: (exc: Error) => setError(exc.message),
  });

  return (
    <form
      className="mt-6 max-w-lg space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2 className="font-medium">Подписка</h2>
      <label className="block text-sm">
        Время
        <input
          className="mt-1 w-full rounded border px-3 py-2"
          value={localTime}
          onChange={(event) => setLocalTime(event.target.value)}
        />
      </label>
      <label className="block text-sm">
        Часовой пояс
        <input
          className="mt-1 w-full rounded border px-3 py-2"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
        />
      </label>
      <label className="block text-sm">
        Режим
        <select
          className="mt-1 w-full rounded border px-3 py-2"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          <option value="group">Общая сводка</option>
          <option value="per_company">По фирмам</option>
          <option value="both">Общая и по фирмам</option>
        </select>
      </label>
      <label className="block text-sm">
        Приватность
        <select
          className="mt-1 w-full rounded border px-3 py-2"
          value={privacy}
          onChange={(event) => setPrivacy(event.target.value)}
        >
          <option value="compact">Кратко</option>
          <option value="full">Полностью</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Рассылка включена
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={instant}
          onChange={(event) => setInstant(event.target.checked)}
        />
        Срочные сигналы
      </label>
      {error ? <p className="text-red-700">{error}</p> : null}
      <button type="submit" className="rounded border px-3 py-2" disabled={save.isPending}>
        Сохранить подписку
      </button>
    </form>
  );
}
