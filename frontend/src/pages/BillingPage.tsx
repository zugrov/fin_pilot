import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { checkout, createQuote, ensureWorkspace, loadTariff } from "../api";
import { Button, Card } from "../components/ui";
import { monthPayLabel, yearPayLabel } from "../lib/cta";

export function BillingPage() {
  const [companies, setCompanies] = useState(1);
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [error, setError] = useState("");
  const tariff = useQuery({ queryKey: ["tariff"], queryFn: loadTariff });
  const example = tariff.data?.examples.find((item) => item.companies === companies);
  const label = example
    ? interval === "year"
      ? yearPayLabel(example.annual_payable)
      : monthPayLabel(example.monthly)
    : "Загрузка тарифа";

  async function pay() {
    setError("");
    try {
      await ensureWorkspace();
      const quote = await createQuote(companies, interval);
      const payment = await checkout(quote.id, crypto.randomUUID());
      if (payment.confirmation_url) {
        window.location.assign(payment.confirmation_url);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось начать оплату");
    }
  }

  return (
    <Card>
      <h1 className="mb-2 text-xl font-semibold">Тариф и оплата</h1>
      <p className="mb-4 text-sm text-slate-600">
        Скидка за год: {tariff.data?.annual_discount_percent ?? "—"}%. Цена приходит с сервера.
      </p>
      <div className="mb-4 flex gap-2">
        <button type="button" className="rounded border px-3 py-1" onClick={() => setInterval("month")}>Месяц</button>
        <button type="button" className="rounded border px-3 py-1" onClick={() => setInterval("year")}>Год</button>
      </div>
      <label className="mb-4 block text-sm">
        Фирм
        <input
          className="mt-1 w-full rounded border px-3 py-2"
          type="number"
          min={1}
          max={5}
          value={companies}
          onChange={(event) => setCompanies(Number(event.target.value))}
        />
      </label>
      {example && interval === "year" ? (
        <p className="mb-4 text-sm">
          Без скидки {example.annual_list} ₽, к оплате {example.annual_payable} ₽, экономия {example.savings} ₽.
        </p>
      ) : null}
      {error ? <p className="mb-3 text-sm text-red-600">{error}</p> : null}
      <Button type="button" disabled={!example || !tariff.data?.annual_billing_enabled && interval === "year"} onClick={pay}>
        {label}
      </Button>
      <Link className="mt-4 block text-sm" to="/login">Войти другим аккаунтом</Link>
    </Card>
  );
}

export function BillingReturnPage() {
  return (
    <Card>
      <h1 className="mb-2 text-xl font-semibold">Платёж ожидает проверки</h1>
      <p className="text-sm text-slate-600">
        Возврат со страницы оплаты не открывает доступ. Статус подтвердит сервер.
      </p>
      <Link className="mt-4 block text-sm" to="/billing">К тарифу</Link>
    </Card>
  );
}
