import type { RefObject } from "react";

import type { OrganizationProfile, OrganizationProfileVersion } from "../../api";
import { formatDate } from "../../lib/dates";
import { OrgProfileSummarySection } from "./OrgProfileSummarySection";

const ROLE_LABELS: Record<string, string> = {
  owner: "владелец",
  accountant: "бухгалтер",
};

type Props = {
  profile: OrganizationProfile;
  versions: OrganizationProfileVersion[] | undefined;
  readOnly: boolean;
  onChangeMode: () => void;
  changeModeButtonRef?: RefObject<HTMLButtonElement>;
};

export function OrgProfileCardPanel({
  profile,
  versions,
  readOnly,
  onChangeMode,
  changeModeButtonRef,
}: Props) {
  const role = profile.confirmed_role
    ? (ROLE_LABELS[profile.confirmed_role] ?? profile.confirmed_role)
    : "—";

  return (
    <div className="space-y-6">
      <div className="rounded-card border border-line bg-surface p-card">
        <p className="text-body">
          Подтверждено {profile.confirmed_at ? formatDate(profile.confirmed_at.slice(0, 10)) : "—"},
          роль: {role}. Действует с {formatDate(profile.effective_from)}.
        </p>
        {!readOnly ? (
          <button
            ref={changeModeButtonRef}
            type="button"
            className="mt-4 rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
            onClick={onChangeMode}
          >
            Изменить режим с даты…
          </button>
        ) : null}
      </div>
      <OrgProfileSummarySection profile={profile} />
      <section className="rounded-card border border-line bg-surface p-card">
        <h3 className="text-heading">История версий</h3>
        {!versions?.length ? (
          <p className="mt-2 text-body text-muted">Версий пока нет.</p>
        ) : (
          <table className="mt-3 w-full text-left text-body">
            <thead>
              <tr className="text-caption text-muted">
                <th className="pb-2">С даты</th>
                <th className="pb-2">Статус</th>
                <th className="pb-2">Подтверждение</th>
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((row) => (
                <tr key={row.version_id} className="border-t border-line">
                  <td className="py-2">{formatDate(row.effective_from)}</td>
                  <td className="py-2">{row.is_confirmed ? "Подтверждена" : "Черновик"}</td>
                  <td className="py-2 text-caption text-muted">
                    {row.confirmed_at
                      ? formatDate(row.confirmed_at.slice(0, 10))
                      : row.change_reason ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
