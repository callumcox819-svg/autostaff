import type { XPartnersCountry, XPartnersQuickStats } from "./xpartners-client.js";

export type StatsRefreshHours = 1 | 3 | 5;

export type PartnerStatsCache = Partial<
  Record<XPartnersCountry, XPartnersQuickStats>
> & {
  cachedAt?: string;
};

export function defaultRefreshHours(): StatsRefreshHours {
  return 3;
}

export function cacheStale(
  cachedAt: string | undefined,
  refreshHours: StatsRefreshHours,
): boolean {
  if (!cachedAt) {
    return true;
  }
  const ageMs = Date.now() - Date.parse(cachedAt);
  if (!Number.isFinite(ageMs)) {
    return true;
  }
  return ageMs >= refreshHours * 60 * 60 * 1000;
}

const COUNTRY_LABEL: Record<XPartnersCountry, string> = {
  CM: "Cameroon",
  EG: "Egypt",
  ZM: "Zambia",
  RW: "Rwanda",
};

const TELEGRAM_HTML_MAX = 4096;

export function formatPlayersIdsMessageParts(
  country: XPartnersCountry,
  exportData: {
    dayKey: string;
    siteLabel: string;
    playerIds: string[];
    registrationsExpected?: number;
  },
): string[] {
  const { dayKey, siteLabel, playerIds, registrationsExpected } = exportData;
  const label = COUNTRY_LABEL[country];
  const countLine =
    registrationsExpected != null &&
    registrationsExpected > 0 &&
    playerIds.length !== registrationsExpected
      ? `<b>Кол-во:</b> ${playerIds.length} <i>(в сводке рег: ${registrationsExpected})</i>`
      : `<b>Кол-во:</b> ${playerIds.length}`;
  const headerLines = [
    `<b>1xPartners · ID регистраций · ${label}</b>`,
    `<b>Сайт:</b> <code>${escapeHtml(siteLabel)}</code>`,
    `<b>Период:</b> сегодня (USD) · ${dayKey}`,
    countLine,
    "",
  ];
  if (
    registrationsExpected != null &&
    registrationsExpected > playerIds.length &&
    playerIds.length > 0
  ) {
    headerLines.splice(
      headerLines.length - 1,
      0,
      "<i>Не все ID регистраций (не FTD): обновите cookie на странице «Отчёт по игрокам» → graphql → Cookie, переменная XPARTNERS_REPORTS_COOKIE в Railway.</i>",
      "",
    );
  }
  if (!playerIds.length) {
    return [
      [
        ...headerLines.slice(0, -1),
        "",
        "За сегодня ID не найдены (как в отчёте «По игрокам»).",
      ].join("\n"),
    ];
  }

  const parts: string[] = [];
  let chunk: string[] = [];
  const flush = (isFirst: boolean) => {
    const prefix = isFirst ? headerLines.join("\n") : `<b>${label} · ID (продолжение)</b>\n\n`;
    parts.push(`${prefix}<code>${escapeHtml(chunk.join("\n"))}</code>`);
    chunk = [];
  };

  let isFirst = true;
  for (const id of playerIds) {
    const trial = [...chunk, id];
    const prefix = isFirst ? headerLines.join("\n") : `<b>${label} · ID (продолжение)</b>\n\n`;
    const trialMsg = `${prefix}<code>${escapeHtml(trial.join("\n"))}</code>`;
    if (trialMsg.length > TELEGRAM_HTML_MAX && chunk.length > 0) {
      flush(isFirst);
      isFirst = false;
      chunk.push(id);
    } else {
      chunk = trial;
    }
  }
  if (chunk.length) {
    flush(isFirst);
  }
  return parts;
}

export function formatPlayersIdsMessage(
  country: XPartnersCountry,
  exportData: { dayKey: string; siteLabel: string; playerIds: string[] },
): string {
  return formatPlayersIdsMessageParts(country, exportData)[0] ?? "";
}

export function formatAllCountriesStats(
  byCountry: Partial<Record<XPartnersCountry, XPartnersQuickStats>>,
  refreshHours: StatsRefreshHours,
): string {
  const lines = [
    "<b>1xPartners · все страны · сегодня (USD)</b>",
    "",
  ];
  for (const country of ["CM", "EG", "ZM", "RW"] as const) {
    const stats = byCountry[country];
    if (!stats) {
      lines.push(`${COUNTRY_LABEL[country]}: <i>нет данных</i>`);
      continue;
    }
    lines.push(
      `<b>${COUNTRY_LABEL[country]}</b> · рег: ${stats.registrations} · FTD: ${stats.newAccountsWithDeposits}`,
    );
  }
  const latest = Object.values(byCountry)
    .map((s) => s?.fetchedAt)
    .filter(Boolean)
    .sort()
    .at(-1);
  const when = latest ? new Date(latest) : new Date();
  const timeStr = Number.isFinite(when.getTime())
    ? when.toLocaleString("ru-RU", { timeZone: "Europe/Kyiv" })
    : "";
  lines.push("", `<i>Обновлено: ${escapeHtml(timeStr)} · авто-кэш: ${refreshHours} ч</i>`);
  return lines.join("\n");
}

export function formatStatsMessage(
  country: XPartnersCountry,
  stats: XPartnersQuickStats,
  refreshHours: StatsRefreshHours,
): string {
  const when = new Date(stats.fetchedAt);
  const timeStr = Number.isFinite(when.getTime())
    ? when.toLocaleString("ru-RU", { timeZone: "Europe/Kyiv" })
    : stats.fetchedAt;
  return [
    `<b>1xPartners · ${COUNTRY_LABEL[country]}</b>`,
    `<b>Сайт:</b> <code>${escapeHtml(stats.siteLabel)}</code>`,
    `<b>Период:</b> Сегодня (USD)`,
    "",
    `<b>Регистрации:</b> ${stats.registrations}`,
    `<b>Новые с депозитом (FTD):</b> ${stats.newAccountsWithDeposits}`,
    "",
    `<i>Обновлено: ${escapeHtml(timeStr)} · авто-кэш: ${refreshHours} ч</i>`,
  ].join("\n");
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function parseRefreshHours(value: string | undefined): StatsRefreshHours {
  const n = Number(value);
  if (n === 1 || n === 3 || n === 5) {
    return n;
  }
  return defaultRefreshHours();
}
