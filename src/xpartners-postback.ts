import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { URL } from "node:url";
import type { AppEnv } from "./env.js";
import type { AppMetaStore } from "./app-meta-store.js";
import type { XPartnersCountry, XPartnersQuickStats } from "./xpartners-client.js";
import {
  loadGlobalPartnerStats,
  saveGlobalPartnerStats,
  type GlobalPartnerStatsState,
} from "./xpartners-stats-cache.js";

export const XPARTNERS_POSTBACK_META_KEY = "xpartners_postback_day";
export const XPARTNERS_POSTBACK_LOG_META_KEY = "xpartners_postback_log";

const XP_REPORT_TIMEZONE = "Europe/Kyiv";
const MAX_DEDUPE_IDS = 500;

type PostbackEvent = "reg" | "ftd";

type PostbackDayState = {
  dayKey: string;
  byCountry: Partial<
    Record<
      XPartnersCountry,
      {
        registrations: number;
        ftd: number;
        seen: string[];
      }
    >
  >;
};

type PostbackLogState = {
  dayKey: string;
  accepted: number;
  rejected: number;
  lastAcceptedAt?: string;
  lastAccepted?: string;
  lastRejectedAt?: string;
  lastRejected?: string;
};

type PostbackRouteHint = {
  country?: XPartnersCountry;
  event?: PostbackEvent;
};

import { usesHybridStats, usesPostbackServer } from "./env.js";

export function usesPostbackStats(env: AppEnv): boolean {
  return env.XPARTNERS_STATS_SOURCE === "postback";
}

export function usesPostbackStatsForFetch(env: AppEnv): boolean {
  return usesPostbackStats(env) && !usesHybridStats(env);
}

function todayDayKey(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: XP_REPORT_TIMEZONE }).format(new Date());
}

function siteLabel(country: XPartnersCountry, env: AppEnv): string {
  if (country === "CM") {
    return env.XPARTNERS_SITE_CM;
  }
  if (country === "EG") {
    return env.XPARTNERS_SITE_EG;
  }
  if (country === "ZM") {
    return env.XPARTNERS_SITE_ZM;
  }
  return env.XPARTNERS_SITE_RW;
}

function parseCountry(raw: string | null | undefined): XPartnersCountry | null {
  const code = (raw || "").trim().toUpperCase();
  if (code === "CM" || code === "EG" || code === "ZM" || code === "RW") {
    return code;
  }
  return null;
}

function parseEvent(raw: string | null | undefined): PostbackEvent | null {
  const value = (raw || "").trim().toLowerCase();
  if (!value) {
    return null;
  }
  if (value === "reg" || value === "registration" || value === "registrations" || value === "signup") {
    return "reg";
  }
  if (
    value === "ftd" ||
    value === "deposit" ||
    value === "first_deposit" ||
    value === "firstdeposit" ||
    value === "new_deposit" ||
    value === "dep"
  ) {
    return "ftd";
  }
  return null;
}

function macroFilled(value: string | null | undefined): boolean {
  const v = (value || "").trim();
  return Boolean(v && !/^\{/.test(v));
}

function parseEventFromParams(params: URLSearchParams, route?: PostbackRouteHint): PostbackEvent | null {
  if (route?.event) {
    return route.event;
  }
  const explicit = parseEvent(
    params.get("event") ?? params.get("type") ?? params.get("postback_type") ?? params.get("goal"),
  );
  if (explicit) {
    return explicit;
  }
  for (const [key, rawValue] of params.entries()) {
    const keyLower = key.trim().toLowerCase();
    const value = rawValue.trim();
    if (!value || /^\{/.test(value)) {
      continue;
    }
    if (keyLower === "reg" || keyLower === "registration" || keyLower === "signup") {
      return "reg";
    }
    if (
      keyLower === "ftd" ||
      keyLower === "deposit" ||
      keyLower === "first_deposit" ||
      keyLower === "firstdeposit"
    ) {
      return "ftd";
    }
  }
  if (macroFilled(params.get("reg"))) {
    return "reg";
  }
  if (macroFilled(params.get("ftd"))) {
    return "ftd";
  }
  if (macroFilled(params.get("deposit")) || macroFilled(params.get("sumdep"))) {
    return "ftd";
  }
  return null;
}

function inferCountryFromPostbackSite(env: AppEnv, siteHint: string | null | undefined): XPartnersCountry | null {
  const raw = (siteHint || "").trim().toLowerCase();
  if (!raw) {
    return null;
  }
  if (/camerun|cameroon|cameroun|\.cm\b|кamer/i.test(raw)) {
    return "CM";
  }
  if (/zambia|\.zm\b|zamb/i.test(raw)) {
    return "ZM";
  }
  if (/egypt|egypt\.com|егип/i.test(raw)) {
    return "EG";
  }
  if (/rwanda|ruand|\.rw\b/i.test(raw)) {
    return "RW";
  }
  return parseCountryFromSite(new URLSearchParams({ site: raw }), env);
}

function parseCountryFromSite(params: URLSearchParams, env: AppEnv): XPartnersCountry | null {
  const siteRaw = (params.get("site") ?? params.get("site_id") ?? params.get("website") ?? "").trim().toLowerCase();
  if (!siteRaw) {
    return null;
  }
  const pairs: Array<[XPartnersCountry, string]> = [
    ["CM", env.XPARTNERS_SITE_CM],
    ["EG", env.XPARTNERS_SITE_EG],
    ["ZM", env.XPARTNERS_SITE_ZM],
    ["RW", env.XPARTNERS_SITE_RW],
  ];
  for (const [country, label] of pairs) {
    const hint = label.replace(/^https?:\/\//i, "").replace(/\/$/, "").toLowerCase();
    if (siteRaw.includes(hint) || hint.includes(siteRaw)) {
      return country;
    }
  }
  if (/camer|cameroon|кamer/i.test(siteRaw)) {
    return "CM";
  }
  if (/zamb|zambia/i.test(siteRaw)) {
    return "ZM";
  }
  if (/egypt|egip|егип/i.test(siteRaw)) {
    return "EG";
  }
  if (/rwand|ruand|руанд/i.test(siteRaw)) {
    return "RW";
  }
  return null;
}

function parseRouteFromPath(pathname: string): PostbackRouteHint {
  const parts = pathname.split("/").filter(Boolean);
  // /xpartners/postback/cm/reg
  if (parts.length >= 4 && parts[0] === "xpartners" && parts[1] === "postback") {
    return {
      country: parseCountry(parts[2]) ?? undefined,
      event: parseEvent(parts[3]) ?? undefined,
    };
  }
  return {};
}

function sanitizeParamsForLog(params: URLSearchParams): string {
  const parts: string[] = [];
  for (const [key, value] of params.entries()) {
    if (key.toLowerCase() === "token") {
      parts.push("token=***");
      continue;
    }
    parts.push(`${key}=${value.slice(0, 80)}`);
  }
  return parts.join("&");
}

async function loadPostbackLog(meta: AppMetaStore): Promise<PostbackLogState> {
  const dayKey = todayDayKey();
  const raw = (await meta.get(XPARTNERS_POSTBACK_LOG_META_KEY))?.trim();
  if (!raw) {
    return { dayKey, accepted: 0, rejected: 0 };
  }
  try {
    const parsed = JSON.parse(raw) as PostbackLogState;
    if (parsed.dayKey !== dayKey) {
      return { dayKey, accepted: 0, rejected: 0 };
    }
    return parsed;
  } catch {
    return { dayKey, accepted: 0, rejected: 0 };
  }
}

async function savePostbackLog(meta: AppMetaStore, state: PostbackLogState): Promise<void> {
  await meta.set(XPARTNERS_POSTBACK_LOG_META_KEY, JSON.stringify(state));
}

async function recordPostbackAccepted(
  meta: AppMetaStore,
  country: XPartnersCountry,
  event: PostbackEvent,
): Promise<void> {
  const log = await loadPostbackLog(meta);
  log.accepted += 1;
  log.lastAcceptedAt = new Date().toISOString();
  log.lastAccepted = `${country} ${event}`;
  await savePostbackLog(meta, log);
}

async function recordPostbackRejected(meta: AppMetaStore, reason: string, params: URLSearchParams): Promise<void> {
  const log = await loadPostbackLog(meta);
  log.rejected += 1;
  log.lastRejectedAt = new Date().toISOString();
  log.lastRejected = `${reason} · ${sanitizeParamsForLog(params)}`;
  await savePostbackLog(meta, log);
  console.warn(`1xPartners postback rejected: ${reason} · ${sanitizeParamsForLog(params)}`);
}

export async function describePostbackActivity(meta: AppMetaStore): Promise<string> {
  const log = await loadPostbackLog(meta);
  const lines = [`Postback сегодня: принято ${log.accepted}, отклонено ${log.rejected}`];
  if (log.lastAcceptedAt && log.lastAccepted) {
    lines.push(`Последний OK: ${log.lastAccepted} · ${formatLogTime(log.lastAcceptedAt)}`);
  }
  if (log.rejected > 0 && log.lastRejected) {
    lines.push(`Последний отказ: ${log.lastRejected.slice(0, 120)}`);
  }
  if (log.accepted === 0 && log.rejected === 0) {
    lines.push("1xPartners ещё не слал postback на Railway URL.");
    lines.push("Проверь: статус Active · «Ссылка для размещения» в трекере · не прямые ссылки.");
  } else if (log.accepted <= 1 && log.rejected === 0) {
    lines.push("В кабинете рег больше — postback не доходит (трафик мимо цепочки или не Active).");
  }
  return lines.join("\n");
}

function formatLogTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: XP_REPORT_TIMEZONE,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function dedupeKey(params: URLSearchParams): string | null {
  for (const key of [
    "click_id",
    "clickid",
    "clickId",
    "player_id",
    "playerId",
    "subid",
    "sub_id",
    "reg",
    "ftd",
    "transaction_id",
    "tid",
  ]) {
    const value = params.get(key)?.trim();
    if (value && !/^\{/.test(value)) {
      return `${key}:${value}`;
    }
  }
  return null;
}

async function loadPostbackDay(meta: AppMetaStore): Promise<PostbackDayState> {
  const dayKey = todayDayKey();
  const raw = (await meta.get(XPARTNERS_POSTBACK_META_KEY))?.trim();
  if (!raw) {
    return { dayKey, byCountry: {} };
  }
  try {
    const parsed = JSON.parse(raw) as PostbackDayState;
    if (parsed.dayKey !== dayKey) {
      return { dayKey, byCountry: {} };
    }
    return parsed;
  } catch {
    return { dayKey, byCountry: {} };
  }
}

async function savePostbackDay(meta: AppMetaStore, state: PostbackDayState): Promise<void> {
  await meta.set(XPARTNERS_POSTBACK_META_KEY, JSON.stringify(state));
}

async function syncGlobalStatsCache(meta: AppMetaStore, env: AppEnv, day: PostbackDayState): Promise<void> {
  const global = await loadGlobalPartnerStats(meta);
  const countries: XPartnersCountry[] = ["CM", "EG", "ZM", "RW"];
  const byCountry: GlobalPartnerStatsState["byCountry"] = { ...(global.byCountry ?? {}) };
  const fetchedAt = new Date().toISOString();
  for (const country of countries) {
    const bucket = day.byCountry[country];
    byCountry[country] = {
      registrations: bucket?.registrations ?? 0,
      newAccountsWithDeposits: bucket?.ftd ?? 0,
      fetchedAt,
      siteLabel: siteLabel(country, env),
    };
  }
  await saveGlobalPartnerStats(meta, {
    refreshIntervalHours: global.refreshIntervalHours,
    cachedAt: fetchedAt,
    byCountry,
  });
}

export async function loadPostbackCountryStats(
  meta: AppMetaStore,
  env: AppEnv,
  country: XPartnersCountry,
): Promise<XPartnersQuickStats> {
  const day = await loadPostbackDay(meta);
  const bucket = day.byCountry[country];
  return {
    registrations: bucket?.registrations ?? 0,
    newAccountsWithDeposits: bucket?.ftd ?? 0,
    fetchedAt: new Date().toISOString(),
    siteLabel: siteLabel(country, env),
  };
}

export async function handlePostbackRequest(
  meta: AppMetaStore,
  env: AppEnv,
  params: URLSearchParams,
  route: PostbackRouteHint = {},
): Promise<{ ok: true; country: XPartnersCountry; event: PostbackEvent } | { ok: false; status: number; message: string }> {
  const event = parseEventFromParams(params, route);
  if (!event) {
    await recordPostbackRejected(meta, "missing event (reg/ftd)", params);
    return { ok: false, status: 400, message: "missing event (reg/ftd)" };
  }

  const token = env.XPARTNERS_POSTBACK_TOKEN?.trim();
  if (token) {
    const got = params.get("token")?.trim();
    if (got !== token) {
      await recordPostbackRejected(meta, "invalid token", params);
      return { ok: false, status: 403, message: "invalid token" };
    }
  }

  const country =
    route.country ??
    parseCountry(params.get("country") ?? params.get("geo") ?? params.get("c")) ??
    inferCountryFromPostbackSite(
      env,
      params.get("site") ??
        params.get("site_id") ??
        params.get("website") ??
        params.get("site_name") ??
        params.get("offer"),
    ) ??
    parseCountryFromSite(params, env);
  if (!country) {
    await recordPostbackRejected(meta, "missing country", params);
    return { ok: false, status: 400, message: "missing country=CM|EG|ZM|RW" };
  }

  const day = await loadPostbackDay(meta);
  const bucket = day.byCountry[country] ?? { registrations: 0, ftd: 0, seen: [] as string[] };
  const idKey = dedupeKey(params);
  if (idKey && bucket.seen.includes(idKey)) {
    await syncGlobalStatsCache(meta, env, day);
    return { ok: true, country, event };
  }

  if (event === "reg") {
    bucket.registrations += 1;
  } else {
    bucket.ftd += 1;
  }
  if (idKey) {
    bucket.seen = [...bucket.seen, idKey].slice(-MAX_DEDUPE_IDS);
  }
  day.byCountry[country] = bucket;
  await savePostbackDay(meta, day);
  await syncGlobalStatsCache(meta, env, day);
  await recordPostbackAccepted(meta, country, event);
  console.log(`1xPartners postback: ${country} ${event}${idKey ? ` · ${idKey}` : ""} · ${sanitizeParamsForLog(params)}`);
  return { ok: true, country, event };
}

function writeText(res: ServerResponse, status: number, body: string): void {
  res.writeHead(status, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(body);
}

async function readUrl(req: IncomingMessage): Promise<URL> {
  const host = req.headers.host || "localhost";
  return new URL(req.url || "/", `http://${host}`);
}

async function readRequestParams(req: IncomingMessage, url: URL): Promise<URLSearchParams> {
  const params = new URLSearchParams(url.searchParams);
  if (req.method !== "POST") {
    return params;
  }
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const body = Buffer.concat(chunks).toString("utf8").trim();
  if (!body) {
    return params;
  }
  const contentType = (req.headers["content-type"] || "").toLowerCase();
  if (contentType.includes("application/json")) {
    try {
      const json = JSON.parse(body) as Record<string, unknown>;
      for (const [key, value] of Object.entries(json)) {
        if (value != null && typeof value !== "object") {
          params.set(key, String(value));
        }
      }
    } catch {
      // ignore malformed json
    }
    return params;
  }
  const extra = new URLSearchParams(body);
  for (const [key, value] of extra.entries()) {
    params.set(key, value);
  }
  return params;
}

function isPostbackPath(pathname: string): boolean {
  return pathname === "/xpartners/postback" || pathname.startsWith("/xpartners/postback/");
}

export function startXPartnersPostbackServer(env: AppEnv, meta: AppMetaStore): void {
  if (!usesPostbackServer(env)) {
    return;
  }
  const port = Number(process.env.PORT || 3000);
  const publicBase = (env.XPARTNERS_POSTBACK_PUBLIC_URL || "").replace(/\/$/, "");

  const server = createServer((req, res) => {
    void (async () => {
      try {
        const url = await readUrl(req);
        if (url.pathname === "/health" || url.pathname === "/") {
          writeText(res, 200, "ok");
          return;
        }
        if (!isPostbackPath(url.pathname)) {
          writeText(res, 404, "not found");
          return;
        }
        if (req.method !== "GET" && req.method !== "HEAD" && req.method !== "POST") {
          writeText(res, 405, "method not allowed");
          return;
        }
        const route = parseRouteFromPath(url.pathname);
        const params = await readRequestParams(req, url);
        console.log(
          `1xPartners postback hit: ${req.method} ${url.pathname}${url.search ? `?${sanitizeParamsForLog(params)}` : ""}`,
        );
        const result = await handlePostbackRequest(meta, env, params, route);
        if (!result.ok) {
          writeText(res, result.status, result.message);
          return;
        }
        if (req.method === "HEAD") {
          res.writeHead(204);
          res.end();
          return;
        }
        writeText(res, 200, "ok");
      } catch (error) {
        console.warn("1xPartners postback error:", error instanceof Error ? error.message : error);
        writeText(res, 500, "error");
      }
    })();
  });

  server.listen(port, "0.0.0.0", () => {
    console.log(`1xPartners postback server on :${port} · /xpartners/postback[/cm/reg|/cm/ftd|…]`);
    if (publicBase) {
      console.log(`1xPartners postback reg CM: ${publicBase}/xpartners/postback/cm/reg?token=***&click_id={click_id}&reg={reg}`);
    } else {
      console.warn("1xPartners: set XPARTNERS_POSTBACK_PUBLIC_URL to your Railway public domain for postback setup.");
    }
  });
}

export type PostbackCabinetSetup = {
  title: string;
  site: string;
  type: string;
  eventNameInSystem: string;
  url: string;
  staticParams: string;
  dynamicParams: Array<{ name: string; value: string }>;
};

export function postbackCabinetSetups(env: AppEnv): PostbackCabinetSetup[] {
  const base = (env.XPARTNERS_POSTBACK_PUBLIC_URL || "https://pagernewtest-production.up.railway.app").replace(
    /\/$/,
    "",
  );
  const token = env.XPARTNERS_POSTBACK_TOKEN?.trim() || "pager_cm_2026_x7";
  const mk = (
    title: string,
    site: string,
    country: string,
    type: string,
    eventName: string,
    eventStatic: string,
    macro: "reg" | "ftd",
  ): PostbackCabinetSetup => ({
    title,
    site,
    type,
    eventNameInSystem: eventName,
    url: `${base}/xpartners/postback`,
    staticParams: `token=${token}&country=${country}&event=${eventStatic}`,
    dynamicParams: [
      { name: "click_id", value: "{click_id}" },
      { name: macro, value: `{${macro}}` },
    ],
  });
  return [
    mk("Registration · Cameroon", "Camerun.com", "CM", "Registration", "reg", "reg", "reg"),
    mk("FTD · Cameroon", "Camerun.com", "CM", "First deposit", "ftd", "ftd", "ftd"),
    mk("Registration · Zambia", "Zambia.com", "ZM", "Registration", "reg", "reg", "reg"),
    mk("FTD · Zambia", "Zambia.com", "ZM", "First deposit", "ftd", "ftd", "ftd"),
  ];
}

export function formatPostbackCabinetSetupText(env: AppEnv): string {
  return postbackCabinetSetups(env)
    .map((p) =>
      [
        `▸ ${p.title}`,
        `Сайт: ${p.site} · Тип: ${p.type}`,
        `Название события: ${p.eventNameInSystem}`,
        `URL: ${p.url}`,
        `Статика: ${p.staticParams}`,
        `Динамика: ${p.dynamicParams.map((d) => `${d.name} → ${d.value}`).join(", ")}`,
      ].join("\n"),
    )
    .join("\n\n");
}

/** Одна строка для быстрой проверки (альтернатива форме кабинета). */
export function postbackSetupHint(env: AppEnv): string {
  const first = postbackCabinetSetups(env)[0];
  if (!first) {
    return "";
  }
  return `${first.url}?${first.staticParams}&click_id={click_id}&reg={reg}`;
}
