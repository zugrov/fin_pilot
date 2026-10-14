import { useQuery } from "@tanstack/react-query";

import { listCompanies, loadWallets } from "../api";
import { Shell } from "../components/Shell";

export function WalletsPage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const wallets = useQuery({
    queryKey: ["wallets", companyId],
    queryFn: () => loadWallets(companyId ?? ""),
    enabled: Boolean(companyId),
  });

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Кошельки</h1>
      {wallets.isLoading ? <p>Загрузка</p> : null}
      {wallets.isError ? <p className="text-red-700">Не удалось загрузить кошельки.</p> : null}
      {wallets.data?.wallets.length === 0 ? <p>Кошельков нет.</p> : null}
      <ul className="space-y-2">
        {wallets.data?.wallets.map((wallet) => (
          <li key={wallet.id} className="rounded-xl border bg-white p-4">
            {wallet.name}
            {wallet.code ? <span className="ml-2 text-sm text-slate-600">{wallet.code}</span> : null}
          </li>
        ))}
      </ul>
    </Shell>
  );
}
