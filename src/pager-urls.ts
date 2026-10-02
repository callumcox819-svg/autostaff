const LEGACY_PAGER_WEB_HOSTS = new Set(["www.pager.co.ua", "pager.co.ua"]);
const PAGER_API_ORIGIN = "https://api.pager.co.ua";
const PAGER_WEB_ORIGIN = "https://www.pager.co.ua";

function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, "");
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** REST `/api/*` calls — Pager moved these off www to api.pager.co.ua. */
export function resolvePagerApiBaseUrl(baseUrl: string): string {
  const normalized = stripTrailingSlash(baseUrl.trim());
  if (!normalized) {
    return PAGER_API_ORIGIN;
  }
  const host = hostOf(normalized);
  if (LEGACY_PAGER_WEB_HOSTS.has(host)) {
    return PAGER_API_ORIGIN;
  }
  return normalized;
}

/** Browser Origin / Referer / HTML warm-up — stays on www. */
export function resolvePagerWebBaseUrl(baseUrl: string, webBaseUrl?: string): string {
  const explicit = webBaseUrl?.trim();
  if (explicit) {
    return stripTrailingSlash(explicit);
  }
  const normalized = stripTrailingSlash(baseUrl.trim());
  if (!normalized || hostOf(normalized) === "api.pager.co.ua") {
    return PAGER_WEB_ORIGIN;
  }
  return normalized;
}

export function parsePagerMovedEndpoint(body: string): string | undefined {
  const trimmed = (body || "").trim();
  if (!trimmed) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(trimmed) as { message?: string };
    const fromMessage = extractUrlFromPagerMigrationMessage(parsed.message ?? "");
    if (fromMessage) {
      return fromMessage;
    }
  } catch {
    // fall through to raw body scan
  }
  return extractUrlFromPagerMigrationMessage(trimmed);
}

function extractUrlFromPagerMigrationMessage(message: string): string | undefined {
  const match = message.match(/https?:\/\/[^\s"'<>]+/i);
  if (!match) {
    return undefined;
  }
  return stripTrailingSlash(match[0].replace(/[.,;:!?)]+$/, ""));
}
