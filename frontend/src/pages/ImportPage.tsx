import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { commitImport, createSource, listCompanies, loadSources, uploadImport } from "../api";
import { Shell } from "../components/Shell";

export function ImportPage() {
  const [dataset, setDataset] = useState<"cash" | "revenue" | "plan">("plan");
  const [error, setError] = useState("");
  const [previewId, setPreviewId] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const sources = useQuery({
    queryKey: ["sources", companyId],
    queryFn: () => loadSources(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const chosen = sources.data?.sources.find((item) => item.dataset === dataset);

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
      <div className="mb-4 flex gap-2">
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("cash")}>Деньги</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("revenue")}>Продажи</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setDataset("plan")}>План</button>
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
    </Shell>
  );
}
