import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  activateCompany,
  checkout,
  createCompany,
  createQuote,
  ensureWorkspace,
  listCompanies,
  loadBillingSubscription,
  loadPayment,
  loadTariff,
  type BillingSubscription,
} from "../api";
import { Button, Card, Field } from "../components/ui";
import { monthPayLabel, renewPayLabel, yearPayLabel } from "../lib/cta";

const STATUS_LABEL: Record<string, string> = {
  active: "Оплачена",
  grace: "Льготный период",
  expired: "Оплата закончилась",
  awaiting_payment: "Ожидает оплаты",
};

const CHECKOUT_PAYMENT_KEY = "fp_checkout_payment_id";
const SELECTED_COMPANY_KEY = "fp_company_id";
const POLL_LIMIT = 15;
const POLL_MS = 5000;

function paidUntil(value: string | null): string {
  if (!value) {
    return "нет оплаченного срока";
  }
  return new Date(value).toLocaleDateString("ru-RU", { dateStyle: "long" });
}

function isPaid(subscription: BillingSubscription | undefined): boolean {
  return subscription?.status === "active" || subscription?.status === "grace";
}

export function BillingPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [companies, setCompanies] = useState(1);
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [error, setError] = useState("");
  const [assignError, setAssignError] = useState("");
  const [name, setName] = useState("");
  const [pendingCompanyId, setPendingCompanyId] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const createKey = useRef(crypto.randomUUID());
  const isCreatingRef = useRef(false);
  const tariff = useQuery({ queryKey: ["tariff"], queryFn: loadTariff });
  const subscription = useQuery({
    queryKey: ["billing-subscription"],
    queryFn: loadBillingSubscription,
  });
  const companyList = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const paid = isPaid(subscription.data);
  const billedCompanies = paid
    ? Math.max(subscription.data?.paid_slots || 0, subscription.data?.company_limit || 0, 1)
    : companies;
  const example = tariff.data?.examples.find((item) => item.companies === billedCompanies);
  const amount = example ? (interval === "year" ? example.annual_payable : example.monthly) : "";
  const label = !example
    ? "Загрузка тарифа"
    : paid
      ? renewPayLabel(amount, interval)
      : interval === "year"
        ? yearPayLabel(example.annual_payable)
        : monthPayLabel(example.monthly);
  const waitingId =
    pendingCompanyId ||
    companyList.data?.companies.find((item) => item.status && item.status !== "active")?.id ||
    "";

  async function assign(companyId: string) {
    await activateCompany(companyId);
    sessionStorage.setItem(SELECTED_COMPANY_KEY, companyId);
    await queryClient.invalidateQueries({ queryKey: ["companies"] });
    await queryClient.invalidateQueries({ queryKey: ["billing-subscription"] });
    navigate("/");
  }

  async function createFirm() {
    if (isCreatingRef.current) {
      return;
    }
    isCreatingRef.current = true;
    setAssignError("");
    setIsCreating(true);
    try {
      if (waitingId) {
        await assign(waitingId);
        return;
      }
      const trimmed = name.trim();
      if (!trimmed) {
        setAssignError("Укажите название фирмы");
        return;
      }
      const created = await createCompany(trimmed, createKey.current);
      await queryClient.invalidateQueries({ queryKey: ["companies"] });
      try {
        await assign(created.id);
      } catch (exc) {
        setPendingCompanyId(created.id);
        const reason = exc instanceof Error ? exc.message : "Не удалось назначить слот";
        setAssignError(`${reason} Фирма сохранена, назначение можно повторить.`);
      }
    } catch (exc) {
      setAssignError(exc instanceof Error ? exc.message : "Не удалось создать фирму");
    } finally {
      isCreatingRef.current = false;
      setIsCreating(false);
    }
  }

  async function pay() {
    setError("");
    try {
      await ensureWorkspace();
      const quote = await createQuote(billedCompanies, interval);
      const payment = await checkout(quote.id, crypto.randomUUID());
      if (payment.payment_id) {
        sessionStorage.setItem(CHECKOUT_PAYMENT_KEY, payment.payment_id);
      }
      if (payment.confirmation_url) {
        window.location.assign(payment.confirmation_url);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось начать оплату");
    }
  }

  const freeSlots = subscription.data?.free_slots ?? 0;

  return (
    <Card>
      <h1 className="mb-2 text-xl font-semibold">Тариф и оплата</h1>
      <p className="mb-4 text-sm text-slate-600">
        Скидка за год: {tariff.data?.annual_discount_percent ?? "—"}%. Цена приходит с сервера.
      </p>
      {subscription.data ? (
        <div className="mb-4 space-y-1 text-sm">
          <p>Статус: {STATUS_LABEL[subscription.data.status] ?? subscription.data.status}</p>
          <p>Оплачено до: {paidUntil(subscription.data.paid_through)}</p>
          <p>
            Слоты: оплачено {subscription.data.paid_slots}, занято {subscription.data.occupied_slots},
            свободно {subscription.data.free_slots}
          </p>
        </div>
      ) : null}
      <div className="mb-4 flex flex-wrap gap-2">
        <button type="button" className="rounded border px-3 py-1" onClick={() => setInterval("month")}>Месяц</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setInterval("year")}>Год</button>
      </div>
      {paid ? null : (
        <label className="mb-4 block text-sm">
          Фирм в подписке
          <input
            className="mt-1 w-full rounded border px-3 py-2"
            type="number"
            min={1}
            max={5}
            value={companies}
            onChange={(event) => setCompanies(Number(event.target.value))}
          />
        </label>
      )}
      {example && interval === "year" ? (
        <p className="mb-4 text-sm">
          Без скидки {example.annual_list} ₽, к оплате {example.annual_payable} ₽, экономия {example.savings} ₽.
        </p>
      ) : null}
      {error ? <p className="mb-3 text-sm text-red-600">{error}</p> : null}
      <Button type="button" disabled={!example || (!tariff.data?.annual_billing_enabled && interval === "year")} onClick={pay}>
        {label}
      </Button>
      {freeSlots > 0 ? (
        <div className="mt-6 border-t pt-4">
          <h2 className="mb-2 text-base font-semibold">Добавить фирму</h2>
          {waitingId ? (
            <p className="mb-3 text-sm">Фирма уже создана и ждёт назначения в слот.</p>
          ) : (
            <Field
              label="Название"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          )}
          {assignError ? <p className="mb-3 text-sm text-red-600">{assignError}</p> : null}
          <Button type="button" disabled={isCreating} onClick={createFirm}>
            {waitingId ? "Назначить в слот" : "Создать фирму"}
          </Button>
        </div>
      ) : null}
      <Link
        className="mt-4 block w-full rounded-md border border-slate-900 px-4 py-2 text-center text-sm"
        to="/overview"
      >
        В основное меню
      </Link>
      <Link className="mt-4 block text-sm" to="/login">Войти другим аккаунтом</Link>
    </Card>
  );
}

export function BillingReturnPage() {
  const [message, setMessage] = useState("Проверяем статус на сервере…");
  const [subscription, setSubscription] = useState<BillingSubscription | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const polls = useRef(0);

  const readStatus = useCallback(async (): Promise<boolean> => {
    const paymentId = sessionStorage.getItem(CHECKOUT_PAYMENT_KEY);
    if (paymentId) {
      const payment = await loadPayment(paymentId);
      if (!payment.activated) {
        return false;
      }
    }
    const view = await loadBillingSubscription();
    if (view.status === "active" || view.status === "grace") {
      setSubscription(view);
      setMessage("Подписка подтверждена сервером.");
      setCanRetry(false);
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    let timer = 0;
    let stopped = false;

    async function tick() {
      try {
        const done = await readStatus();
        if (stopped || done) {
          return;
        }
        polls.current += 1;
        if (polls.current >= POLL_LIMIT) {
          setMessage("Сервер ещё не подтвердил оплату. Новую оплату не создаём.");
          setCanRetry(true);
          return;
        }
        timer = window.setTimeout(() => void tick(), POLL_MS);
      } catch (exc) {
        setMessage(exc instanceof Error ? exc.message : "Не удалось проверить статус");
        setCanRetry(true);
      }
    }

    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [readStatus]);

  return (
    <Card>
      <h1 className="mb-2 text-xl font-semibold">
        {subscription ? "Подписка активна" : "Платёж ожидает проверки"}
      </h1>
      <p className="text-sm text-slate-600">{message}</p>
      {subscription ? (
        <p className="mt-3 text-sm">
          Оплачено до {paidUntil(subscription.paid_through)}. Свободных слотов: {subscription.free_slots}.
        </p>
      ) : (
        <p className="mt-3 text-sm text-slate-600">
          Возврат со страницы оплаты не открывает доступ. Статус подтвердит сервер.
        </p>
      )}
      {canRetry ? (
        <div className="mt-4">
          <Button
            type="button"
            onClick={() => {
              setCanRetry(false);
              setMessage("Проверяем статус на сервере…");
              void readStatus().then((done) => {
                if (!done) {
                  setMessage("Сервер ещё не подтвердил оплату. Новую оплату не создаём.");
                  setCanRetry(true);
                }
              });
            }}
          >
            Проверить статус
          </Button>
        </div>
      ) : null}
      <Link className="mt-4 block text-sm" to="/billing">
        {subscription ? "Создать фирму" : "К тарифу"}
      </Link>
    </Card>
  );
}
