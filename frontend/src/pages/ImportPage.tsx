import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  commitImport,
  createMailbox,
  createSource,
  listCompanies,
  loadSources,
  loadWallets,
  testMailbox,
  uploadImport,
} from "../api";
import { Shell } from "../components/Shell";
import { coverageCaption, mailboxCaption, pollResultCaption } from "../lib/mail";

export function ImportPage() {
  const [dataset, setDataset] = useState<"cash" | "revenue" | "plan" | "budget">("budget");
  const [error, setError] = useState("");
  const [previewId, setPreviewId] = useState("");
  const [host, setHost] = useState("");
  const [username, setUsername] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [sender, setSender] = useState("");
  const [password, setPassword] = useState("");
  const [mailError, setMailError] = useState("");
  const [mailNote, setMailNote] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const sources = useQuery({
    queryKey: ["sources", companyId],
    queryFn: () => loadSources(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const chosen = sources.data?.sources.find(
    (item) => item.dataset === dataset && item.type !== "email",
  );
  const mailbox = sources.data?.sources.find((item) => item.type === "email") ?? null;
  const wallets = useQuery({
    queryKey: ["wallets", companyId],
    queryFn: () => loadWallets(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const walletId = wallets.data?.wallets[0]?.id;

  const ensure = useMutation({
    mutationFn: () => createSource(companyId ?? "", dataset, `${dataset}-${crypto.randomUUID().slice(0, 8)}`),
    onSuccess: async () => {
      setError("");
      await client.invalidateQueries({ queryKey: ["sources", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadImport(companyId ?? "", chosen?.id ?? "", file),
    onSuccess: (preview) => {
      setError("");
      setPreviewId(preview.id);
    },
    onError: (exc: Error) => setError(exc.message),
  });

  const saveMailbox = useMutation({
    mutationFn: () =>
      createMailbox(companyId ?? "", walletId ?? "", {
        host,
        username,
        folder,
        sender,
        password,
      }),
    onSuccess: async () => {
      setPassword("");
      setMailError("");
      setMailNote("Ящик сохранён. Письма сами не проводятся.");
      await client.invalidateQueries({ queryKey: ["sources", companyId] });
    },
    onError: (exc: Error) => setMailError(exc.message),
  });

  const checkMailbox = useMutation({
    mutationFn: () => testMailbox(companyId ?? "", mailbox?.id ?? ""),
    onSuccess: () => {
      setMailError("");
      setMailNote(pollResultCaption("ok"));
    },
    onError: (exc: Error) => {
      setMailNote("");
      setMailError(pollResultCaption(exc.message));
    },
  });

  const commit = useMutation({
    mutationFn: () => commitImport(previewId),
    onSuccess: () => setError(""),
    onError: (exc: Error) => setError(exc.message),
  });

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Импорт</h1>
      {sources.isLoading ? <p>Загрузка</p> : null}
      {sources.isError ? <p className="text-red-700">Не удалось загрузить источники.</p> : null}
      <div className="mb-4 flex flex-wrap gap-2">
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("cash")}>Деньги</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("revenue")}>Продажи</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("plan")}>План</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("budget")}>Бюджет</button>
      </div>
      {sources.isSuccess && chosen ? (
        <p className="mb-3 text-sm">Источник: {chosen.name}</p>
      ) : null}
      {sources.isSuccess && !chosen ? (
        <p className="mb-3 text-sm">Источника этого вида нет.</p>
      ) : null}
      <button
        type="button"
        className="mb-4 rounded border px-3 py-2"
        disabled={!companyId || ensure.isPending}
        onClick={() => ensure.mutate()}
      >
        Создать источник
      </button>
      <input
        type="file"
        className="mb-4 block"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && chosen) {
            upload.mutate(file);
          }
        }}
      />
      {upload.data ? (
        <p className="mb-3 text-sm">
          Новых {upload.data.counts.new}, повтор {upload.data.counts.repeated}, ошибок {upload.data.counts.invalid}
        </p>
      ) : null}
      {error ? <p className="mb-3 text-sm text-red-700">{error}</p> : null}
      <button
        type="button"
        className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
        disabled={!previewId || commit.isPending}
        onClick={() => commit.mutate()}
      >
        Провести
      </button>
      {commit.data ? <p className="mt-3 text-sm">Статус: {commit.data.status}</p> : null}
      <section className="mt-8 max-w-xl border-t pt-4">
        <h2 className="mb-3 text-lg font-semibold">Почта</h2>
        {sources.isLoading ? <p>Загрузка ящика</p> : null}
        {sources.isError ? <p className="text-red-700">Не удалось загрузить ящик.</p> : null}
        {sources.isSuccess && mailbox == null ? <p>{mailboxCaption(null)}</p> : null}
        {mailbox ? (
          <div className="mb-4 text-sm">
            <p>Сервер: {mailbox.host}</p>
            <p>Ящик: {mailbox.username}</p>
            <p>Папка: {mailbox.folder}</p>
            <p>Отправитель: {mailbox.sender}</p>
            <p>{coverageCaption(mailbox.coverage_through)}</p>
            <p>Последняя попытка: {mailbox.last_attempt_at ?? "нет"}</p>
            <p>Последний успех: {mailbox.last_success_at ?? "нет"}</p>
            {mailbox.last_error ? <p>Проблема: {mailbox.last_error}</p> : null}
            <button
              type="button"
              className="mt-3 rounded border px-3 py-2"
              disabled={checkMailbox.isPending}
              onClick={() => checkMailbox.mutate()}
            >
              Проверить вход
            </button>
          </div>
        ) : null}
        {sources.isSuccess ? (
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (walletId) {
                saveMailbox.mutate();
              }
            }}
          >
            <label className="grid gap-1 text-sm">
              Сервер
              <input
                className="rounded border px-2 py-1"
                value={host}
                onChange={(event) => setHost(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm">
              Логин ящика
              <input
                className="rounded border px-2 py-1"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm">
              Папка
              <input
                className="rounded border px-2 py-1"
                value={folder}
                onChange={(event) => setFolder(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm">
              Отправитель
              <input
                className="rounded border px-2 py-1"
                value={sender}
                onChange={(event) => setSender(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-sm">
              Пароль
              <input
                className="rounded border px-2 py-1"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {!walletId && wallets.isSuccess ? (
              <p className="text-sm">Нужен кошелёк для выписки.</p>
            ) : null}
            <button
              type="submit"
              className="w-fit rounded border px-3 py-2"
              disabled={!companyId || !walletId || saveMailbox.isPending}
            >
              Сохранить ящик
            </button>
          </form>
        ) : null}
        {mailError ? <p className="mt-3 text-sm text-red-700">{mailError}</p> : null}
        {mailNote ? <p className="mt-3 text-sm">{mailNote}</p> : null}
      </section>
    </Shell>
  );
}
