import type { CompanyRef } from "../lib/companySelection";

type Props = {
  list: CompanyRef[];
  value: string;
  needsPlaceholder: boolean;
  disabled?: boolean;
  onSelect: (companyId: string) => void;
};

export function CompanyWritePicker({
  list,
  value,
  needsPlaceholder,
  disabled,
  onSelect,
}: Props) {
  if (list.length === 0) {
    return <p className="mb-4 text-sm text-slate-600">Нет доступной фирмы.</p>;
  }

  return (
    <div className="mb-4">
      <label className="text-sm">
        Фирма
        <select
          className="mt-1 block rounded border px-3 py-1 disabled:opacity-50"
          value={value}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value)}
        >
          {needsPlaceholder ? (
            <option value="">— выберите фирму —</option>
          ) : null}
          {list.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {needsPlaceholder && !value ? (
        <p className="mt-2 text-sm text-amber-800">Выберите фирму, чтобы загрузить и сохранить данные.</p>
      ) : null}
    </div>
  );
}
