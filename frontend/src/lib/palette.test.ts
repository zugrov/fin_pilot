import { describe, expect, it } from "vitest";

/** Контраст по WCAG 2.1: (L1 + 0.05) / (L2 + 0.05). */

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const r = Number.parseInt(h.slice(0, 2), 16);
  const g = Number.parseInt(h.slice(2, 4), 16);
  const b = Number.parseInt(h.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

const INK = "#0f172a";
const INK_MUTED = "#475569";
const INK_SUBTLE = "#64748b";
const SURFACE = "#ffffff";
const CANVAS = "#f8fafc";

describe("контраст текста ≥ 4,5:1", () => {
  it("основной текст на поверхностях", () => {
    expect(contrast(INK, SURFACE)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(INK, CANVAS)).toBeGreaterThanOrEqual(4.5);
  });

  it("подписи и сноски", () => {
    expect(contrast(INK_MUTED, SURFACE)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(INK_MUTED, CANVAS)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(INK_SUBTLE, SURFACE)).toBeGreaterThanOrEqual(4.5);
  });

  it("смысловые цвета на своих фонах", () => {
    expect(contrast("#047857", SURFACE)).toBeGreaterThanOrEqual(4.5); // inflow
    expect(contrast("#b91c1c", SURFACE)).toBeGreaterThanOrEqual(4.5); // outflow/danger
    expect(contrast("#b45309", SURFACE)).toBeGreaterThanOrEqual(4.5); // warn
    expect(contrast("#b45309", "#fffbeb")).toBeGreaterThanOrEqual(4.5); // warn на своём фоне
    expect(contrast("#1d4ed8", SURFACE)).toBeGreaterThanOrEqual(4.5); // info
  });

  it("кольцо фокуса видно на фоне страницы", () => {
    expect(contrast("#2563eb", CANVAS)).toBeGreaterThanOrEqual(3);
  });
});

describe("светлое боковое меню и бренд-акцент", () => {
  const BRAND = "#0f766e";
  const BRAND_SOFT = "#ccfbf1";
  const RAIL_TEXT = "#475569";

  it("текст пунктов меню читается на белом фоне", () => {
    expect(contrast(RAIL_TEXT, SURFACE)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(INK, SURFACE)).toBeGreaterThanOrEqual(4.5);
  });

  it("активный пункт: бренд-текст на мягкой подложке", () => {
    expect(contrast(BRAND, BRAND_SOFT)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(BRAND, SURFACE)).toBeGreaterThanOrEqual(4.5);
  });

  it("логотип: белый знак на бренд-плашке", () => {
    expect(contrast(SURFACE, BRAND)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("ступени тепловой карты дебиторки", () => {
  const steps = [
    { fill: "#f0fdf4", border: "#047857", text: INK },
    { fill: "#6ee7b7", border: "#047857", text: INK },
    { fill: "#047857", border: "#f8fafc", text: SURFACE },
    { fill: "#134e4a", border: "#f8fafc", text: SURFACE },
  ];

  it("каждая ступень отличима рамкой ≥ 3:1", () => {
    for (const step of steps) {
      expect(contrast(step.fill, step.border)).toBeGreaterThanOrEqual(3);
    }
  });

  it("текст на каждой ступени читается ≥ 4,5:1", () => {
    for (const step of steps) {
      expect(contrast(step.text, step.fill)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("шкала монотонна: светлое к тёмному", () => {
    const luminances = steps.map((step) => luminance(step.fill));
    for (let i = 1; i < luminances.length; i += 1) {
      expect(luminances[i]).toBeLessThan(luminances[i - 1]);
    }
  });

  it("4 ступени с шагом 3:1 физически невозможны — зафиксировано осознанно", () => {
    // Максимум ч/б = 21:1; для 4 ступеней с шагом 3 нужен диапазон 27:1.
    const maxPossible = contrast("#000000", "#ffffff");
    expect(maxPossible).toBeLessThan(3 ** 3);
    // Поэтому различимость обеспечивается рамкой, а не соседними заливками.
  });
});
