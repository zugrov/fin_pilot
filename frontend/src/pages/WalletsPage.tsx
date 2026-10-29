import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import {
  createWallet,
  listCompanies,
  loadWallets,
  setWalletOpeningBalance,
  WalletRequestError,
  type Wallet,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { companyScopedData, useWritableCompanySelection } from "../lib/companySelection";
import {
  UNKNOWN_OUTCOME_MESSAGE,
  applyOpeningAfterFailure,
  applyWalletCreateAfterFailure,
  balanceLabel,
  buildOpeningEffectiveAt,
  completeOpeningAttempt,
  completeWalletCreateAttempt,
  guardCompanySwitch,
  lockedCompanyId,
  markOpeningSubmitExecuting,
  newIdempotencyKey,
  openingAttemptAfterCancel,
  openingSummary,
  parseAmountInput,
  pendingOpeningFromAttempt,
  resolveOpeningConfirmAttempt,
  resolveWalletCreateSubmit,
  shouldBlockOpeningFieldEdit,
  shouldBlockWalletCreateFieldEdit,
  shouldRestoreOpeningFromAttempt,
  type IdempotentAttempt,
  type OpeningSubmitPayload,
  type WalletCreatePayload,
} from "../lib/walletForm";

const WALLET_TYPES = [
  { value: "bank", label: "Банк" },
  { value: "cash", label: "Касса" },
  { value: "deposit", label: "Депозит" },
  { value: "business_owner_card", label: "Карта владельца" },
  { value: "other", label: "Другое" },
];

type PendingOpening = OpeningSubmitPayload & {
  walletLabel: string;
  offsetUsed: string;
  currency: string;
  idempotencyKey: string;
};

function failureMeta(exc: unknown): { status: number; code: string; message: string } {
  if (exc instanceof WalletRequestError) {
    return { status: exc.status, code: exc.code, message: exc.message };
  }
  const message = exc instanceof Error ? exc.message : "Запрос не выполнен";
  return { status: 0, code: "", message };
}

export function WalletsPage() {
  const client = useQueryClient();
  const [createName, setCreateName] = useState("");
  const [createCode, setCreateCode] = useState("");
  const [createType, setCreateType] = useState("bank");
  const [openingWalletId, setOpeningWalletId] = useState("");
  const [openingDate, setOpeningDate] = useState("");
  const [openingTime, setOpeningTime] = useState("00:00");
  const [openingAmount, setOpeningAmount] = useState("0.00");
  const [manualOffset, setManualOffset] = useState("");
  const [formError, setFormError] = useState("");
  const [pendingOpening, setPendingOpening] = useState<PendingOpening | null>(null);
  const [createAttempt, setCreateAttempt] = useState<IdempotentAttempt<WalletCreatePayload> | null>(
    null,
  );
  const [openingAttempt, setOpeningAttempt] = useState<IdempotentAttempt<OpeningSubmitPayload> | null>(
    null,
  );

  const resetFieldState = useCallback(() => {
    setCreateName("");
    setCreateCode("");
    setCreateType("bank");
    setOpeningWalletId("");
    setOpeningDate("");
    setOpeningTime("00:00");
    setOpeningAmount("0.00");
    setManualOffset("");
    setFormError("");
    setPendingOpening(null);
  }, []);

  const onCompanyChanged = useCallback(() => {
    resetFieldState();
    setCreateAttempt(null);
    setOpeningAttempt(null);
  }, [resetFieldState]);

  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const selection = useWritableCompanySelection(companies, { onCompanyChanged });
  const { companyId, company } = selection;
  const companyLockId = lockedCompanyId(createAttempt, openingAttempt);

  const handleCompanySelect = useCallback(
    (nextRaw: string) => {
      if (nextRaw) {
        const guard = guardCompanySwitch(nextRaw, companyLockId);
        if (!guard.allowed) {
          setFormError(guard.message);
          return;
        }
      }
      setFormError("");
      selection.onSelect(nextRaw);
    },
    [companyLockId, selection],
  );

  const wallets = useQuery({
    queryKey: ["wallets", companyId],
    queryFn: () => loadWallets(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const list = companyScopedData(companyId, companyId ?? undefined, wallets.data?.wallets);

  const createWalletMutation = useMutation({
    mutationFn: async (attempt: IdempotentAttempt<WalletCreatePayload>) => {
      const { companyId: cid, name, type, code } = attempt.payload;
      return createWallet(cid, { name, type, code }, attempt.key);
    },
    onSuccess: async () => {
      setFormError("");
      setCreateAttempt(completeWalletCreateAttempt());
      resetFieldState();
      await client.invalidateQueries({ queryKey: ["wallets", companyId] });
    },
    onError: (exc: unknown, attempt) => {
      const meta = failureMeta(exc);
      setCreateAttempt((current) => {
        if (!current || current.key !== attempt.key) {
          return current;
        }
        return applyWalletCreateAfterFailure(current, meta.status, meta.code);
      });
      const suffix =
        applyWalletCreateAfterFailure(
          { ...attempt, phase: "executing" },
          meta.status,
          meta.code,
        ) === null
          ? ""
          : ` ${UNKNOWN_OUTCOME_MESSAGE}`;
      setFormError(`${meta.message}${suffix}`);
    },
  });

  const confirmOpeningMutation = useMutation({
    mutationFn: async (pending: PendingOpening) => {
      return setWalletOpeningBalance(
        pending.walletId,
        pending.effectiveAt,
        pending.amount,
        pending.idempotencyKey,
      );
    },
    onSuccess: async () => {
      setFormError("");
      setPendingOpening(null);
      setOpeningAttempt(completeOpeningAttempt());
      await client.invalidateQueries({ queryKey: ["wallets", companyId] });
    },
    onError: (exc: unknown, pending) => {
      const meta = failureMeta(exc);
      setPendingOpening(null);
      setOpeningAttempt((current) => {
        if (!current || current.key !== pending.idempotencyKey) {
          return current;
        }
        return applyOpeningAfterFailure(current, meta.status, meta.code);
      });
      const suffix =
        applyOpeningAfterFailure(
          {
            key: pending.idempotencyKey,
            payload: {
              companyId: pending.companyId,
              walletId: pending.walletId,
              amount: pending.amount,
              effectiveAt: pending.effectiveAt,
            },
            phase: "executing",
          },
          meta.status,
          meta.code,
        ) === null
          ? ""
          : ` ${UNKNOWN_OUTCOME_MESSAGE}`;
      setFormError(`${meta.message}${suffix}`);
    },
  });

  const mutating = createWalletMutation.isPending || confirmOpeningMutation.isPending;
  const createFieldsLocked =
    shouldBlockWalletCreateFieldEdit(createAttempt) || createWalletMutation.isPending;
  const openingFieldsLocked =
    shouldBlockOpeningFieldEdit(openingAttempt) || confirmOpeningMutation.isPending;
  const createUnknown = createAttempt?.phase === "unknown";
  const openingUnknown = openingAttempt?.phase === "unknown";

  function runCreateSubmit(attempt: IdempotentAttempt<WalletCreatePayload>) {
    setCreateAttempt(attempt);
    createWalletMutation.mutate(attempt);
  }

  function submitCreate() {
    setFormError("");
    if (createAttempt?.phase === "unknown") {
      runCreateSubmit({ ...createAttempt, phase: "executing" });
      return;
    }
    if (!companyId) {
      setFormError("Выберите фирму");
      return;
    }
    if (!createName.trim() || !createCode.trim()) {
      setFormError("Укажите название и код счёта");
      return;
    }
    const next: WalletCreatePayload = {
      companyId,
      name: createName.trim(),
      type: createType,
      code: createCode.trim(),
    };
    const resolved = resolveWalletCreateSubmit(createAttempt, next, newIdempotencyKey);
    if (resolved.kind === "blocked") {
      setFormError(UNKNOWN_OUTCOME_MESSAGE);
      return;
    }
    runCreateSubmit(resolved.attempt);
  }

  function requestOpeningConfirm() {
    setFormError("");
    if (shouldRestoreOpeningFromAttempt(openingAttempt)) {
      setPendingOpening(pendingOpeningFromAttempt(openingAttempt!));
      return;
    }
    if (!companyId || !openingWalletId) {
      setFormError("Выберите счёт");
      return;
    }
    const amount = parseAmountInput(openingAmount);
    if (!amount.ok) {
      setFormError(amount.message);
      return;
    }
    const effective = buildOpeningEffectiveAt(
      openingDate,
      openingTime,
      company?.timezone,
      manualOffset.trim() || undefined,
    );
    if (!effective.ok) {
      setFormError(effective.message);
      return;
    }
    const next: OpeningSubmitPayload = {
      companyId,
      walletId: openingWalletId,
      amount: amount.value,
      effectiveAt: effective.iso,
    };
    const wallet = list?.find((item) => item.id === openingWalletId);
    const label = wallet ? `${wallet.name}${wallet.code ? ` (${wallet.code})` : ""}` : openingWalletId;
    const meta = {
      walletLabel: label,
      offsetUsed: effective.offsetUsed,
      currency: wallet?.currency ?? "RUB",
    };
    const resolved = resolveOpeningConfirmAttempt(openingAttempt, next, meta, newIdempotencyKey);
    if (resolved.kind === "blocked") {
      setFormError(UNKNOWN_OUTCOME_MESSAGE);
      return;
    }
    setOpeningAttempt(resolved.attempt);
    setPendingOpening(pendingOpeningFromAttempt(resolved.attempt));
  }

  function cancelOpeningConfirm() {
    setOpeningAttempt(openingAttemptAfterCancel(openingAttempt));
    setPendingOpening(null);
  }

  function confirmOpeningSubmit() {
    if (!pendingOpening || !openingAttempt) {
      return;
    }
    const executing = markOpeningSubmitExecuting(openingAttempt);
    setOpeningAttempt(executing);
    const pending = pendingOpeningFromAttempt(executing);
    setPendingOpening(pending);
    confirmOpeningMutation.mutate(pending);
  }

  return (
    <Shell title="Кошельки">
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || mutating || Boolean(companyLockId)}
        onSelect={handleCompanySelect}
      />
      {company?.timezone ? (
        <p className="mb-3 text-sm text-ink-muted">Часовой пояс фирмы: {company.timezone}</p>
      ) : (
        <p className="mb-3 text-sm text-warn">
          Пояс фирмы неизвестен — для начального остатка укажите смещение UTC вручную.
        </p>
      )}
      {createUnknown || openingUnknown ? (
        <p className="mb-3 rounded-control border border-warn-line bg-warn-soft p-3 text-sm text-warn">
          {UNKNOWN_OUTCOME_MESSAGE}
        </p>
      ) : null}
      {formError ? <p className="mb-3 text-danger">{formError}</p> : null}
      {companyId && wallets.isLoading ? <p>Загрузка</p> : null}
      {companyId && wallets.isError ? (
        <p className="text-danger">Не удалось загрузить кошельки.</p>
      ) : null}
      {list?.length === 0 ? <p className="mb-4">Кошельков нет.</p> : null}
      <ul className="mb-8 space-y-3">
        {list?.map((wallet) => (
          <WalletCard key={wallet.id} wallet={wallet} />
        ))}
      </ul>

      {selection.canWrite && companyId ? (
        <section className="mb-8 max-w-lg rounded-card border bg-white p-4">
          <h2 className="mb-3 font-medium">Новый счёт</h2>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              submitCreate();
            }}
          >
            <label className="block text-sm">
              Название
              <input
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={createName}
                disabled={createFieldsLocked}
                onChange={(event) => setCreateName(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              Код (для импорта)
              <input
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={createCode}
                disabled={createFieldsLocked}
                onChange={(event) => setCreateCode(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              Тип
              <select
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={createType}
                disabled={createFieldsLocked}
                onChange={(event) => setCreateType(event.target.value)}
              >
                {WALLET_TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="rounded-control bg-brand px-3 py-2 text-white disabled:opacity-50"
              disabled={mutating}
            >
              {createWalletMutation.isPending
                ? "Сохранение…"
                : createUnknown
                  ? "Повторить отправку"
                  : "Создать счёт"}
            </button>
          </form>
        </section>
      ) : null}

      {selection.canWrite && companyId && (list?.length ?? 0) > 0 ? (
        <section className="max-w-lg rounded-card border bg-white p-4">
          <h2 className="mb-3 font-medium">Начальный остаток</h2>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              requestOpeningConfirm();
            }}
          >
            <label className="block text-sm">
              Счёт
              <select
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={openingWalletId}
                disabled={openingFieldsLocked}
                onChange={(event) => setOpeningWalletId(event.target.value)}
              >
                <option value="">Выберите</option>
                {list?.map((wallet) => (
                  <option key={wallet.id} value={wallet.id}>
                    {wallet.name}
                    {wallet.code ? ` (${wallet.code})` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Дата
              <input
                type="date"
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={openingDate}
                disabled={openingFieldsLocked}
                onChange={(event) => setOpeningDate(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              Время
              <input
                type="time"
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={openingTime}
                disabled={openingFieldsLocked}
                onChange={(event) => setOpeningTime(event.target.value)}
              />
            </label>
            {!company?.timezone ? (
              <label className="block text-sm">
                Смещение UTC (например +03:00)
                <input
                  className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                  value={manualOffset}
                  disabled={openingFieldsLocked}
                  placeholder="+03:00"
                  onChange={(event) => setManualOffset(event.target.value)}
                />
              </label>
            ) : null}
            <label className="block text-sm">
              Сумма (RUB)
              <input
                className="mt-1 w-full rounded-control border px-2 py-1 disabled:bg-canvas"
                value={openingAmount}
                disabled={openingFieldsLocked}
                onChange={(event) => setOpeningAmount(event.target.value)}
              />
            </label>
            <button
              type="submit"
              className="rounded-control bg-brand px-3 py-2 text-white disabled:opacity-50"
              disabled={mutating}
            >
              {openingUnknown ? "Продолжить подтверждение" : "Проверить и подтвердить"}
            </button>
          </form>
        </section>
      ) : null}

      {pendingOpening ? (
        <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4">
          <div className="max-w-md rounded-card bg-white p-5 shadow-lg">
            <h3 className="mb-3 text-lg font-medium">Подтвердите начальный остаток</h3>
            <ul className="mb-4 space-y-1 text-sm">
              <li>Фирма: {company?.name ?? companyId}</li>
              <li>Счёт: {pendingOpening.walletLabel}</li>
              <li>
                Сумма: {pendingOpening.amount} {pendingOpening.currency}
              </li>
              <li>Момент: {pendingOpening.effectiveAt}</li>
              <li>Часовой пояс / смещение: {pendingOpening.offsetUsed}</li>
            </ul>
            <p className="mb-4 text-sm text-ink-muted">
              Повторная отправка с тем же ключом не создаст второй остаток. Замена существующего
              active остатка пометит прежний как replaced.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-control border px-3 py-2"
                disabled={confirmOpeningMutation.isPending}
                onClick={cancelOpeningConfirm}
              >
                Отмена
              </button>
              <button
                type="button"
                className="rounded-control bg-brand px-3 py-2 text-white disabled:opacity-50"
                disabled={confirmOpeningMutation.isPending}
                onClick={confirmOpeningSubmit}
              >
                {confirmOpeningMutation.isPending ? "Сохранение…" : "Подтвердить"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </Shell>
  );
}

function WalletCard({ wallet }: { wallet: Wallet }) {
  const flags = wallet.quality_flags ?? [];
  return (
    <li className="rounded-card border bg-white p-4">
      <div className="font-medium">
        {wallet.name}
        {wallet.code ? <span className="ml-2 text-sm text-ink-muted">{wallet.code}</span> : null}
      </div>
      <p className="text-sm text-ink-muted">
        Тип: {wallet.type}; валюта: {wallet.currency ?? "RUB"}
      </p>
      <p className="text-sm">
        Текущий баланс: {balanceLabel(wallet.balance ?? null, flags)}
      </p>
      <p className="text-sm">Начальный остаток: {openingSummary(wallet.active_opening)}</p>
    </li>
  );
}
