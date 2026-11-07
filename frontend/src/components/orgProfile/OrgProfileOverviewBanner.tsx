import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { loadOrganizationProfile } from "../../api";
import { Banner } from "../system/Banner";
import { currentPeriodMonth } from "../../lib/orgProfileWizardPlan";

type Props = {
  companyId: string;
  timeZone: string;
};

export function OrgProfileOverviewBanner({ companyId, timeZone }: Props) {
  const period = currentPeriodMonth(timeZone);
  const profile = useQuery({
    queryKey: ["organization-profile", companyId, period],
    queryFn: () => loadOrganizationProfile(companyId, period),
    enabled: Boolean(companyId),
    staleTime: 60_000,
    retry: 1,
  });

  if (!companyId || profile.isLoading || profile.isError || !profile.data) {
    return null;
  }

  if (!profile.data.profile_unconfirmed) {
    return null;
  }

  const canWrite = profile.data.can_write;

  return (
    <div className="mb-4" data-testid="org-profile-overview-banner">
      <Banner tone="warn" label="Профиль организации не подтверждён">
        <p className="text-body">
          Налоговые подсказки и часть разрезов могут быть неточными до подтверждения профиля.
        </p>
        {canWrite ? (
          <Link
            to="/settings/org-profile"
            className="mt-2 inline-block min-h-tap rounded bg-accent px-4 py-2 text-on-accent"
          >
            Настроить профиль
          </Link>
        ) : (
          <p className="mt-2 text-body text-muted">
            Попросите владельца или бухгалтера подтвердить профиль.
          </p>
        )}
      </Banner>
    </div>
  );
}
