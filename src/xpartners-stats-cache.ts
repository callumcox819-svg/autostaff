import type { AppMetaStore } from "./app-meta-store.js";
import type { XPartnersCountry, XPartnersQuickStats } from "./xpartners-client.js";
import { defaultRefreshHours, type StatsRefreshHours } from "./xpartners-stats-ui.js";

export const XPARTNERS_STATS_META_KEY = "xpartners_stats_cache";

export type GlobalPartnerStatsState = {
  refreshIntervalHours: StatsRefreshHours;
  cachedAt?: string;
  byCountry?: Partial<Record<XPartnersCountry, XPartnersQuickStats>>;
};

export async function loadGlobalPartnerStats(meta: AppMetaStore): Promise<GlobalPartnerStatsState> {
  const raw = (await meta.get(XPARTNERS_STATS_META_KEY))?.trim();
  if (!raw) {
    return { refreshIntervalHours: defaultRefreshHours() };
  }
  try {
    const parsed = JSON.parse(raw) as GlobalPartnerStatsState;
    return {
      refreshIntervalHours: parsed.refreshIntervalHours ?? defaultRefreshHours(),
      cachedAt: parsed.cachedAt,
      byCountry: parsed.byCountry,
    };
  } catch {
    return { refreshIntervalHours: defaultRefreshHours() };
  }
}

export async function saveGlobalPartnerStats(
  meta: AppMetaStore,
  state: GlobalPartnerStatsState,
): Promise<void> {
  await meta.set(XPARTNERS_STATS_META_KEY, JSON.stringify(state));
}
