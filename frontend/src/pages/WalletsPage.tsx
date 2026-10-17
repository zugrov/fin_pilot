import { useQuery } from "@tanstack/react-query";

import { listCompanies, loadWallets } from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { companyScopedData, useWritableCompanySelection } from "../lib/companySelection";

export function WalletsPage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const selection = useWritableCompanySelection(companies.data?.companies);
  const { companyId } = selection;
  const wallets = useQuery({
    queryKey: ["wallets", companyId],
    queryFn: () => loadWallets(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const list = companyScopedData(companyId, companyId ?? undefined, wallets.data?.wallets);

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Кошельки</h1>
      <CompanyWritePicker
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        onSelect={selection.onSelect}
      />
      {companyId && wallets.isLoading ? <p>Загрузка</p> : null}
      {companyId && wallets.isError ? <p className="text-red-700">Не удалось загрузить кошельки.</p> : null}
      {list?.length === 0 ? <p>Кошельков нет.</p> : null}
      <ul className="space-y-2">
        {list?.map((wallet) => (
          <li key={wallet.id} className="rounded-xl border bg-white p-4">
            {wallet.name}
            {wallet.code ? <span className="ml-2 text-sm text-slate-600">{wallet.code}</span> : null}
          </li>
        ))}
      </ul>
    </Shell>
  );
}
