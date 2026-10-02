import makeFetchCookie from "fetch-cookie";
import { CookieJar } from "tough-cookie";
import type { AppEnv } from "./env.js";
import { shouldFetchStatsFromApi, shouldPreferGraphqlApi } from "./env.js";
import type { AppMetaStore } from "./app-meta-store.js";

export const XPARTNERS_SESSION_META_KEY = "xpartners_session_cookie";
export const XPARTNERS_LOGIN_META_KEY = "xpartners_login";
export const XPARTNERS_PASSWORD_META_KEY = "xpartners_password";

export type XPartnersSessionStatus = {
  connected: boolean;
  source: "cookie" | "credentials" | "env" | "none";
  loginHint?: string;
  hasStoredCookie: boolean;
  hasStoredCredentials: boolean;
  hasEnvCookie: boolean;
  hasEnvCredentials: boolean;
  captchaBlockedUntil?: string;
  message: string;
};

export type XPartnersCountry = "CM" | "EG" | "ZM" | "RW";

export type XPartnersQuickStats = {
  registrations: number;
  newAccountsWithDeposits: number;
  fetchedAt: string;
  siteLabel: string;
};

export type XPartnersPlayersToday = {
  country: XPartnersCountry;
  dayKey: string;
  siteLabel: string;
  playerIds: string[];
  registrationsExpected: number;
  fetchedAt: string;
};

const COUNTRY_API_NAME: Record<XPartnersCountry, string> = {
  CM: "Cameroon",
  EG: "Egypt",
  ZM: "Zambia",
  RW: "Rwanda",
};

type GraphQlBatchItem = {
  operationName: string;
  variables?: Record<string, unknown>;
  query: string;
};

const BASE = "https://1xpartners.com";
const MULTI_BASE = "https://multi.1xpartners.com";
const MULTI_REST = `${MULTI_BASE}/rest`;
const MULTI_REST_LAPI = `${MULTI_BASE}/rest/lapi`;
const MULTI_WEB_UI = `${MULTI_BASE}/web/PartnerAccountWeb3Ui`;
const GRAPHQL = `${BASE}/graphql/`;
const XP_FETCH_TIMEOUT_MS = 90_000;
const MULTI_REST_TIMEOUT_MS = 25_000;
const MULTI_REFRESH_TIMEOUT_MS = 12_000;
const MULTI_REFRESH_BACKOFF_MS = 10 * 60_000;
const MULTI_API_VERSION = 13;

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  Accept: "application/json",
  "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
};

const SIGN_IN_MUTATION = `
mutation SignIn($login: String!, $password: String!, $recaptcha: String!, $likePartner: Boolean, $isOwnCaptcha: Boolean) {
  authorization {
    signIn(login: $login, password: $password, recaptcha: $recaptcha, likePartner: $likePartner, isOwnCaptcha: $isOwnCaptcha) {
      user { id }
      twoFactorAuthNeeded
    }
  }
}`;

const GET_AUTH_STATE = `
query GetAuthState {
  authorized {
    partnerAccount {
      twoFA { state { enabled } }
    }
  }
}`;

const PARTNER_SITES = `
query PartnerSites($filter: SitesFilter!) {
  authorized {
    partnerAndManager {
      data {
        sites(filter: $filter) { id name hidden }
      }
    }
  }
}`;

const GET_QUICK_REPORT = `
query GetQuickReport($filter: QuickReportFilter!) {
  authorized {
    partner {
      reports {
        quickReport(filter: $filter) {
          status
          total {
            countOfViews
            countOfClicks
            countOfDirectLinks
            countOfRegistrations
            countOfRegistrationsWithDeposits
            newDepositsSum
            newDepositors
            countOfAccountsWithDeposits
            depositAmount
            profit
            countOfDeposits
            countOfActivePlayers
          }
        }
      }
    }
  }
}`;

const GET_SUBPARTNER_REPORT = `
query GetSubpartnerReport($filter: SubpartnerReportFilter!) {
  authorized {
    partner {
      reports {
        subpartnerReport(filter: $filter) {
          status
          hash
          pagesCount
          rows {
            subPartnerId
            siteName
            siteId
            countOfRegistrations
            countOfNewAccountsWithDeposits
            registrationDate
          }
          total {
            countOfRegistrations
            countOfNewAccountsWithDeposits
          }
        }
      }
    }
  }
}`;

const GET_PLAYERS_REPORT = `
query GetPlayersReport($filter: PlayersReportFilter!) {
  authorized {
    partner {
      reports {
        playersReport(filter: $filter) {
          status
          hash
          pagesCount
          rows {
            playerId
            registrationDate
            depositAmount
            siteName
            siteId
          }
        }
      }
    }
  }
}`;

const SITE_HINTS: Record<XPartnersCountry, string[]> = {
  CM: ["camerun", "cameroon"],
  EG: ["egypt", "egypt0011", "eg011", "hapka"],
  ZM: ["zambia", "zam"],
  RW: ["rwanda", "ruanda", "rw"],
};

const DEFAULT_SITE_URL: Record<XPartnersCountry, string> = {
  CM: "http://Camerun.com",
  EG: "http://Egypt.com",
  ZM: "http://Zambia.com",
  RW: "http://Rwanda.com",
};

/** Same calendar day as 1xPartners UI (moment startOf/endOf day in partner TZ). */
const XP_REPORT_TIMEZONE = "Europe/Kyiv";

/** Partner UI normalizes start/end to the same UTC midnight for "today". */
function quickReportTodayPeriod(): { startPeriod: string; endPeriod: string } {
  const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: XP_REPORT_TIMEZONE }).format(new Date());
  const midnight = `${dayKey}T00:00:00.000Z`;
  return {
    startPeriod: midnight,
    endPeriod: midnight,
  };
}

function todayDayKey(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: XP_REPORT_TIMEZONE }).format(new Date());
}

/** Registration date column in partner UI (YYYY-MM-DD). */
function registrationDayKey(registrationDate: string | undefined): string | null {
  if (!registrationDate?.trim()) {
    return null;
  }
  const raw = registrationDate.trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    return raw.slice(0, 10);
  }
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) {
    return null;
  }
  return new Intl.DateTimeFormat("en-CA", { timeZone: XP_REPORT_TIMEZONE }).format(new Date(ms));
}

/** «Сегодня» в отчёте «По игрокам»: startOf/endOf day → ISO (как moment в кабинете). */
function playersReportTodayPeriodFullDay(): { startPeriod: string; endPeriod: string } {
  const dayKey = todayDayKey();
  const start = `${dayKey}T00:00:00.000Z`;
  return {
    startPeriod: start,
    endPeriod: `${dayKey}T23:59:59.999Z`,
  };
}

function todayReportPeriodVariants(): Array<{ startPeriod: string; endPeriod: string }> {
  const quick = quickReportTodayPeriod();
  return [quick, playersReportTodayPeriodFullDay()];
}

type PlayersReportRow = {
  playerId?: string | number;
  registrationDate?: string;
  depositAmount?: string | number | null;
  siteName?: string;
  siteId?: number | string;
};

type SubpartnerReportRow = {
  subPartnerId?: string | number;
  siteName?: string;
  siteId?: number | string;
  countOfRegistrations?: number;
  countOfNewAccountsWithDeposits?: number;
  registrationDate?: string;
};

function usesSubpartnerStats(env: AppEnv): boolean {
  return env.XPARTNERS_STATS_SOURCE === "subpartners";
}

function subpartnerRowMatchesCountry(
  row: SubpartnerReportRow,
  country: XPartnersCountry,
  env: AppEnv,
): boolean {
  const overrideId = siteIdOverride(env, country);
  const siteId = Number(row.siteId);
  if (overrideId && siteId === overrideId) {
    return true;
  }
  const wantUrl = siteUrlForCountry(env, country).toLowerCase();
  const name = (row.siteName || "").trim().toLowerCase();
  if (!name) {
    return false;
  }
  if (name === wantUrl) {
    return true;
  }
  return SITE_HINTS[country].some((hint) => name.includes(hint));
}

function resolveCurrencyId(env: AppEnv): number {
  const raw = Number(env.XPARTNERS_CURRENCY_ID || 6);
  // Railway often kept legacy default 1; USD in partner UI is 6.
  if (raw === 1) {
    return 6;
  }
  return raw > 0 ? raw : 6;
}

/** multi.1xpartners.com cabinet uses accessToken cookies + /rest/lapi (not 1xpartners.com/graphql). */
function usesMultiRestAuth(cookieHeader: string | null | undefined): boolean {
  return Boolean(cookieHeader?.includes("accessToken="));
}

function multiRestTodayPeriod(): { startPeriod: string; endPeriod: string } {
  const dayKey = todayDayKey();
  return { startPeriod: dayKey, endPeriod: dayKey };
}

function pickNumericField(obj: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const raw = obj[key];
    if (raw == null || raw === "") {
      continue;
    }
    const n = Number(raw);
    if (Number.isFinite(n)) {
      return n;
    }
  }
  return undefined;
}

function parseRestQuickReportTotals(data: unknown): QuickReportTotals {
  let best: QuickReportTotals = {};
  const walk = (value: unknown, depth = 0): void => {
    if (depth > 12 || value == null) {
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        walk(item, depth + 1);
      }
      return;
    }
    if (typeof value !== "object") {
      return;
    }
    const obj = value as Record<string, unknown>;
    const registrations = pickNumericField(obj, [
      "countOfRegistrations",
      "CountOfRegistrations",
      "registrations",
      "Registrations",
    ]);
    const hasRegistrationField =
      registrations != null ||
      "countOfRegistrations" in obj ||
      "CountOfRegistrations" in obj ||
      "registrations" in obj ||
      "Registrations" in obj;
    if (hasRegistrationField) {
      const candidate: QuickReportTotals = {
        countOfRegistrations: registrations ?? 0,
        newDepositors: pickNumericField(obj, ["newDepositors", "NewDepositors", "newDepositsCount", "NewDepositsCount"]),
        countOfRegistrationsWithDeposits: pickNumericField(obj, [
          "countOfRegistrationsWithDeposits",
          "CountOfRegistrationsWithDeposits",
        ]),
        countOfAccountsWithDeposits: pickNumericField(obj, [
          "countOfAccountsWithDeposits",
          "CountOfAccountsWithDeposits",
        ]),
      };
      const score = Number(candidate.countOfRegistrations ?? 0) + Number(candidate.newDepositors ?? 0);
      const bestScore = Number(best.countOfRegistrations ?? 0) + Number(best.newDepositors ?? 0);
      if (score >= bestScore) {
        best = candidate;
      }
    }
    for (const nested of Object.values(obj)) {
      walk(nested, depth + 1);
    }
  };
  walk(data);
  return best;
}

function collectSiteLikeObjects(
  value: unknown,
  out: Array<{ id: number; name: string }>,
  depth = 0,
): void {
  if (depth > 12 || value == null) {
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === "object") {
        const obj = item as Record<string, unknown>;
        const id = Number(obj.id ?? obj.siteId ?? obj.SiteId ?? obj.websiteId ?? obj.WebsiteId);
        const name = String(obj.name ?? obj.siteName ?? obj.SiteName ?? obj.url ?? obj.Url ?? obj.title ?? "").trim();
        if (id > 0 && name) {
          out.push({ id, name });
        }
      }
      collectSiteLikeObjects(item, out, depth + 1);
    }
    return;
  }
  if (typeof value === "object") {
    for (const nested of Object.values(value as Record<string, unknown>)) {
      collectSiteLikeObjects(nested, out, depth + 1);
    }
  }
}

function totalsLookEmpty(total: QuickReportTotals | undefined): boolean {
  if (!total) {
    return true;
  }
  const keys: (keyof QuickReportTotals)[] = [
    "countOfRegistrations",
    "newDepositors",
    "countOfRegistrationsWithDeposits",
    "countOfAccountsWithDeposits",
  ];
  return keys.every((k) => !Number(total[k] ?? 0));
}

type QuickReportTotals = {
  countOfRegistrations?: number;
  newDepositors?: number;
  countOfRegistrationsWithDeposits?: number;
  countOfAccountsWithDeposits?: number;
};

function sumQuickReportTotals(totals: QuickReportTotals[]): QuickReportTotals {
  const sum = (pick: (t: QuickReportTotals) => number | undefined) =>
    totals.reduce((acc, t) => acc + Number(pick(t) ?? 0), 0);
  return {
    countOfRegistrations: sum((t) => t.countOfRegistrations),
    newDepositors: sum((t) => t.newDepositors),
    countOfRegistrationsWithDeposits: sum((t) => t.countOfRegistrationsWithDeposits),
    countOfAccountsWithDeposits: sum((t) => t.countOfAccountsWithDeposits),
  };
}

function formatGraphqlErrors(errors: Array<{ message?: string; extensions?: unknown }>): string {
  const parts = errors.map((e) => {
    const msg = (e.message || "GraphQL error").trim();
    if (e.extensions && typeof e.extensions === "object") {
      const ext = e.extensions as Record<string, unknown>;
      const code = ext.code ?? ext.errorCode ?? ext.type;
      if (code != null) {
        return `${msg} [${String(code)}]`;
      }
    }
    return msg;
  });
  return [...new Set(parts)].join("; ");
}

function siteIdOverride(env: AppEnv, country: XPartnersCountry): number | undefined {
  const raw =
    country === "CM"
      ? env.XPARTNERS_SITE_ID_CM
      : country === "EG"
        ? env.XPARTNERS_SITE_ID_EG
        : country === "RW"
          ? env.XPARTNERS_SITE_ID_RW
          : env.XPARTNERS_SITE_ID_ZM;
  return raw && raw > 0 ? raw : undefined;
}

function siteUrlForCountry(env: AppEnv, country: XPartnersCountry): string {
  const key =
    country === "CM"
      ? env.XPARTNERS_SITE_CM
      : country === "EG"
        ? env.XPARTNERS_SITE_EG
        : country === "RW"
          ? env.XPARTNERS_SITE_RW
          : env.XPARTNERS_SITE_ZM;
  return (key || DEFAULT_SITE_URL[country]).trim();
}

function parseCredentials(env: AppEnv): { login: string; password: string } | null {
  const combined = (env.XPARTNERS_CREDENTIALS || "").trim();
  if (combined.includes(":")) {
    const idx = combined.indexOf(":");
    const login = combined.slice(0, idx).trim();
    const password = combined.slice(idx + 1).trim();
    if (login && password) {
      return { login, password };
    }
  }
  const login = (env.XPARTNERS_LOGIN || "").trim();
  const password = (env.XPARTNERS_PASSWORD || "").trim();
  if (login && password) {
    return { login, password };
  }
  return null;
}

function mapSignInError(raw: string): string {
  if (raw.includes("INVALID_CAPTCHA") || raw.includes("CAPTCHA") || /captcha/i.test(raw)) {
    return "1xPartners: при входе нужна капча — один раз обнови XPARTNERS_COOKIE, дальше бот сам продлевает сессию через refresh-token.";
  }
  return raw.startsWith("1xPartners:") ? raw : `1xPartners: ${raw}`;
}

function mapCookieRejectedError(detail?: string): string {
  if (detail?.includes("COOKIE_REJECTED") || detail?.includes("TOKEN_ERROR")) {
    return "1xPartners: cookie истекла или не подходит — обнови XPARTNERS_COOKIE (AffiliateInfo → Copy as cURL).";
  }
  if (detail?.trim()) {
    return detail.trim();
  }
  return "1xPartners: XPARTNERS_COOKIE не принят.";
}

function mapMultiLoginError(status: number, body: string): string {
  const lower = body.toLowerCase();
  if (lower.includes("captcha") || lower.includes("recaptcha")) {
    return mapSignInError("INVALID_CAPTCHA");
  }
  try {
    const parsed = JSON.parse(body) as {
      message?: string;
      error?: string;
      errors?: Array<{ message?: string }>;
    };
    const msg =
      parsed.message ||
      parsed.error ||
      parsed.errors
        ?.map((entry) => entry.message)
        .filter(Boolean)
        .join("; ");
    if (msg) {
      return mapSignInError(msg);
    }
  } catch {
    // not JSON
  }
  if (status === 401 || status === 403) {
    return "1xPartners: неверный логин или пароль (XPARTNERS_LOGIN/PASSWORD).";
  }
  return `1xPartners: вход не удался (HTTP ${status}).`;
}

/** DevTools wraps long cookie — newlines in the middle break accessToken. */
function normalizeCookieHeader(raw: string): string {
  let s = raw
    .replace(/^cookie:\s*/i, "")
    .replace(/\r/g, "")
    .replace(/\n/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (
    (s.startsWith('"') && s.endsWith('"')) ||
    (s.startsWith("'") && s.endsWith("'"))
  ) {
    s = s.slice(1, -1).trim();
  }
  return s.replace(/\^/g, "");
}

function parseDevToolsCurl(raw: string): { cookie: string | null; headers: Record<string, string> } {
  const headers: Record<string, string> = {};
  if (!/-H\s/i.test(raw)) {
    return { cookie: null, headers };
  }
  for (const m of raw.matchAll(/-H\s+(?:\^?"([^"]+)"\^?|\^?'([^']+)'\^?|"([^"]+)"|'([^']+)')/gi)) {
    const line = (m[1] ?? m[2] ?? m[3] ?? m[4] ?? "").replace(/\^/g, "");
    const idx = line.indexOf(":");
    if (idx <= 0) {
      continue;
    }
    headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  const cookieEntry = Object.entries(headers).find(([k]) => k.toLowerCase() === "cookie");
  return {
    cookie: cookieEntry?.[1] ? normalizeCookieHeader(cookieEntry[1]) : null,
    headers,
  };
}

function apiCookieHeader(raw: string): string {
  return extractAuthCookieHeader(raw) || normalizeCookieHeader(raw);
}

function extractAuthCookieHeader(raw: string): string {
  const normalized = normalizeCookieHeader(raw);
  const names = ["accessToken", "refreshToken", "XSRF-TOKEN"] as const;
  const parts: string[] = [];
  for (const name of names) {
    const match = normalized.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`, "i"));
    if (match?.[1]) {
      parts.push(`${name}=${match[1].trim()}`);
    }
  }
  if (parts.length >= 2) {
    return parts.join("; ");
  }
  return normalized;
}

function validateAuthCookieHeader(cookie: string): void {
  if (!/accessToken=/i.test(cookie)) {
    throw new Error(
      "XPARTNERS_COOKIE: нет accessToken=. Вставь всю строку cookie из Network → GetQuickReport → Headers (не только кусок refreshToken).",
    );
  }
  if (!/refreshToken=/i.test(cookie)) {
    throw new Error(
      "XPARTNERS_COOKIE обрезан: нет refreshToken. Скопируй cookie ещё раз — до самого конца строки.",
    );
  }
}

export function cookiesFromEnv(env: AppEnv): string | null {
  const raw = (env.XPARTNERS_COOKIE || "").trim();
  if (!raw) {
    return null;
  }
  const fromCurl = parseDevToolsCurl(raw);
  const normalized = normalizeCookieHeader(fromCurl.cookie ?? raw);
  if (!/accessToken=/i.test(normalized)) {
    return null;
  }
  return normalized;
}

export function curlHeadersFromEnv(env: AppEnv): Record<string, string> | null {
  const raw = (env.XPARTNERS_COOKIE || "").trim();
  if (!raw || !/-H\s/i.test(raw)) {
    return null;
  }
  const { headers } = parseDevToolsCurl(raw);
  if (!Object.keys(headers).length) {
    return null;
  }
  const skip = new Set(["host", "connection", "content-length", "accept-encoding"]);
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    if (!skip.has(key.toLowerCase()) && value) {
      out[key] = value;
    }
  }
  return Object.keys(out).length ? out : null;
}

function usesCookieAuth(env: AppEnv): boolean {
  return Boolean(cookiesFromEnv(env));
}

function xsrfHeaderFromCookieHeader(cookieHeader: string | null | undefined): Record<string, string> {
  if (!cookieHeader?.trim()) {
    return {};
  }
  const match = cookieHeader.match(/(?:^|;\s*)XSRF-TOKEN=([^;]*)/i);
  if (!match?.[1]) {
    return {};
  }
  const raw = match[1].trim();
  let token = raw;
  try {
    token = decodeURIComponent(raw);
  } catch {
    // keep raw
  }
  return { "X-XSRF-TOKEN": token, "X-CSRF-TOKEN": token };
}

function cookieValueFromHeader(cookieHeader: string, name: string): string | null {
  const match = cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`, "i"));
  return match?.[1]?.trim() || null;
}

function bearerHeaderFromCookie(cookieHeader: string): Record<string, string> {
  const accessToken = cookieValueFromHeader(cookieHeader, "accessToken");
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

function applySetCookiesToHeader(baseCookie: string, setCookies: string[]): string {
  const jar = new Map<string, string>();
  for (const part of baseCookie.split(";")) {
    const trimmed = part.trim();
    if (!trimmed) {
      continue;
    }
    const eq = trimmed.indexOf("=");
    if (eq <= 0) {
      continue;
    }
    jar.set(trimmed.slice(0, eq).trim(), trimmed.slice(eq + 1).trim());
  }
  for (const raw of setCookies) {
    const first = raw.split(";")[0]?.trim();
    if (!first) {
      continue;
    }
    const eq = first.indexOf("=");
    if (eq <= 0) {
      continue;
    }
    jar.set(first.slice(0, eq).trim(), first.slice(eq + 1).trim());
  }
  const names = ["accessToken", "refreshToken", "XSRF-TOKEN"] as const;
  const parts: string[] = [];
  for (const name of names) {
    const value = jar.get(name);
    if (value) {
      parts.push(`${name}=${value}`);
    }
  }
  return parts.length ? parts.join("; ") : baseCookie.trim();
}

function multiRestDefaultQuery(): Record<string, string> {
  return {
    apitype: "web",
    apiVersion: String(MULTI_API_VERSION),
    v: String(MULTI_API_VERSION),
  };
}

function multiWebUiDefaultQuery(): Record<string, string> {
  return { v: String(MULTI_API_VERSION) };
}

const MULTI_WEB_REFERER = `${MULTI_BASE}/ru/partner/reports/quick-report`;

function multiWebRequestHeaders(cookie: string, curlHeaders: Record<string, string> | null): Record<string, string> {
  if (curlHeaders) {
    const merged: Record<string, string> = {
      ...BROWSER_HEADERS,
      Accept: "application/json, text/plain, */*",
      "Sec-Fetch-Dest": "empty",
      "Sec-Fetch-Mode": "cors",
      "Sec-Fetch-Site": "same-origin",
      ...curlHeaders,
      Cookie:
        Object.entries(curlHeaders).find(([k]) => k.toLowerCase() === "cookie")?.[1] ?? cookie,
    };
    if (!Object.keys(curlHeaders).some((k) => k.toLowerCase() === "authorization")) {
      Object.assign(merged, bearerHeaderFromCookie(cookie));
    }
    if (!Object.keys(curlHeaders).some((k) => k.toLowerCase() === "x-xsrf-token")) {
      Object.assign(merged, xsrfHeaderFromCookieHeader(cookie));
    }
    return merged;
  }
  return {
    ...BROWSER_HEADERS,
    Accept: "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Api-Version": String(MULTI_API_VERSION),
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    Origin: MULTI_BASE,
    Referer: MULTI_WEB_REFERER,
    Cookie: cookie,
    ...bearerHeaderFromCookie(cookie),
    ...xsrfHeaderFromCookieHeader(cookie),
  };
}

const GET_PARTNERS_CAPTCHA_MODE = `
query PartnersCaptchaMode {
  partnersProgram {
    generalInformation {
      hasOwnCaptcha
    }
  }
}`;

export class XPartnersClient {
  private jar: CookieJar;
  private fetchWithCookies: typeof fetch;
  private loggedIn = false;
  private siteBundleCache = new Map<
    XPartnersCountry,
    { sites: Array<{ id: number; label: string }>; label: string }
  >();
  private bootstrapped = false;
  private signInInFlight: Promise<void> | null = null;
  /** After captcha/login failure, do not hammer SignIn (e.g. «Обновить все» × 3 countries). */
  private signInBlockedUntilMs = 0;
  private lastSignInError = "";
  private lastPingDetail = "";
  private multiWebBlocked = false;
  private multiRefreshInFlight: Promise<boolean> | null = null;
  private multiRefreshBlockedUntilMs = 0;
  private envCredentialsSeeded = false;

  constructor(
    private readonly env: AppEnv,
    private readonly meta?: AppMetaStore,
  ) {
    this.jar = new CookieJar();
    this.fetchWithCookies = makeFetchCookie(fetch, this.jar) as typeof fetch;
  }

  private async requestHeaders(
    extra: Record<string, string> = {},
    cookieSource?: string | null,
  ): Promise<Record<string, string>> {
    let xsrfSource = cookieSource?.trim() || extra.Cookie?.trim() || null;
    if (!xsrfSource) {
      xsrfSource = (await this.jar.getCookieString(BASE)) || null;
    }
    return {
      ...BROWSER_HEADERS,
      ...xsrfHeaderFromCookieHeader(xsrfSource),
      ...extra,
    };
  }

  private async bootstrapCookiesIfNeeded(): Promise<void> {
    if (this.bootstrapped) {
      await this.seedEnvCredentialsIfNeeded();
      return;
    }
    this.bootstrapped = true;
    const existing = await this.jar.getCookieString(BASE);
    if (existing) {
      await this.seedEnvCredentialsIfNeeded();
      return;
    }
    let raw = (await this.meta?.get(XPARTNERS_SESSION_META_KEY))?.trim() || null;
    if (!raw) {
      raw = cookiesFromEnv(this.env);
      if (raw && this.meta && usesMultiRestAuth(raw)) {
        await this.persistMultiCookieHeader(extractAuthCookieHeader(raw));
      }
    }
    if (raw) {
      await this.seedCookies(extractAuthCookieHeader(raw));
    }
    await this.seedEnvCredentialsIfNeeded();
  }

  private async seedEnvCredentialsIfNeeded(): Promise<void> {
    if (this.envCredentialsSeeded || !this.meta) {
      return;
    }
    this.envCredentialsSeeded = true;
    const creds = parseCredentials(this.env);
    if (!creds || usesCookieAuth(this.env)) {
      return;
    }
    const existingLogin = (await this.meta.get(XPARTNERS_LOGIN_META_KEY))?.trim();
    if (!existingLogin) {
      await this.meta.set(XPARTNERS_LOGIN_META_KEY, creds.login);
      await this.meta.set(XPARTNERS_PASSWORD_META_KEY, creds.password);
    }
  }

  private async persistSessionCookies(): Promise<void> {
    if (!this.meta) {
      return;
    }
    const multiJar = (await this.jar.getCookieString(MULTI_BASE)) || "";
    const cookie = extractAuthCookieHeader(multiJar);
    if (cookie && /accessToken=/i.test(cookie)) {
      await this.persistCookieString(cookie);
      return;
    }
    const active = await this.activeSessionCookieHeader();
    if (active) {
      await this.persistCookieString(active);
    }
  }

  private async seedCookies(cookieHeader: string): Promise<void> {
    for (const base of [BASE, MULTI_BASE]) {
      for (const part of cookieHeader.split(";")) {
        const trimmed = part.trim();
        if (!trimmed) {
          continue;
        }
        try {
          await this.jar.setCookie(trimmed, base);
        } catch {
          // ignore malformed fragments
        }
      }
    }
  }

  private sessionCookieHeader(): string | null {
    const cookie = cookiesFromEnv(this.env);
    if (!cookie) {
      return null;
    }
    validateAuthCookieHeader(cookie);
    return cookie;
  }

  private async activeSessionCookieHeader(): Promise<string | null> {
    const envCookie = cookiesFromEnv(this.env);
    if (envCookie) {
      try {
        validateAuthCookieHeader(envCookie);
        return envCookie;
      } catch {
        // malformed env cookie
      }
    }
    const metaRaw = (await this.meta?.get(XPARTNERS_SESSION_META_KEY))?.trim();
    if (metaRaw) {
      const metaCookie = extractAuthCookieHeader(metaRaw);
      if (metaCookie) {
        try {
          validateAuthCookieHeader(metaCookie);
          return metaCookie;
        } catch {
          // fall through
        }
      }
    }
    return null;
  }

  private usesMultiRestSession(cookie?: string | null): boolean {
    return usesMultiRestAuth(cookie ?? cookiesFromEnv(this.env));
  }

  /** multi.1xpartners.com web UI — blocked from many cloud IPs (403 FORBIDDEN). */
  private preferMultiWebApi(): boolean {
    if (usesSubpartnerStats(this.env)) {
      return false;
    }
    if (shouldPreferGraphqlApi(this.env)) {
      return false;
    }
    return !this.multiWebBlocked && this.usesMultiRestSession(null);
  }

  private markMultiWebBlocked(reason: string): void {
    if (!this.multiWebBlocked) {
      this.multiWebBlocked = true;
      console.warn(`1xPartners: multi web blocked (${reason}), using 1xpartners.com/graphql`);
    }
  }

  private async persistMultiCookieHeader(cookieHeader: string): Promise<void> {
    const trimmed = extractAuthCookieHeader(cookieHeader);
    if (!trimmed) {
      return;
    }
    await this.seedCookies(trimmed);
    await this.persistCookieString(trimmed);
  }

  private responseSetCookies(response: Response): string[] {
    const headers = response.headers as Headers & { getSetCookie?: () => string[] };
    if (typeof headers.getSetCookie === "function") {
      return headers.getSetCookie();
    }
    const single = response.headers.get("set-cookie");
    return single ? [single] : [];
  }

  private async refreshMultiSession(): Promise<boolean> {
    if (Date.now() < this.multiRefreshBlockedUntilMs) {
      return false;
    }
    if (this.multiRefreshInFlight) {
      return this.multiRefreshInFlight;
    }
    this.multiRefreshInFlight = this.refreshMultiSessionOnce().finally(() => {
      this.multiRefreshInFlight = null;
    });
    return this.multiRefreshInFlight;
  }

  private sessionWasCleared(setCookies: string[]): boolean {
    return setCookies.some((raw) => /(?:^|;\s*)(accessToken|refreshToken)=null/i.test(raw));
  }

  private async markMultiRefreshFailure(fastFail = false): Promise<void> {
    if (!fastFail) {
      this.multiRefreshBlockedUntilMs = Date.now() + MULTI_REFRESH_BACKOFF_MS;
    }
    if (this.meta) {
      await this.meta.set(XPARTNERS_SESSION_META_KEY, "");
    }
  }

  private async refreshMultiSessionOnce(): Promise<boolean> {
    const cookie = await this.activeSessionCookieHeader();
    if (!cookie) {
      return false;
    }
    const qs = new URLSearchParams(multiRestDefaultQuery());
    try {
      const response = await fetch(`${MULTI_REST}/refresh-token?${qs.toString()}`, {
        method: "POST",
        redirect: "manual",
        headers: {
          ...BROWSER_HEADERS,
          Accept: "application/json, text/plain, */*",
          "Content-Type": "application/json",
          "Api-Version": String(MULTI_API_VERSION),
          Origin: MULTI_BASE,
          Referer: `${MULTI_BASE}/`,
          Cookie: cookie,
          ...bearerHeaderFromCookie(cookie),
          ...xsrfHeaderFromCookieHeader(cookie),
        },
        body: "{}",
        signal: AbortSignal.timeout(MULTI_REFRESH_TIMEOUT_MS),
      });
      const setCookies = this.responseSetCookies(response);
      if (setCookies.length) {
        await this.persistMultiCookieHeader(applySetCookiesToHeader(cookie, setCookies));
      }
      if (response.status === 302 || response.status === 307 || response.status === 308) {
        await this.markMultiRefreshFailure(true);
        return false;
      }
      if (!response.ok) {
        await this.markMultiRefreshFailure(true);
        console.warn("1xPartners refresh-token:", response.status, (await response.text()).slice(0, 200));
        return false;
      }
      this.multiRefreshBlockedUntilMs = 0;
      return true;
    } catch (error) {
      await this.markMultiRefreshFailure();
      console.warn("1xPartners refresh-token:", error instanceof Error ? error.message : error);
      return false;
    }
  }

  private async warmMultiCabinetPage(cookie: string): Promise<void> {
    try {
      await fetch(MULTI_WEB_REFERER, {
        method: "GET",
        redirect: "manual",
        headers: {
          ...BROWSER_HEADERS,
          Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          Referer: `${MULTI_BASE}/`,
          Cookie: cookie,
          ...bearerHeaderFromCookie(cookie),
          ...xsrfHeaderFromCookieHeader(cookie),
        },
        signal: AbortSignal.timeout(12_000),
      });
    } catch {
      // optional warmup
    }
  }

  private async multiRestRequest(
    method: "GET" | "POST",
    urlPath: string,
    params: Record<string, string | number> = {},
    body?: unknown,
    allowRefresh = true,
    api: "rest" | "web" = "rest",
  ): Promise<unknown> {
    const cookie = await this.activeSessionCookieHeader();
    if (!cookie) {
      throw new Error("1xPartners: нет cookie для multi REST.");
    }
    const qs = new URLSearchParams(api === "web" ? multiWebUiDefaultQuery() : multiRestDefaultQuery());
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && String(value).length > 0) {
        qs.set(key, String(value));
      }
    }
    const url = `${urlPath}?${qs.toString()}`;
    const curlHeaders = curlHeadersFromEnv(this.env);
    const webHeaders =
      api === "web" ? multiWebRequestHeaders(cookie, curlHeaders) : null;
    const response = await fetch(url, {
      method,
      redirect: "manual",
      headers:
        webHeaders ??
        {
          ...BROWSER_HEADERS,
          Accept: "application/json, text/plain, */*",
          "Api-Version": String(MULTI_API_VERSION),
          Origin: MULTI_BASE,
          Referer: `${MULTI_BASE}/`,
          Cookie: cookie,
          ...bearerHeaderFromCookie(cookie),
          ...xsrfHeaderFromCookieHeader(cookie),
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(MULTI_REST_TIMEOUT_MS),
    });

    if (api === "web" && (response.status === 401 || response.status === 403)) {
      const bodyPreview = (await response.text()).slice(0, 80).replace(/\s+/g, " ");
      console.warn(
        `1xPartners web API ${response.status} ${urlPath.split("/").pop()} cookieLen=${cookie.length} body=${bodyPreview}`,
      );
      if (response.status === 403 && bodyPreview.includes("FORBIDDEN")) {
        this.markMultiWebBlocked("403 FORBIDDEN");
        this.lastPingDetail = "COOKIE_REJECTED";
        throw new Error("COOKIE_REJECTED");
      }
      if (allowRefresh && !this.multiWebBlocked && (await this.refreshMultiSession())) {
        return this.multiRestRequest(method, urlPath, params, body, false, api);
      }
      this.lastPingDetail = "COOKIE_REJECTED";
      throw new Error("COOKIE_REJECTED");
    }

    const setCookies = this.responseSetCookies(response);
    if (setCookies.length) {
      if (this.sessionWasCleared(setCookies)) {
        this.lastPingDetail = "COOKIE_REJECTED";
        console.warn("1xPartners: API rejected cookie (accessToken=null)");
        throw new Error("COOKIE_REJECTED");
      }
      await this.persistMultiCookieHeader(applySetCookiesToHeader(cookie, setCookies));
    }

    const needsRefresh =
      allowRefresh &&
      (response.status === 401 ||
        response.status === 302 ||
        response.status === 307 ||
        response.status === 308 ||
        ((response.ok || response.status === 200) &&
          (response.headers.get("content-type") || "").includes("text/html")));

    if (needsRefresh) {
      const location = response.headers.get("location") || "";
      if (location.includes("sign-in") || response.status === 401 || response.status === 308) {
        if (await this.refreshMultiSession()) {
          return this.multiRestRequest(method, urlPath, params, body, false, api);
        }
        throw new Error("TOKEN_ERROR");
      }
    }

    if (response.status === 302 || response.status === 307 || response.status === 308) {
      throw new Error("TOKEN_ERROR");
    }

    const text = await response.text();
    if (!response.ok) {
      throw new Error(`1xPartners multi REST HTTP ${response.status}: ${text.slice(0, 300)}`);
    }
    const ct = response.headers.get("content-type") || "";
    if (ct.includes("text/html")) {
      if (allowRefresh && (await this.refreshMultiSession())) {
        return this.multiRestRequest(method, urlPath, params, body, false, api);
      }
      throw new Error("TOKEN_ERROR");
    }
    try {
      const parsed = JSON.parse(text) as unknown;
      const latest = (await this.activeSessionCookieHeader()) || cookie;
      await this.persistMultiCookieHeader(latest);
      return parsed;
    } catch {
      throw new Error(`1xPartners multi REST invalid JSON: ${text.slice(0, 200)}`);
    }
  }

  private async multiRestGet(endpoint: string, params: Record<string, string | number> = {}): Promise<unknown> {
    return this.multiRestRequest("GET", `${MULTI_WEB_UI}/${endpoint}`, params, undefined, true, "web");
  }

  private cookieRejectedByServer(): boolean {
    return this.lastPingDetail.includes("COOKIE_REJECTED");
  }

  private async pingMultiAuthorized(): Promise<boolean> {
    try {
      const cookie = await this.activeSessionCookieHeader();
      if (cookie) {
        await this.warmMultiCabinetPage(cookie);
      }
      const data = await this.multiRestGet("AffiliateInfo");
      if (data && typeof data === "object") {
        const err = (data as Record<string, unknown>).error ?? (data as Record<string, unknown>).Error;
        if (err != null && String(err).trim()) {
          this.lastPingDetail = String(err);
          return false;
        }
        return true;
      }
      this.lastPingDetail = "AffiliateInfo: пустой ответ";
      return false;
    } catch (error) {
      this.lastPingDetail = error instanceof Error ? error.message : String(error);
      return false;
    }
  }

  private async listSitesMulti(): Promise<Array<{ id: number; name: string }>> {
    const collected: Array<{ id: number; name: string }> = [];
    try {
      collectSiteLikeObjects(await this.multiRestGet("AffiliateInfo"), collected);
    } catch (error) {
      console.warn("1xPartners AffiliateInfo:", error instanceof Error ? error.message : error);
    }
    try {
      collectSiteLikeObjects(await this.multiRestGet("GetCountries"), collected);
    } catch {
      // optional
    }
    const byId = new Map<number, { id: number; name: string }>();
    for (const site of collected) {
      byId.set(site.id, site);
    }
    return [...byId.values()];
  }

  private async fetchQuickReportTotalsMulti(filter: {
    merchantId: number;
    siteId?: number;
    startPeriod: string;
    endPeriod: string;
  }): Promise<{ status?: string; total: QuickReportTotals }> {
    const params: Record<string, string | number> = {
      MerchantId: filter.merchantId,
      StartPeriod: filter.startPeriod,
      EndPeriod: filter.endPeriod,
    };
    if (filter.siteId && filter.siteId > 0) {
      params.SiteId = filter.siteId;
    }
    const data = await this.multiRestGet("GetQuickReport", params);
    const total = parseRestQuickReportTotals(data);
    return { status: "SUCCESS", total };
  }

  private graphqlOrigin(): string {
    if (this.multiWebBlocked) {
      return BASE;
    }
    const cookie = cookiesFromEnv(this.env);
    return cookie?.includes("accessToken") ? MULTI_BASE : BASE;
  }

  private async graphql<T>(
    items: GraphQlBatchItem[],
    referer?: string,
  ): Promise<T> {
    const cookie = this.sessionCookieHeader();
    const origin = this.graphqlOrigin();
    const refererUrl = referer ?? `${origin}/ru/partner/reports/quick-report`;
    const init: RequestInit = {
      method: "POST",
      headers: await this.requestHeaders(
        {
          "Content-Type": "application/json",
          Origin: origin,
          Referer: refererUrl,
          ...(cookie
            ? { Cookie: cookie, ...bearerHeaderFromCookie(cookie), ...xsrfHeaderFromCookieHeader(cookie) }
            : {}),
        },
        cookie,
      ),
      body: JSON.stringify(items),
    };
    const response = cookie
      ? await fetch(GRAPHQL, { ...init, signal: AbortSignal.timeout(XP_FETCH_TIMEOUT_MS) })
      : await this.fetchTimed(GRAPHQL, init);
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`1xPartners HTTP ${response.status}: ${text.slice(0, 300)}`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error(`1xPartners invalid JSON: ${text.slice(0, 200)}`);
    }
    if (cookie) {
      await this.persistCookieString(cookie);
    } else {
      await this.persistSessionCookies();
    }
    return parsed as T;
  }

  private async persistCookieString(cookieHeader: string): Promise<void> {
    if (!cookieHeader.trim() || !this.meta) {
      return;
    }
    await this.meta.set(XPARTNERS_SESSION_META_KEY, cookieHeader.trim());
  }

  private reportsCookieFromEnv(): string | null {
    const raw = (this.env.XPARTNERS_REPORTS_COOKIE || "").trim();
    return raw || null;
  }

  private playersReportCookieHeader(): string | null {
    const reports = this.reportsCookieFromEnv();
    if (reports) {
      return reports;
    }
    return cookiesFromEnv(this.env);
  }

  /** GetPlayersReport: явный Cookie (reports или основной), иначе jar-сессия. */
  private async graphqlPlayersReport<T>(items: GraphQlBatchItem[]): Promise<T> {
    const cookie = this.playersReportCookieHeader();
    if (!cookie) {
      return this.graphql<T>(items, `${BASE}/ru/partner/reports/players`);
    }
    const response = await fetch(GRAPHQL, {
      method: "POST",
      headers: await this.requestHeaders(
        {
          "Content-Type": "application/json",
          Origin: BASE,
          Referer: `${BASE}/ru/partner/reports/players`,
          Cookie: cookie,
        },
        cookie,
      ),
      body: JSON.stringify(items),
      signal: AbortSignal.timeout(XP_FETCH_TIMEOUT_MS),
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`1xPartners HTTP ${response.status}: ${text.slice(0, 300)}`);
    }
    try {
      const parsed = JSON.parse(text) as T;
      await this.persistCookieString(cookie);
      return parsed;
    } catch {
      throw new Error(`1xPartners invalid JSON: ${text.slice(0, 200)}`);
    }
  }

  private async clearStaleSessionForLogin(): Promise<void> {
    if (this.meta) {
      await this.meta.set(XPARTNERS_SESSION_META_KEY, "");
    }
    this.bootstrapped = false;
    this.jar = new CookieJar();
    this.fetchWithCookies = makeFetchCookie(fetch, this.jar) as typeof fetch;
  }

  private async fetchTimed(url: string, init: RequestInit): Promise<Response> {
    return this.fetchWithCookies(url, {
      ...init,
      signal: AbortSignal.timeout(XP_FETCH_TIMEOUT_MS),
    });
  }

  private async reloadEnvCookieSession(): Promise<boolean> {
    const envCookie = cookiesFromEnv(this.env);
    if (!envCookie) {
      return false;
    }
    this.jar = new CookieJar();
    this.fetchWithCookies = makeFetchCookie(fetch, this.jar) as typeof fetch;
    this.bootstrapped = false;
    if (this.usesMultiRestSession(envCookie)) {
      await this.seedCookies(envCookie);
      await this.persistCookieString(envCookie);
    } else {
      await this.seedCookies(envCookie);
    }
    this.bootstrapped = true;
    return this.pingAuthorized();
  }

  private async readAuthFlags(): Promise<{
    hasStoredCookie: boolean;
    hasStoredCredentials: boolean;
    hasEnvCookie: boolean;
    hasEnvCredentials: boolean;
  }> {
    const metaLogin = (await this.meta?.get(XPARTNERS_LOGIN_META_KEY))?.trim();
    const metaPassword = await this.meta?.get(XPARTNERS_PASSWORD_META_KEY);
    return {
      hasStoredCookie: Boolean((await this.meta?.get(XPARTNERS_SESSION_META_KEY))?.trim()),
      hasStoredCredentials: Boolean(metaLogin && metaPassword),
      hasEnvCookie: Boolean(cookiesFromEnv(this.env)),
      hasEnvCredentials: Boolean(parseCredentials(this.env)),
    };
  }

  private async getStoredCredentials(): Promise<{ login: string; password: string } | null> {
    const metaLogin = (await this.meta?.get(XPARTNERS_LOGIN_META_KEY))?.trim();
    const metaPassword = await this.meta?.get(XPARTNERS_PASSWORD_META_KEY);
    if (metaLogin && metaPassword) {
      return { login: metaLogin, password: metaPassword };
    }
    return parseCredentials(this.env);
  }

  private async reloadPersistedCookieSession(): Promise<boolean> {
    const raw = (await this.meta?.get(XPARTNERS_SESSION_META_KEY))?.trim();
    const cookieHeader = raw ? extractAuthCookieHeader(raw) : "";
    if (!cookieHeader) {
      return false;
    }
    this.jar = new CookieJar();
    this.fetchWithCookies = makeFetchCookie(fetch, this.jar) as typeof fetch;
    this.bootstrapped = false;
    await this.seedCookies(cookieHeader);
    this.bootstrapped = true;
    return this.pingAuthorized();
  }

  private async loginWithStoredCredentials(): Promise<boolean> {
    const creds = await this.getStoredCredentials();
    if (!creds) {
      return false;
    }
    if (Date.now() < this.signInBlockedUntilMs) {
      return false;
    }
    try {
      await this.clearStaleSessionForLogin();
      await this.loginWithPasswordOnce(creds.login, creds.password);
      return true;
    } catch {
      return false;
    }
  }

  async describeSessionStatus(metaOverride?: AppMetaStore): Promise<XPartnersSessionStatus> {
    const meta = metaOverride ?? this.meta;
    const hasStoredCookie = Boolean((await meta?.get(XPARTNERS_SESSION_META_KEY))?.trim());
    const metaLogin = (await meta?.get(XPARTNERS_LOGIN_META_KEY))?.trim();
    const metaPassword = await meta?.get(XPARTNERS_PASSWORD_META_KEY);
    const hasStoredCredentials = Boolean(metaLogin && metaPassword);
    const hasEnvCookie = Boolean(cookiesFromEnv(this.env));
    const hasEnvCredentials = Boolean(parseCredentials(this.env));

    await this.bootstrapCookiesIfNeeded();
    const connected = await this.pingAuthorized();
    if (connected) {
      const source = hasStoredCookie || hasEnvCookie ? "cookie" : hasStoredCredentials || hasEnvCredentials ? "credentials" : "env";
      return {
        connected: true,
        source,
        loginHint: metaLogin || parseCredentials(this.env)?.login,
        hasStoredCookie,
        hasStoredCredentials,
        hasEnvCookie,
        hasEnvCredentials,
        captchaBlockedUntil:
          Date.now() < this.signInBlockedUntilMs
            ? new Date(this.signInBlockedUntilMs).toISOString()
            : undefined,
        message: "Сессия активна.",
      };
    }

    const credsHint = metaLogin || parseCredentials(this.env)?.login;
    return {
      connected: false,
      source: "none",
      loginHint: credsHint,
      hasStoredCookie,
      hasStoredCredentials,
      hasEnvCookie,
      hasEnvCredentials,
      captchaBlockedUntil:
        Date.now() < this.signInBlockedUntilMs
          ? new Date(this.signInBlockedUntilMs).toISOString()
          : undefined,
      message: this.lastSignInError
        || (hasStoredCookie || hasEnvCookie || hasStoredCredentials || hasEnvCredentials
          ? "Сессия истекла — бот переподключится сам. Если не помогло: обнови XPARTNERS_COOKIE в Railway."
          : "Задай XPARTNERS_LOGIN/PASSWORD или XPARTNERS_COOKIE в Railway Variables."),
    };
  }

  async importCookieHeader(cookieHeader: string): Promise<void> {
    const trimmed = extractAuthCookieHeader(cookieHeader);
    if (!trimmed) {
      throw new Error("Cookie пустой.");
    }
    validateAuthCookieHeader(trimmed);
    await this.clearStaleSessionForLogin();
    await this.seedCookies(trimmed);
    this.bootstrapped = true;
    if (!(await this.pingAuthorized())) {
      throw new Error(mapCookieRejectedError(this.lastPingDetail));
    }
    this.loggedIn = true;
    await this.persistCookieString(trimmed);
  }

  async persistCredentials(login: string, password: string): Promise<void> {
    if (!this.meta) {
      throw new Error("Хранилище сессии недоступно (нет DATABASE_URL).");
    }
    await this.meta.set(XPARTNERS_LOGIN_META_KEY, login.trim());
    await this.meta.set(XPARTNERS_PASSWORD_META_KEY, password);
  }

  async clearStoredAuth(): Promise<void> {
    if (this.meta) {
      await this.meta.set(XPARTNERS_SESSION_META_KEY, "");
      await this.meta.set(XPARTNERS_LOGIN_META_KEY, "");
      await this.meta.set(XPARTNERS_PASSWORD_META_KEY, "");
    }
    this.loggedIn = false;
    this.bootstrapped = false;
    this.signInBlockedUntilMs = 0;
    this.lastSignInError = "";
    this.jar = new CookieJar();
    this.fetchWithCookies = makeFetchCookie(fetch, this.jar) as typeof fetch;
  }

  async ensureSession(): Promise<void> {
    await this.bootstrapCookiesIfNeeded();
    const envCookie = cookiesFromEnv(this.env);
    const cookieAuth = Boolean(envCookie);

    if (await this.pingAuthorized()) {
      this.loggedIn = true;
      await this.persistSessionCookies();
      return;
    }
    this.loggedIn = false;

    if (this.preferMultiWebApi() && !this.cookieRejectedByServer()) {
      if (await this.refreshMultiSession()) {
        if (await this.pingAuthorized()) {
          this.loggedIn = true;
          await this.persistSessionCookies();
          return;
        }
      }
    }

    if (this.cookieRejectedByServer() && cookieAuth && !this.multiWebBlocked) {
      throw new Error(mapCookieRejectedError(this.lastPingDetail));
    }

    if (await this.reloadEnvCookieSession()) {
      this.loggedIn = true;
      await this.persistSessionCookies();
      return;
    }

    if (await this.reloadPersistedCookieSession()) {
      this.loggedIn = true;
      await this.persistSessionCookies();
      return;
    }

    if (cookieAuth) {
      try {
        validateAuthCookieHeader(envCookie!);
      } catch (error) {
        throw error instanceof Error ? error : new Error(String(error));
      }
      throw new Error(mapCookieRejectedError(this.lastPingDetail));
    }

    if (await this.loginWithStoredCredentials()) {
      this.loggedIn = true;
      await this.persistSessionCookies();
      return;
    }

    const creds = await this.getStoredCredentials();
    if (creds) {
      if (Date.now() < this.signInBlockedUntilMs) {
        throw new Error(this.lastSignInError || mapSignInError("INVALID_CAPTCHA"));
      }
      throw new Error(
        this.lastSignInError ||
          "1xPartners: автологин по XPARTNERS_LOGIN/PASSWORD не удался — проверь логин и пароль.",
      );
    }

    throw new Error(
      "1xPartners: задай XPARTNERS_COOKIE или XPARTNERS_LOGIN/PASSWORD в Railway Variables.",
    );
  }

  async keepAlive(): Promise<void> {
    try {
      await this.bootstrapCookiesIfNeeded();
      if (await this.pingAuthorized()) {
        this.loggedIn = true;
        await this.persistSessionCookies();
        return;
      }
      this.loggedIn = false;
      if (
        this.preferMultiWebApi() &&
        !this.cookieRejectedByServer()
      ) {
        if (await this.refreshMultiSession() && (await this.pingAuthorized())) {
          this.loggedIn = true;
          await this.persistSessionCookies();
          return;
        }
      }
      await this.ensureSession();
    } catch (error) {
      this.loggedIn = false;
      console.warn("1xPartners keep-alive:", error instanceof Error ? error.message : error);
    }
  }

  private async fetchUsesOwnCaptcha(): Promise<boolean> {
    try {
      const batch = await this.graphql<
        Array<{
          data?: { partnersProgram?: { generalInformation?: { hasOwnCaptcha?: boolean } } };
        }>
      >([{ operationName: "PartnersCaptchaMode", query: GET_PARTNERS_CAPTCHA_MODE }]);
      return Boolean(batch?.[0]?.data?.partnersProgram?.generalInformation?.hasOwnCaptcha);
    } catch {
      return false;
    }
  }

  private async loginWithPasswordOnce(login: string, password: string): Promise<void> {
    if (Date.now() < this.signInBlockedUntilMs) {
      throw new Error(this.lastSignInError || mapSignInError("INVALID_CAPTCHA"));
    }
    if (this.signInInFlight) {
      await this.signInInFlight;
      if (this.loggedIn) {
        return;
      }
      if (Date.now() < this.signInBlockedUntilMs) {
        throw new Error(this.lastSignInError || mapSignInError("INVALID_CAPTCHA"));
      }
    }
    this.signInInFlight = this.loginWithPassword(login, password).finally(() => {
      this.signInInFlight = null;
    });
    await this.signInInFlight;
  }

  private async pingGraphqlAuthorized(): Promise<boolean> {
    try {
      const batch = await this.graphql<
        Array<{
          data?: {
            authorized?: {
              partnerAndManager?: { data?: { sites?: unknown[] } };
            };
          };
          errors?: Array<{ message?: string }>;
        }>
      >([
        {
          operationName: "PartnerSites",
          variables: { filter: { hidden: false, partnerId: null } },
          query: PARTNER_SITES,
        },
      ]);
      const first = batch?.[0];
      if (first?.errors?.length) {
        this.lastPingDetail = formatGraphqlErrors(first.errors);
        return false;
      }
      const sites = first?.data?.authorized?.partnerAndManager?.data?.sites;
      if (!Array.isArray(sites)) {
        this.lastPingDetail = "graphql: нет partner sites (cookie истёк или не партнёрский)";
        return false;
      }
      return true;
    } catch (error) {
      this.lastPingDetail = error instanceof Error ? error.message : String(error);
      return false;
    }
  }

  private async pingAuthorized(): Promise<boolean> {
    this.lastPingDetail = "";
    if (this.preferMultiWebApi()) {
      if (await this.pingMultiAuthorized()) {
        return true;
      }
      if (this.multiWebBlocked || this.lastPingDetail.includes("COOKIE_REJECTED")) {
        return this.pingGraphqlAuthorized();
      }
      return false;
    }
    return this.pingGraphqlAuthorized();
  }

  private async loginWithPassword(login: string, password: string): Promise<void> {
    await this.loginWithMultiRest(login, password);
  }

  private async loginWithMultiRest(login: string, password: string): Promise<void> {
    await this.fetchTimed(`${MULTI_BASE}/sign-in`, {
      method: "GET",
      headers: { Accept: "text/html,application/xhtml+xml" },
    });

    const qs = new URLSearchParams(multiRestDefaultQuery());
    const postLogin = async (isOwnCaptcha: boolean): Promise<Response> => {
      const cookieHeader = (await this.jar.getCookieString(MULTI_BASE)) || "";
      return fetch(`${MULTI_REST}/login?${qs.toString()}`, {
        method: "POST",
        redirect: "manual",
        headers: {
          ...BROWSER_HEADERS,
          Accept: "application/json, text/plain, */*",
          "Content-Type": "application/json",
          "Api-Version": String(MULTI_API_VERSION),
          Origin: MULTI_BASE,
          Referer: `${MULTI_BASE}/sign-in`,
          Cookie: cookieHeader,
          ...xsrfHeaderFromCookieHeader(cookieHeader),
        },
        body: JSON.stringify({
          userName: login,
          password,
          canPartnerLogin: true,
          recaptchaToken: "",
          isOwnCaptcha,
        }),
        signal: AbortSignal.timeout(MULTI_REST_TIMEOUT_MS),
      });
    };

    let response = await postLogin(true);
    let body = await response.text();
    if (!response.ok && /captcha|recaptcha/i.test(body)) {
      response = await postLogin(false);
      body = await response.text();
    }

    const cookieBefore = (await this.jar.getCookieString(MULTI_BASE)) || "";
    const setCookies = this.responseSetCookies(response);
    if (setCookies.length) {
      await this.persistMultiCookieHeader(applySetCookiesToHeader(cookieBefore, setCookies));
      this.bootstrapped = true;
    }

    if (!response.ok) {
      const mapped = mapMultiLoginError(response.status, body);
      if (/captcha|recaptcha|INVALID_CAPTCHA/i.test(mapped)) {
        this.signInBlockedUntilMs = Date.now() + 30 * 60_000;
        this.lastSignInError = mapped;
      }
      throw new Error(mapped);
    }

    let parsed: { is2Fa?: boolean } | null = null;
    try {
      parsed = JSON.parse(body) as { is2Fa?: boolean };
    } catch {
      // empty or non-json success body
    }
    if (parsed?.is2Fa) {
      throw new Error("1xPartners: включена 2FA — отключите или задайте XPARTNERS_COOKIE.");
    }

    if (!(await this.pingAuthorized())) {
      throw new Error(this.lastPingDetail || "1xPartners: вход прошёл, но API не отвечает.");
    }
  }

  private async listSitesGraphql(): Promise<Array<{ id: number; name: string }>> {
    const run = async (hidden: boolean | undefined) => {
      const filter: { partnerId: null; hidden?: boolean } = { partnerId: null };
      if (hidden !== undefined) {
        filter.hidden = hidden;
      }
      const batch = await this.graphql<
        Array<{
          data?: {
            authorized?: {
              partnerAndManager?: {
                data?: { sites?: Array<{ id: string | number; name: string; hidden?: boolean }> };
              };
            };
          };
        }>
      >([
        {
          operationName: "PartnerSites",
          variables: { filter },
          query: PARTNER_SITES,
        },
      ]);
      return batch?.[0]?.data?.authorized?.partnerAndManager?.data?.sites ?? [];
    };
    const merged = [...(await run(false)), ...(await run(true))];
    const byId = new Map<number, { id: number; name: string }>();
    for (const s of merged) {
      if (s.hidden) {
        continue;
      }
      const id = Number(s.id);
      const name = (s.name || "").trim();
      if (id > 0 && name) {
        byId.set(id, { id, name });
      }
    }
    return [...byId.values()];
  }

  private async listSites(): Promise<Array<{ id: number; name: string }>> {
    await this.ensureSession();
    if (this.preferMultiWebApi()) {
      try {
        const sites = await this.listSitesMulti();
        if (sites.length) {
          return sites;
        }
      } catch (error) {
        if (!(error instanceof Error && error.message.includes("COOKIE_REJECTED"))) {
          console.warn("1xPartners listSites multi:", error instanceof Error ? error.message : error);
        }
      }
    }
    return this.listSitesGraphql();
  }

  private async resolveSitesForCountry(
    country: XPartnersCountry,
  ): Promise<{ sites: Array<{ id: number; label: string }>; label: string }> {
    const cached = this.siteBundleCache.get(country);
    if (cached) {
      return cached;
    }
    const allSites = await this.listSites();
    const overrideId = siteIdOverride(this.env, country);
    if (overrideId) {
      const hit = allSites.find((s) => s.id === overrideId);
      if (!hit) {
        throw new Error(`1xPartners: XPARTNERS_SITE_ID_${country}=${overrideId} не найден в списке сайтов.`);
      }
      const bundle = { sites: [{ id: hit.id, label: hit.name }], label: hit.name };
      this.siteBundleCache.set(country, bundle);
      return bundle;
    }

    const wantUrl = siteUrlForCountry(this.env, country).toLowerCase();
    const hints = SITE_HINTS[country];
    const exact = allSites.filter((s) => s.name.toLowerCase() === wantUrl);
    const byHints = allSites.filter((s) => {
      const n = s.name.toLowerCase();
      return hints.some((h) => n.includes(h));
    });
    const matched = [...new Map([...exact, ...byHints].map((s) => [Number(s.id), s])).values()];
    if (!matched.length) {
      throw new Error(
        `1xPartners: не найден сайт для ${country} (ожидали ${wantUrl} или подсказки ${hints.join(", ")}).`,
      );
    }

    const label =
      matched.length === 1
        ? matched[0]!.name
        : `${matched.length} сайта · ${country} (${matched.map((s) => s.name).slice(0, 2).join(", ")}${matched.length > 2 ? "…" : ""})`;
    const bundle = {
      sites: matched.map((s) => ({ id: Number(s.id), label: s.name })),
      label,
    };
    this.siteBundleCache.set(country, bundle);
    return bundle;
  }

  private async fetchQuickReportTotals(filter: {
    currencyId: number;
    siteId?: number;
    startPeriod: string;
    endPeriod: string;
  }): Promise<{ status?: string; total: QuickReportTotals }> {
    if (this.preferMultiWebApi()) {
      try {
        const period = multiRestTodayPeriod();
        return await this.fetchQuickReportTotalsMulti({
          merchantId: filter.currencyId,
          siteId: filter.siteId,
          startPeriod: period.startPeriod,
          endPeriod: period.endPeriod,
        });
      } catch (error) {
        if (!(error instanceof Error && error.message.includes("COOKIE_REJECTED"))) {
          throw error;
        }
      }
    }
    const deadline = Date.now() + 60_000;
    let lastStatus: string | undefined;
    let total: QuickReportTotals | undefined;
    let partnerMissing = false;

    for (;;) {
      const batch = await this.graphql<
        Array<{
          data?: {
            authorized?: {
              partner?: {
                reports?: {
                  quickReport?: {
                    status?: string;
                    total?: QuickReportTotals;
                  };
                };
              } | null;
            };
          };
          errors?: Array<{ message?: string; extensions?: unknown }>;
        }>
      >([
        {
          operationName: "GetQuickReport",
          variables: { filter },
          query: GET_QUICK_REPORT,
        },
      ]);
      const first = batch?.[0];
      if (first?.errors?.length) {
        console.warn("1xPartners GetQuickReport errors:", JSON.stringify(first.errors).slice(0, 2000));
        throw new Error(formatGraphqlErrors(first.errors));
      }
      const partner = first?.data?.authorized?.partner;
      if (!partner) {
        partnerMissing = true;
        break;
      }
      const quickReport = partner.reports?.quickReport;
      lastStatus = quickReport?.status;
      total = quickReport?.total;
      if (lastStatus !== "PENDING") {
        break;
      }
      if (Date.now() >= deadline) {
        throw new Error("1xPartners: отчёт ещё формируется (PENDING), попробуйте через минуту.");
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }

    if (partnerMissing) {
      throw new Error(
        "1xPartners: нет доступа к partner.reports (сессия не партнёрская или cookie устарел).",
      );
    }

    if (lastStatus === "ERROR") {
      throw new Error("1xPartners: ошибка формирования быстрого отчёта (status ERROR).");
    }

    if (lastStatus === "SUCCESS" && totalsLookEmpty(total)) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const retry = await this.graphql<
        Array<{
          data?: {
            authorized?: {
              partner?: {
                reports?: {
                  quickReport?: { status?: string; total?: QuickReportTotals };
                };
              } | null;
            };
          };
        }>
      >([
        {
          operationName: "GetQuickReport",
          variables: { filter },
          query: GET_QUICK_REPORT,
        },
      ]);
      const qr = retry?.[0]?.data?.authorized?.partner?.reports?.quickReport;
      if (qr?.total && !totalsLookEmpty(qr.total)) {
        return { status: qr.status, total: qr.total };
      }
    }

    return { status: lastStatus, total: total ?? {} };
  }

  private subpartnerReportFilter(period: { startPeriod: string; endPeriod: string }): Record<string, unknown> {
    return {
      currencyId: resolveCurrencyId(this.env),
      startPeriod: period.startPeriod,
      endPeriod: period.endPeriod,
      methood: "get",
    };
  }

  private async fetchSubpartnerReportOnce(filter: Record<string, unknown>): Promise<{
    status?: string;
    rows: SubpartnerReportRow[];
  }> {
    const deadline = Date.now() + 90_000;
    let lastStatus: string | undefined;
    let rows: SubpartnerReportRow[] = [];

    for (;;) {
      const batch = await this.graphql<
        Array<{
          data?: {
            authorized?: {
              partner?: {
                reports?: {
                  subpartnerReport?: {
                    status?: string;
                    rows?: SubpartnerReportRow[];
                  };
                };
              } | null;
            };
          };
          errors?: Array<{ message?: string; extensions?: unknown }>;
        }>
      >(
        [
          {
            operationName: "GetSubpartnerReport",
            variables: { filter },
            query: GET_SUBPARTNER_REPORT,
          },
        ],
        `${BASE}/ru/partner/report-subpartners`,
      );
      const first = batch?.[0];
      if (first?.errors?.length) {
        throw new Error(formatGraphqlErrors(first.errors));
      }
      const partner = first?.data?.authorized?.partner;
      if (!partner) {
        throw new Error("1xPartners: нет доступа к отчёту по суб-партнёрам.");
      }
      const report = partner.reports?.subpartnerReport;
      lastStatus = report?.status;
      rows = report?.rows ?? [];
      if (lastStatus !== "PENDING") {
        break;
      }
      if (Date.now() >= deadline) {
        throw new Error("1xPartners: отчёт по суб-партнёрам ещё формируется (PENDING).");
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }

    if (lastStatus === "ERROR") {
      throw new Error("1xPartners: ошибка отчёта по суб-партнёрам (status ERROR).");
    }

    return { status: lastStatus, rows };
  }

  private async fetchSubpartnerStatsToday(country: XPartnersCountry): Promise<XPartnersQuickStats> {
    let matched: SubpartnerReportRow[] = [];
    let usedPeriod = quickReportTodayPeriod();

    for (const period of todayReportPeriodVariants()) {
      const { rows } = await this.fetchSubpartnerReportOnce(this.subpartnerReportFilter(period));
      const hits = rows.filter((row) => subpartnerRowMatchesCountry(row, country, this.env));
      if (hits.length) {
        matched = hits;
        usedPeriod = period;
        break;
      }
      if (rows.length && !matched.length) {
        matched = hits;
        usedPeriod = period;
      }
    }

    const registrations = matched.reduce((sum, row) => sum + Number(row.countOfRegistrations ?? 0), 0);
    const ftdN = matched.reduce((sum, row) => sum + Number(row.countOfNewAccountsWithDeposits ?? 0), 0);
    const siteLabel =
      matched.length === 1
        ? (matched[0]?.siteName || DEFAULT_SITE_URL[country]).trim()
        : matched.length > 1
          ? `${matched.length} суб · ${country}`
          : DEFAULT_SITE_URL[country];

    if (registrations === 0 && ftdN === 0) {
      console.warn(
        `1xPartners ${country}: subpartners zero · period=${usedPeriod.startPeriod}/${usedPeriod.endPeriod}`,
      );
    }

    return {
      registrations,
      newAccountsWithDeposits: ftdN,
      fetchedAt: new Date().toISOString(),
      siteLabel,
    };
  }

  async fetchQuickStatsToday(country: XPartnersCountry): Promise<XPartnersQuickStats> {
    if (!this.loggedIn) {
      await this.ensureSession();
    }
    if (usesSubpartnerStats(this.env)) {
      return this.fetchSubpartnerStatsToday(country);
    }
    const { sites, label: siteLabel } = await this.resolveSitesForCountry(country);
    const { startPeriod, endPeriod } = quickReportTodayPeriod();
    const currencyId = resolveCurrencyId(this.env);
    const baseFilter = { currencyId, startPeriod, endPeriod };

    const perSite: QuickReportTotals[] = [];
    let usedFilter = baseFilter;

    const fetchAllSites = async (filter: typeof baseFilter & { siteId?: number }) => {
      const totals: QuickReportTotals[] = [];
      for (const site of sites) {
        const { status, total } = await this.fetchQuickReportTotals({ ...filter, siteId: site.id });
        totals.push(total);
        if (totalsLookEmpty(total)) {
          console.warn(
            `1xPartners ${country}: empty total · siteId=${site.id} name=${site.label} status=${status} filter=${JSON.stringify({ ...filter, siteId: site.id })}`,
          );
        }
      }
      return totals;
    };

    perSite.push(...(await fetchAllSites(baseFilter)));

    let total =
      sites.length === 1 ? (perSite[0] ?? {}) : sumQuickReportTotals(perSite);

    if (totalsLookEmpty(total)) {
      const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: XP_REPORT_TIMEZONE }).format(
        new Date(),
      );
      const altFilter = {
        ...baseFilter,
        startPeriod: `${dayKey}T00:00:00.000Z`,
        endPeriod: `${dayKey}T23:59:59.999Z`,
      };
      const altPerSite = await fetchAllSites(altFilter);
      const altTotal =
        sites.length === 1 ? (altPerSite[0] ?? {}) : sumQuickReportTotals(altPerSite);
      if (!totalsLookEmpty(altTotal)) {
        perSite.length = 0;
        perSite.push(...altPerSite);
        total = altTotal;
        usedFilter = altFilter;
      }
    }
    const ftd =
      total.newDepositors ??
      total.countOfRegistrationsWithDeposits ??
      total.countOfAccountsWithDeposits ??
      0;
    const registrations = Number(total.countOfRegistrations ?? 0);
    const ftdN = Number(ftd);

    if (registrations === 0 && ftdN === 0) {
      console.warn(
        `1xPartners ${country}: zero after fetch · sites=${sites.map((s) => `${s.id}:${s.label}`).join("|")} · currencyId=${currencyId} · period=${usedFilter.startPeriod}/${usedFilter.endPeriod}`,
      );
    }

    return {
      registrations,
      newAccountsWithDeposits: ftdN,
      fetchedAt: new Date().toISOString(),
      siteLabel,
    };
  }

  private playersReportBaseFilter(
    scope: { siteId: number } | { country: XPartnersCountry },
    options?: {
      onlyNewPlayers?: boolean;
      withoutDepositsOnly?: boolean;
      startPeriod?: string;
      endPeriod?: string;
    },
  ): Record<string, unknown> {
    const period = playersReportTodayPeriodFullDay();
    const filter: Record<string, unknown> = {
      currencyId: resolveCurrencyId(this.env),
      startPeriod: options?.startPeriod ?? period.startPeriod,
      endPeriod: options?.endPeriod ?? period.endPeriod,
      methood: "get",
      onlyNewPlayers: options?.onlyNewPlayers ?? false,
      withoutDepositsOnly: options?.withoutDepositsOnly ?? false,
      subId: "",
    };
    if ("siteId" in scope) {
      filter.siteId = scope.siteId;
    } else {
      filter.country = COUNTRY_API_NAME[scope.country];
    }
    return filter;
  }

  private async fetchPlayersReportOnce(filter: Record<string, unknown>): Promise<{
    status?: string;
    hash?: string;
    pagesCount?: number;
    rows: PlayersReportRow[];
  }> {
    const deadline = Date.now() + 90_000;
    let lastStatus: string | undefined;
    let payload:
      | {
          status?: string;
          hash?: string;
          pagesCount?: number;
          rows?: PlayersReportRow[];
        }
      | undefined;

    for (;;) {
      const batch = await this.graphqlPlayersReport<
        Array<{
          data?: {
            authorized?: {
              partner?: {
                reports?: {
                  playersReport?: {
                    status?: string;
                    hash?: string;
                    pagesCount?: number;
                    rows?: PlayersReportRow[];
                  };
                };
              } | null;
            };
          };
          errors?: Array<{ message?: string; extensions?: unknown }>;
        }>
      >([
        {
          operationName: "GetPlayersReport",
          variables: { filter },
          query: GET_PLAYERS_REPORT,
        },
      ]);
      const first = batch?.[0];
      if (first?.errors?.length) {
        console.warn("1xPartners GetPlayersReport errors:", JSON.stringify(first.errors).slice(0, 2000));
        throw new Error(formatGraphqlErrors(first.errors));
      }
      const partner = first?.data?.authorized?.partner;
      if (!partner) {
        throw new Error(
          "1xPartners: нет доступа к отчёту по игрокам (partner.reports).",
        );
      }
      payload = partner.reports?.playersReport;
      lastStatus = payload?.status;
      if (lastStatus !== "PENDING") {
        break;
      }
      if (Date.now() >= deadline) {
        throw new Error("1xPartners: отчёт по игрокам ещё формируется (PENDING).");
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }

    if (lastStatus === "ERROR") {
      throw new Error(
        `1xPartners: ошибка отчёта по игрокам (status ERROR) · filter=${JSON.stringify(filter).slice(0, 400)}`,
      );
    }

    return {
      status: lastStatus,
      hash: payload?.hash,
      pagesCount: payload?.pagesCount,
      rows: payload?.rows ?? [],
    };
  }

  private async fetchPlayersReportAllRows(
    scope: { siteId: number } | { country: XPartnersCountry },
    options?: {
      onlyNewPlayers?: boolean;
      withoutDepositsOnly?: boolean;
      startPeriod?: string;
      endPeriod?: string;
    },
  ): Promise<PlayersReportRow[]> {
    const base = this.playersReportBaseFilter(scope, options);
    const load = async (extra: Record<string, unknown>) => {
      const first = await this.fetchPlayersReportOnce({ ...base, ...extra });
      const acc = [...(first.rows ?? [])];
      const pagesCount = Math.max(1, Number(first.pagesCount ?? 1));
      let hash = first.hash;
      for (let page = 2; page <= pagesCount && page <= 100; page++) {
        const next = await this.fetchPlayersReportOnce({
          ...base,
          ...extra,
          pageNumber: page,
          countOnPage: 100,
          ...(hash ? { hash } : {}),
        });
        acc.push(...(next.rows ?? []));
        hash = next.hash ?? hash;
      }
      return acc;
    };

    let rows = await load({});
    if (rows.length <= 4) {
      const paged = await load({ pageNumber: 1, countOnPage: 100 });
      if (paged.length > rows.length) {
        rows = paged;
      }
    }
    return rows;
  }

  private ingestPlayerReportRows(
    idSet: Set<string>,
    rows: PlayersReportRow[],
    dayKey: string,
    mode: "all" | "registeredToday",
  ): void {
    for (const row of rows) {
      if (mode === "registeredToday" && registrationDayKey(row.registrationDate) !== dayKey) {
        continue;
      }
      const id = String(row.playerId ?? "").trim();
      if (id) {
        idSet.add(id);
      }
    }
  }

  private static readonly NEW_PLAYER_REPORT_VARIANTS = [
    { onlyNewPlayers: true, withoutDepositsOnly: true },
    { onlyNewPlayers: true, withoutDepositsOnly: false },
  ] as const;

  private async addPlayerIdsFromReports(
    idSet: Set<string>,
    scope: { siteId: number },
    dayKey: string,
    label: string,
    options: {
      variants: ReadonlyArray<{ onlyNewPlayers: boolean; withoutDepositsOnly: boolean }>;
      periods: Array<{ startPeriod: string; endPeriod: string }>;
      mode: "all" | "registeredToday";
    },
  ): Promise<void> {
    let first = true;
    for (const period of options.periods) {
      for (const variant of options.variants) {
        if (!first) {
          await new Promise((resolve) => setTimeout(resolve, 400));
        }
        first = false;
        try {
          const rows = await this.fetchPlayersReportAllRows(scope, {
            ...variant,
            ...period,
          });
          console.log(
            `1xPartners ${label}: playersReport onlyNew=${variant.onlyNewPlayers} noDep=${variant.withoutDepositsOnly} end=${period.endPeriod} mode=${options.mode} rows=${rows.length}`,
          );
          this.ingestPlayerReportRows(idSet, rows, dayKey, options.mode);
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          console.warn(
            `1xPartners ${label}: skip playersReport variant onlyNew=${variant.onlyNewPlayers} noDep=${variant.withoutDepositsOnly} · ${msg}`,
          );
        }
      }
    }
  }

  async fetchPlayerIdsToday(country: XPartnersCountry): Promise<XPartnersPlayersToday> {
    await this.ensureSession();
    const dayKey = todayDayKey();
    const { sites, label: siteLabel } = await this.resolveSitesForCountry(country);
    const quick = await this.fetchQuickStatsToday(country);
    const idSet = new Set<string>();
    const quickPeriod = quickReportTodayPeriod();
    const newVariants = XPartnersClient.NEW_PLAYER_REPORT_VARIANTS;

    for (const site of sites) {
      await this.addPlayerIdsFromReports(idSet, { siteId: site.id }, dayKey, `${country}:site${site.id}`, {
        variants: newVariants,
        periods: [quickPeriod],
        mode: "all",
      });
    }

    if (idSet.size < quick.registrations) {
      for (const site of sites) {
        await this.addPlayerIdsFromReports(idSet, { siteId: site.id }, dayKey, `${country}:site${site.id}:fallback`, {
          variants: newVariants,
          periods: todayReportPeriodVariants(),
          mode: "all",
        });
        await this.addPlayerIdsFromReports(idSet, { siteId: site.id }, dayKey, `${country}:site${site.id}:fallback`, {
          variants: [{ onlyNewPlayers: false, withoutDepositsOnly: false }],
          periods: todayReportPeriodVariants(),
          mode: "registeredToday",
        });
      }
    }

    let playerIds = [...idSet].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

    if (playerIds.length > quick.registrations && quick.registrations > 0) {
      const byRegDate = new Set<string>();
      for (const site of sites) {
        await this.addPlayerIdsFromReports(
          byRegDate,
          { siteId: site.id },
          dayKey,
          `${country}:site${site.id}:trim`,
          {
            variants: newVariants,
            periods: todayReportPeriodVariants(),
            mode: "registeredToday",
          },
        );
      }
      if (byRegDate.size > 0 && byRegDate.size <= playerIds.length) {
        console.log(
          `1xPartners ${country}: trim player IDs ${playerIds.length} → ${byRegDate.size} (registrationDate=${dayKey}, сводка рег=${quick.registrations})`,
        );
        playerIds = [...byRegDate].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      }
    }

    if (
      quick.registrations > 0 &&
      playerIds.length === quick.newAccountsWithDeposits &&
      playerIds.length < quick.registrations
    ) {
      console.warn(
        `1xPartners ${country}: ID count matches FTD (${playerIds.length}) but registrations=${quick.registrations} — need XPARTNERS_REPORTS_COOKIE from «Отчёт по игрокам»`,
      );
    }

    if (quick.registrations > 0 && playerIds.length !== quick.registrations) {
      const hint = this.playersReportCookieHeader()
        ? ""
        : " · задайте XPARTNERS_REPORTS_COOKIE со страницы «Отчёт по игрокам»";
      console.warn(
        `1xPartners ${country}: player IDs ${playerIds.length} vs registrations ${quick.registrations}${hint}`,
      );
    }

    return {
      country,
      dayKey,
      siteLabel,
      playerIds,
      registrationsExpected: quick.registrations,
      fetchedAt: new Date().toISOString(),
    };
  }
}

let sharedClient: XPartnersClient | null = null;
let sharedMeta: AppMetaStore | undefined;

function hasStoredOrEnvAuth(
  env: AppEnv,
  flags: {
    hasStoredCookie: boolean;
    hasStoredCredentials: boolean;
    hasEnvCookie: boolean;
    hasEnvCredentials: boolean;
  },
): boolean {
  return (
    flags.hasStoredCookie ||
    flags.hasStoredCredentials ||
    flags.hasEnvCookie ||
    flags.hasEnvCredentials ||
    Boolean(parseCredentials(env)) ||
    Boolean(cookiesFromEnv(env))
  );
}

export function configureXPartnersSessionStore(meta: AppMetaStore): void {
  sharedMeta = meta;
}

export function getXPartnersClient(env: AppEnv): XPartnersClient | null {
  if (!env.XPARTNERS_ENABLED) {
    return null;
  }
  if (!sharedClient) {
    sharedClient = new XPartnersClient(env, sharedMeta);
  }
  return sharedClient;
}

export function startXPartnersKeepAlive(env: AppEnv): void {
  if (!shouldFetchStatsFromApi(env)) {
    return;
  }
  const client = getXPartnersClient(env);
  if (!client) {
    return;
  }
  const minutes = Math.max(1, env.XPARTNERS_KEEPALIVE_MINUTES);
  const ms = minutes * 60_000;
  void client.keepAlive();
  setInterval(() => {
    void client.keepAlive();
  }, ms);
  console.log(`1xPartners: session keep-alive every ${minutes} min (ping + auto-refresh on expiry)`);
}
