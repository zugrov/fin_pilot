/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Смысловые роли. Названия описывают значение, не оттенок.
        ink: {
          DEFAULT: "#0f172a", // основной текст
          muted: "#475569", // подписи, 7.58:1 на белом
          subtle: "#64748b", // сноски, 4.76:1 на белом (только от 14px)
        },
        canvas: "#f8fafc",
        surface: "#ffffff",
        line: "#e2e8f0",
        // Поступления и списания: цвет + знак, никогда только цвет.
        inflow: { DEFAULT: "#047857", soft: "#ecfdf5", line: "#a7f3d0" },
        outflow: { DEFAULT: "#b91c1c", soft: "#fef2f2", line: "#fecaca" },
        warn: { DEFAULT: "#b45309", soft: "#fffbeb", line: "#fcd34d" },
        danger: { DEFAULT: "#b91c1c", soft: "#fef2f2", line: "#fecaca" },
        info: { DEFAULT: "#1d4ed8", soft: "#eff6ff", line: "#bfdbfe" },
        focus: "#2563eb",
        // Бренд-акцент: бирюзово-тёмный, для активного пункта меню и логотипа.
        brand: { DEFAULT: "#0f766e", soft: "#ccfbf1", line: "#99f6e4" },
        // Светлое боковое меню (как в референсе Equinox): белый фон, тёмный текст.
        rail: {
          DEFAULT: "#ffffff",
          hover: "#f1f5f9",
          active: "#ccfbf1",
          text: "#475569",
          strong: "#0f172a",
          border: "#e2e8f0",
        },
        // Серии графиков: различимые оттенки для легенд и долей кольца.
        series: {
          "1": "#0f766e",
          "2": "#1d4ed8",
          "3": "#b45309",
          "4": "#b91c1c",
          "5": "#6d28d9",
          "6": "#475569",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      fontSize: {
        // Шкала: сноска / тело / заголовок карточки / заголовок страницы / KPI.
        note: ["0.75rem", { lineHeight: "1rem" }],
        body: ["0.875rem", { lineHeight: "1.375rem" }],
        label: ["0.8125rem", { lineHeight: "1.125rem", fontWeight: "500" }],
        title: ["1.5rem", { lineHeight: "2rem", fontWeight: "600" }],
        kpi: ["1.875rem", { lineHeight: "2.25rem", fontWeight: "600" }],
      },
      spacing: {
        // Три уровня отступов вместо 20 разных.
        card: "1rem", // внутри карточки
        section: "1.5rem", // между карточками
        page: "2rem", // между блоками страницы
      },
      borderRadius: {
        control: "6px", // поля, кнопки
        card: "12px", // карточки, таблицы
      },
      boxShadow: {
        card: "0 1px 2px rgb(15 23 42 / 0.04)",
        pop: "0 8px 24px rgb(15 23 42 / 0.08)",
      },
      minHeight: {
        tap: "40px", // цель нажатия
      },
      minWidth: {
        tap: "40px",
      },
    },
  },
  plugins: [],
};
