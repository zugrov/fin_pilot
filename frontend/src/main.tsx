import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import "./index.css";
import { BillingPage, BillingReturnPage } from "./pages/BillingPage";
import { ForgotPage, LoginPage, RegisterPage, ResetPage, VerifyPage } from "./pages/AuthPages";
import { AlertsPage } from "./pages/AlertsPage";
import { BudgetsPage } from "./pages/BudgetsPage";
import { CalendarPage } from "./pages/CalendarPage";
import { CashflowPage } from "./pages/CashflowPage";
import { ClassificationPage } from "./pages/ClassificationPage";
import { ForecastPage } from "./pages/ForecastPage";
import { ImportPage } from "./pages/ImportPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReceivablePage } from "./pages/ReceivablePage";
import { SalesPage } from "./pages/SalesPage";
import { TelegramPage } from "./pages/TelegramPage";
import { WalletsPage } from "./pages/WalletsPage";

const router = createBrowserRouter([
  { path: "/", element: <OverviewPage /> },
  { path: "/overview", element: <OverviewPage /> },
  { path: "/cashflow", element: <CashflowPage /> },
  { path: "/receivables", element: <ReceivablePage /> },
  { path: "/wallets", element: <WalletsPage /> },
  { path: "/sales", element: <SalesPage /> },
  { path: "/calendar", element: <CalendarPage /> },
  { path: "/classification", element: <ClassificationPage /> },
  { path: "/forecast", element: <ForecastPage /> },
  { path: "/budgets", element: <BudgetsPage /> },
  { path: "/alerts", element: <AlertsPage /> },
  { path: "/import", element: <ImportPage /> },
  { path: "/telegram", element: <TelegramPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/verify-email", element: <VerifyPage /> },
  { path: "/forgot-password", element: <ForgotPage /> },
  { path: "/reset-password", element: <ResetPage /> },
  { path: "/billing", element: <BillingPage /> },
  { path: "/billing/return", element: <BillingReturnPage /> },
]);

const queryClient = new QueryClient();
const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}
