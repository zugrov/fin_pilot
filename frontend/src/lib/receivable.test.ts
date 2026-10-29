import { describe, expect, it } from "vitest";

import { formatMoney, sumMoney, toCents } from "./money";
import {
  ageDaysLabel,
  asOfCaption,
  BUCKETS,
  bucketHint,
  bucketLabel,
  bucketPercentText,
  bucketShares,
  completenessLabel,
  completenessNote,
  counterpartyLabel,
  debtBasisNote,
  documentLabel,
  emptyStateText,
  flagNotes,
  hasMissingRevenueSource,
  isRowsTruncated,
  isUnavailable,
  orphanNote,
  orphanTitle,
  receivableErrorText,
  ROWS_LIMIT,
  todayInTimeZone,
  truncatedNotice,
  unallocatedNote,
  unallocatedTitle,
} from "./receivable";

const ORACLE_TOTAL = "47506.00";
const ORACLE_BUCKETS = {
  "0-30": "32501.00",
  "31-60": "5002.00",
  "61-90": "5002.00",
  ">90": "5001.00",
};

describe("итоги ORACLE дебиторки", () => {
  it("сумма корзин равна итогу", () => {
    const sum = sumMoney(BUCKETS.map((code) => ORACLE_BUCKETS[code]));
    expect(sum).toBe(ORACLE_TOTAL);
    expect(sumMoney(Object.values(ORACLE_BUCKETS))).toBe("47506.00");
  });

  it("корзины ORACLE совпадают с ожидаемыми", () => {
    expect(ORACLE_BUCKETS["0-30"]).toBe("32501.00");
    expect(ORACLE_BUCKETS["31-60"]).toBe("5002.00");
    expect(ORACLE_BUCKETS["61-90"]).toBe("5002.00");
    expect(ORACLE_BUCKETS[">90"]).toBe("5001.00");
    expect(ORACLE_BUCKETS["0-30"]).toBe("32501.00");
  });

  it("сумма строк равна итогу", () => {
    const rows = [
      "12000.00",
      "6000.00",
      "8000.00",
      "-2000.00",
      "6000.00",
      "1500.00",
      "5000.00",
      "5000.00",
      "5000.00",
      "1.00",
      "1.00",
      "1.00",
      "1.00",
      "1.00",
      "1.00",
      "1000.00",
    ];
    expect(sumMoney(rows)).toBe(ORACLE_TOTAL);
  });

  it("форматирует итог по-русски", () => {
    expect(formatMoney(ORACLE_TOTAL)).toBe("47 506,00 ₽");
    expect(formatMoney(ORACLE_BUCKETS["0-30"])).toBe("32 501,00 ₽");
  });
});

describe("доли корзин", () => {
  it("считает проценты текстом", () => {
    const slices = BUCKETS.map((code) => ({ code, total: ORACLE_BUCKETS[code] }));
    const shares = bucketShares(slices, ORACLE_TOTAL);
    const byCode = Object.fromEntries(shares.map((item) => [item.code, item.percent]));
    expect(byCode["0-30"]).toBe("68,4");
    expect(byCode["31-60"]).toBe("10,5");
    expect(byCode["61-90"]).toBe("10,5");
    expect(byCode[">90"]).toBe("10,5");
  });

  it("не делит на ноль при нулевом итоге", () => {
    const slices = BUCKETS.map((code) => ({ code, total: "0.00" }));
    const shares = bucketShares(slices, "0.00");
    expect(shares.every((item) => item.percent === "0")).toBe(true);
    expect(bucketPercentText(shares[0].percent)).toBe("0 %");
  });

  it("не делит на ноль при отсутствии итога", () => {
    const shares = bucketShares([{ code: "0-30", total: null }], null);
    expect(shares[0].percent).toBe("0");
  });

  it("показывает процент с подписью", () => {
    expect(bucketPercentText("68,4")).toBe("68,4 %");
    expect(bucketPercentText("100")).toBe("100 %");
  });
});

describe("null не равен нулю", () => {
  it("отсутствующая сумма — «Нет данных», а не 0,00", () => {
    expect(formatMoney(null)).toBe("Нет данных");
    expect(formatMoney(undefined)).toBe("Нет данных");
    expect(formatMoney("")).toBe("Нет данных");
    expect(formatMoney("0.00")).toBe("0,00 ₽");
  });

  it("сумма с пропуском не считается нулём", () => {
    expect(sumMoney(["100.00", null])).toBeNull();
    expect(sumMoney([])).toBe("0.00");
  });

  it("дни без значения не показываются нулём", () => {
    expect(ageDaysLabel(null)).toBe("Нет данных");
    expect(ageDaysLabel(undefined)).toBe("Нет данных");
    expect(ageDaysLabel(0)).toBe("0");
  });
});

describe("метки корзин", () => {
  it("переводит коды на понятный язык", () => {
    expect(bucketLabel("0-30")).toBe("до 30 дней");
    expect(bucketLabel("31-60")).toBe("31–60 дней");
    expect(bucketLabel("61-90")).toBe("61–90 дней");
    expect(bucketLabel(">90")).toBe("больше 90 дней");
  });

  it("даёт подсказки по риску", () => {
    expect(bucketHint(">90")).toContain("риск");
    expect(bucketHint("0-30")).toContain("Свежие");
    expect([...BUCKETS].every((code) => (bucketHint(code) ?? "").length > 0)).toBe(true);
  });

  it("не теряет неизвестный код", () => {
    expect(bucketLabel("180+")).toBe("180+");
    expect(bucketHint("180+")).toBeNull();
  });

  it("все четыре корзины в порядке", () => {
    expect([...BUCKETS]).toEqual(["0-30", "31-60", "61-90", ">90"]);
  });
});

describe("состояния полноты", () => {
  it("переводит статусы", () => {
    expect(completenessLabel("unavailable")).toBe("Нет данных о продажах");
    expect(completenessLabel("preliminary")).toBe("Предварительно");
    expect(completenessLabel("full")).toBe("Полно");
    expect(completenessLabel(null)).toBe("Нет данных");
  });

  it("объясняет отсутствие данных без нулей", () => {
    expect(completenessNote("unavailable")).toContain("посчитать нельзя");
    expect(completenessNote("preliminary")).toContain("неполные");
    expect(completenessNote("full")).toContain("Все продажи");
  });

  it("распознаёт unavailable", () => {
    expect(isUnavailable("unavailable")).toBe(true);
    expect(isUnavailable("full")).toBe(false);
  });

  it("выделяет отсутствие источника продаж", () => {
    expect(hasMissingRevenueSource(["missing_revenue_source"])).toBe(true);
    expect(hasMissingRevenueSource(["partial_period"])).toBe(false);
    expect(flagNotes(["missing_revenue_source"])[0]).toContain("Источник продаж не подключён");
  });
});

describe("строки долгов", () => {
  it("показывает контрагента или честную подпись", () => {
    expect(counterpartyLabel({ name: "Synth AR One", inn: "7700000901" })).toBe(
      "Synth AR One (ИНН 7700000901)",
    );
    expect(counterpartyLabel(null)).toBe("Контрагент не указан");
    expect(counterpartyLabel({ name: "", inn: "" })).toBe("Контрагент не указан");
    expect(counterpartyLabel({ name: "Только имя", inn: "" })).toBe("Только имя");
    expect(counterpartyLabel({ name: "", inn: "7700000901" })).toBe("ИНН 7700000901");
  });

  it("собирает документ из номера и внешнего id", () => {
    expect(documentLabel({ number: "RD-A", external_id: "rd-r-a" })).toBe("RD-A · rd-r-a");
    expect(documentLabel({ number: "RD-A", external_id: null })).toBe("RD-A");
    expect(documentLabel({ number: "", external_id: "rd-r-a" })).toBe("rd-r-a");
    expect(documentLabel(null)).toBe("—");
  });
});

describe("orphan_return", () => {
  it("показывает отрицательную сумму с пояснением", () => {
    expect(formatMoney("-2000.00")).toBe("\u22122 000,00 ₽");
    expect(orphanTitle()).toBe("Возвраты без связанной продажи");
    expect(orphanNote()).toContain("знаком минус");
  });
});

describe("усечение строк", () => {
  it("предупреждает при достижении лимита", () => {
    const rows = Array.from({ length: ROWS_LIMIT }, (_, index) => ({ id: index }));
    expect(isRowsTruncated(rows, false)).toBe(true);
    expect(isRowsTruncated(rows.slice(0, 10), false)).toBe(false);
    expect(isRowsTruncated([], true)).toBe(true);
    expect(truncatedNotice()).toBe("Показаны не все строки (лимит 500). Сузьте дату среза.");
    expect(truncatedNotice()).toContain("500");
  });
});

describe("тексты экрана", () => {
  it("объясняет, что это долг, а не деньги", () => {
    expect(debtBasisNote()).toContain("не деньги на счёте");
    expect(emptyStateText()).toContain("долгов нет");
  });

  it("объясняет поступления без привязки", () => {
    expect(unallocatedTitle()).toBe("Поступления без привязки к продаже");
    expect(unallocatedNote()).toContain("не связаны");
  });

  it("строит подпись даты среза", () => {
    expect(asOfCaption("2026-10-31")).toBe("Долги на 31.10.2026");
  });
});

describe("дата среза в часовом поясе фирмы", () => {
  it("берёт дату по поясу, а не по браузеру", () => {
    const moment = new Date("2026-10-31T21:30:00Z");
    expect(todayInTimeZone("Europe/Moscow", moment)).toBe("2026-11-01");
    expect(todayInTimeZone("UTC", moment)).toBe("2026-10-31");
    expect(todayInTimeZone("Asia/Vladivostok", moment)).toBe("2026-11-01");
  });

  it("не падает без пояса", () => {
    expect(todayInTimeZone("", new Date("2026-10-31T10:00:00Z"))).toBe("2026-10-31");
  });
});

describe("ошибки по HTTP-статусу", () => {
  it("различает 403, 404, 422 и 402", () => {
    expect(receivableErrorText({ status: 403 })).toContain("Нет доступа");
    expect(receivableErrorText({ status: 404 })).toContain("не найдена");
    expect(receivableErrorText({ status: 422 })).toContain("дату среза");
    expect(receivableErrorText({ status: 402 })).toContain("тариф");
  });

  it("для сети даёт понятный текст", () => {
    expect(receivableErrorText(new Error("Failed to fetch"))).toContain("Не удалось загрузить");
  });

  it("показывает серверное сообщение при прочих статусах", () => {
    expect(receivableErrorText({ status: 500, message: "Сбой" })).toBe("Сбой");
  });
});

describe("денежная база", () => {
  it("считает копейки без float", () => {
    expect(toCents("47506.00")).toBe(4750600n);
    expect(toCents("-2000.00")).toBe(-200000n);
    expect(toCents("0.10")).toBe(10n);
  });

  it("складывает без потери копеек", () => {
    expect(sumMoney(["32501.00", "5002.00", "5002.00", "5001.00"])).toBe("47506.00");
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
  });
});
