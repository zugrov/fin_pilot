import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

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
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { coverageCaption, mailboxCaption, pollResultCaption } from "../lib/mail";
import {
  companyScopedData,
  guardWriteRequest,
  importUploadTarget,
  resetImportDependentState,
  useWritableCompanySelection,
} from "../lib/companySelection";

export function ImportPage() {
  const [dataset, setDataset] = useState<"cash" | "revenue" | "plan" | "budget">("budget");
  const [error, setError] = useState("");
  const [previewId, setPreviewId] = useState("");
  const [uploadPreview, setUploadPreview] = useState<Awaited<ReturnType<typeof uploadImport>> | null>(
    null,
  );
  const [host, setHost] = useState("");
  const [username, setUsername] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [sender, setSender] = useState("");
  const [password, setPassword] = useState("");
  const [mailError, setMailError] = useState("");
  const [mailNote, setMailNote] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });

  const resetDependent = useCallback(() => {
    const cleared = resetImportDependentState();
    setPreviewId(cleared.previewId);
    setError(cleared.error);
    setMailError(cleared.mailError);
    setMailNote(cleared.mailNote);
    setUploadPreview(null);
    setPassword("");
  }, []);

  const onCompanyChanged = useCallback(
    (prevId: string | null, nextId: string | null) => {
      if (prevId !== null && prevId !== nextId) {
        resetDependent();
      }
    },
    [resetDependent],
  );

  const selection = useWritableCompanySelection(companies.data?.companies, {
    onCompanyChanged,
  });
  const { companyId } = selection;

  const sources = useQuery({
    queryKey: ["sources", companyId],
    queryFn: () => loadSources(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const sourceList = companyScopedData(companyId, companyId ?? undefined, sources.data?.sources);
  const chosen = sourceList?.find((item) => item.dataset === dataset && item.type !== "email");
  const mailbox = sourceList?.find((item) => item.type === "email") ?? null;

  const wallets = useQuery({
    queryKey: ["wallets", companyId],
    queryFn: () => loadWallets(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const walletList = companyScopedData(companyId, companyId ?? undefined, wallets.data?.wallets);
  const walletId = walletList?.[0]?.id;

  const ensure = useMutation({
    mutationFn: () => {
      const target = guardWriteRequest(companyId);
      if (!target.allowed) {
        throw new Error("Выберите фирму");
      }
      return createSource(target.companyId, dataset, `${dataset}-${crypto.randomUUID().slice(0, 8)}`);
    },
    onSuccess: async () => {
      setError("");
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["sources", companyId] });
      }
    },
    onError: (exc: Error) => setError(exc.message),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const target = importUploadTarget(companyId, chosen?.id);
      if (!target.allowed) {
        throw new Error("Выберите фирму и источник");
      }
      return uploadImport(target.companyId, target.sourceId, file);
    },
    onSuccess: (preview) => {
      setError("");
      setPreviewId(preview.id);
      setUploadPreview(preview);
    },
    onError: (exc: Error) => setError(exc.message),
  });

  const saveMailbox = useMutation({
    mutationFn: () => {
      const target = guardWriteRequest(companyId);
      if (!target.allowed || !walletId) {
        throw new Error("Выберите фирму и кошелёк");
      }
      return createMailbox(target.companyId, walletId, {
        host,
        username,
        folder,
        sender,
        password,
      });
    },
    onSuccess: async () => {
      setPassword("");
      setMailError("");
      setMailNote("Ящик сохранён. Письма сами не проводятся.");
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["sources", companyId] });
      }
    },
    onError: (exc: Error) => setMailError(exc.message),
  });

  const checkMailbox = useMutation({
    mutationFn: () => {
      const target = guardWriteRequest(companyId);
      if (!target.allowed || !mailbox?.id) {
        throw new Error("Выберите фирму");
      }
      return testMailbox(target.companyId, mailbox.id);
    },
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
    mutationFn: () => {
      if (!previewId) {
        throw new Error("Нет пакета для проведения");
      }
      return commitImport(previewId);
    },
    onSuccess: () => setError(""),
    onError: (exc: Error) => setError(exc.message),
  });

  const writeLocked =
    ensure.isPending ||
    upload.isPending ||
    commit.isPending ||
    saveMailbox.isPending ||
    checkMailbox.isPending;

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Импорт</h1>
      <CompanyWritePicker
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={writeLocked}
        onSelect={selection.onSelect}
      />
      {companyId && sources.isLoading ? <p>Загрузка</p> : null}
      {companyId && sources.isError ? <p className="text-red-700">Не удалось загрузить источники.</p> : null}
      <div className="mb-4 flex flex-wrap gap-2">
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("cash")}>
          Деньги
        </button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("revenue")}>
          Продажи
        </button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("plan")}>
          План
        </button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("budget")}>
          Бюджет
        </button>
      </div>
      {companyId && sources.isSuccess && chosen ? (
        <p className="mb-3 text-sm">Источник: {chosen.name}</p>
      ) : null}
      {companyId && sources.isSuccess && !chosen ? (
        <p className="mb-3 text-sm">Источника этого вида нет.</p>
      ) : null}
      <button
        type="button"
        className="mb-4 rounded border px-3 py-2 disabled:opacity-50"
        disabled={!selection.canWrite || ensure.isPending}
        onClick={() => {
          if (guardWriteRequest(companyId).allowed) {
            ensure.mutate();
          }
        }}
      >
        Создать источник
      </button>
      <input
        type="file"
        className="mb-4 block disabled:opacity-50"
        disabled={!selection.canWrite || !chosen || upload.isPending}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && importUploadTarget(companyId, chosen?.id).allowed) {
            upload.mutate(file);
          }
          event.target.value = "";
        }}
      />
      {uploadPreview ? (
        <p className="mb-3 text-sm">
          Новых {uploadPreview.counts.new}, повтор {uploadPreview.counts.repeated}, ошибок{" "}
          {uploadPreview.counts.invalid}
        </p>
      ) : null}
      {error ? <p className="mb-3 text-sm text-red-700">{error}</p> : null}
      <button
        type="button"
        className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
        disabled={!previewId || commit.isPending}
        onClick={() => {
          if (previewId) {
            commit.mutate();
          }
        }}
      >
        Провести
      </button>
      {commit.data ? <p className="mt-3 text-sm">Статус: {commit.data.status}</p> : null}
      <section className="mt-8 max-w-xl border-t pt-4">
        <h2 className="mb-3 text-lg font-semibold">Почта</h2>
        {companyId && sources.isLoading ? <p>Загрузка ящика</p> : null}
        {companyId && sources.isError ? <p className="text-red-700">Не удалось загрузить ящик.</p> : null}
        {companyId && sources.isSuccess && mailbox == null ? <p>{mailboxCaption(null)}</p> : null}
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
              className="mt-3 rounded border px-3 py-2 disabled:opacity-50"
              disabled={!selection.canWrite || checkMailbox.isPending}
              onClick={() => {
                if (guardWriteRequest(companyId).allowed) {
                  checkMailbox.mutate();
                }
              }}
            >
              Проверить вход
            </button>
          </div>
        ) : null}
        {companyId && sources.isSuccess ? (
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (selection.canWrite && walletId) {
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
            {wallets.isSuccess && !walletId ? (
              <p className="text-sm">Нужен кошелёк для выписки.</p>
            ) : null}
            <button
              type="submit"
              className="w-fit rounded border px-3 py-2 disabled:opacity-50"
              disabled={!selection.canWrite || !walletId || saveMailbox.isPending}
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
