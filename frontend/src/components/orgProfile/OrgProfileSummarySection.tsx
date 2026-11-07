import type { OrganizationProfile } from "../../api";
import { Banner } from "../system/Banner";
import { buildExportPreviewLines } from "../../lib/orgProfileExportPreview";
import { profileSummaryRows } from "../../lib/orgProfileDisplay";
import { orgProfileMissingLabel, orgProfileSupportBanner } from "../../lib/orgProfileMessages";

type Props = {
  profile: OrganizationProfile;
  showMissing?: boolean;
};

export function OrgProfileSummarySection({ profile, showMissing = false }: Props) {
  const rows = profileSummaryRows(profile);
  const exports = buildExportPreviewLines({
    money_channels: profile.money_channels,
    industry_sphere: profile.industry_sphere,
    accounting_source: profile.accounting_source,
    vat_status: profile.vat_status,
    usn_tax_object: profile.usn_tax_object,
  });
  const supportText = orgProfileSupportBanner(profile.support_code);
  const missing = profile.confirm_readiness.missing ?? [];

  return (
    <div className="space-y-4">
      <h3 className="text-heading">Итоговая сводка</h3>
      <dl className="space-y-2 rounded-card border border-line bg-surface p-card">
        {rows.map((row) => (
          <div key={row.field} className="grid gap-1 sm:grid-cols-2">
            <dt className="text-caption text-muted">{row.label}</dt>
            <dd className="text-body">{row.value}</dd>
          </div>
        ))}
      </dl>
      {supportText ? (
        <Banner tone="info" label="Поддержка профиля">
          {supportText}
        </Banner>
      ) : null}
      {showMissing && missing.length > 0 ? (
        <div className="rounded-card border border-line bg-surface p-card">
          <p className="text-body font-medium">Не хватает для подтверждения:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-body">
            {missing.map((field) => (
              <li key={field}>{orgProfileMissingLabel(field)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="rounded-card border border-line bg-surface p-card">
        <h4 className="text-body font-medium">Рекомендуемые выгрузки</h4>
        <p className="mt-1 text-caption text-muted">Период — календарный месяц (FA-R03.2).</p>
        {exports.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-body">
            {exports.map((line) => (
              <li key={line.title}>
                {line.title}
                <span className="text-caption text-muted"> · {line.period}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-body text-muted">Укажите каналы денег, чтобы увидеть список.</p>
        )}
      </div>
    </div>
  );
}
