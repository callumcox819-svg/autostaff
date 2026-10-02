import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  TELEGRAM_BOT_TOKEN: z.string().min(1),
  TELEGRAM_BOT_NAME: z.string().default("Pager Test Bot"),
  PAGER_BASE_URL: z.string().url().default("https://api.pager.co.ua"),
  /** Web UI origin for Referer/HTML warm-up (login pages stay on www). */
  PAGER_WEB_URL: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.string().url())
    .optional(),
  BOT_CONFIG_PATH: z.string().default("config/bot.config.yaml"),
  BOT_STATE_PATH: z.string().default("data/chat-state.json"),
  DATABASE_URL: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.string().min(1))
    .optional(),
  OCR_LANG: z.string().default("eng"),
  OCR_ENABLED: z
    .string()
    .default("true")
    .transform((value) => value.toLowerCase() !== "false"),
  POLL_INTERVAL_MS: z.coerce.number().int().positive().default(2000),
  AI_ENABLED: z
    .string()
    .default("false")
    .transform((value) => value.toLowerCase() === "true"),
  AI_API_KEY: z
    .preprocess(
      (value) => {
        if (value === "" || value === undefined) {
          return undefined;
        }
        return String(value).replace(/\s+/g, "").trim();
      },
      z.string().min(1),
    )
    .optional(),
  AI_MODEL: z.string().default("gpt-4o-mini"),
  AI_VISION_MODEL: z.string().default("gpt-4o-mini"),
  /** OpenAI-compatible API base, e.g. OpenRouter: https://openrouter.ai/api/v1/chat/completions */
  AI_BASE_URL: z
    .string()
    .url()
    .default("https://api.openai.com/v1/chat/completions"),
  /** Optional — OpenRouter recommends HTTP-Referer */
  AI_HTTP_REFERER: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.string().url())
    .optional(),
  AI_APP_TITLE: z.string().default("Pager Inbox Bot"),

  XPARTNERS_ENABLED: z
    .string()
    .default("false")
    .transform((value) => value.toLowerCase() === "true"),
  XPARTNERS_CREDENTIALS: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  XPARTNERS_LOGIN: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  XPARTNERS_PASSWORD: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  XPARTNERS_COOKIE: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  /** Optional: Cookie copied while on «Отчёт по игрокам» (F12 → graphql → Request Headers). Used only for GetPlayersReport. */
  XPARTNERS_REPORTS_COOKIE: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  XPARTNERS_KEEPALIVE_MINUTES: z.coerce.number().int().positive().default(3),
  /** 1xPartners currency id (6 = USD in partner UI). */
  XPARTNERS_CURRENCY_ID: z.coerce.number().int().positive().default(6),
  /** Skip multi.1xpartners.com web API (403 on Railway) and use 1xpartners.com/graphql directly. Auto on Railway. */
  XPARTNERS_PREFER_GRAPHQL: z
    .string()
    .default("auto")
    .transform((value) => value.trim().toLowerCase()),
  /** quick = отчёт из кабинета; hybrid = отчёт + postback-сервер; postback = только счётчики postback. */
  XPARTNERS_STATS_SOURCE: z
    .preprocess(
      (value) => (value === "" || value === undefined ? "quick" : String(value).trim().toLowerCase()),
      z.enum(["quick", "subpartners", "postback", "hybrid"]),
    )
    .default("quick"),
  /** Secret token in postback URL (?token=). Strongly recommended on Railway. */
  XPARTNERS_POSTBACK_TOKEN: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value)), z.string())
    .optional(),
  /** Public base URL, e.g. https://pagernewtest-production.up.railway.app */
  XPARTNERS_POSTBACK_PUBLIC_URL: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : String(value).trim()), z.string().url())
    .optional(),
  XPARTNERS_SITE_CM: z.string().default("http://Camerun.com"),
  XPARTNERS_SITE_EG: z.string().default("http://Egypt.com"),
  XPARTNERS_SITE_ZM: z.string().default("http://Zambia.com"),
  XPARTNERS_SITE_RW: z.string().default("http://Rwanda.com"),
  XPARTNERS_SITE_ID_CM: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.coerce.number().int().positive())
    .optional(),
  XPARTNERS_SITE_ID_EG: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.coerce.number().int().positive())
    .optional(),
  XPARTNERS_SITE_ID_ZM: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.coerce.number().int().positive())
    .optional(),
  XPARTNERS_SITE_ID_RW: z
    .preprocess((value) => (value === "" || value === undefined ? undefined : value), z.coerce.number().int().positive())
    .optional(),
  /** RW auto-funnel on training channels (built-in scripts). Set false to pause sends only. */
  RW_FUNNEL_ENABLED: z
    .string()
    .default("true")
    .transform((value) => value.toLowerCase() === "true"),
});

export type AppEnv = z.infer<typeof envSchema>;

export function hasXPartnersApiAuth(env: AppEnv): boolean {
  if (env.XPARTNERS_COOKIE?.trim()) {
    return true;
  }
  if (env.XPARTNERS_LOGIN?.trim() && env.XPARTNERS_PASSWORD?.trim()) {
    return true;
  }
  const creds = env.XPARTNERS_CREDENTIALS?.trim();
  return Boolean(creds && creds.includes(":"));
}

/** Postback counters only when explicitly postback AND no cookie/login to pull dashboard stats. */
export function usesPostbackStatsOnly(env: AppEnv): boolean {
  return env.XPARTNERS_STATS_SOURCE === "postback" && !hasXPartnersApiAuth(env);
}

export function usesHybridStats(env: AppEnv): boolean {
  return env.XPARTNERS_STATS_SOURCE === "hybrid";
}

export function usesPostbackServer(env: AppEnv): boolean {
  return env.XPARTNERS_STATS_SOURCE === "postback" || env.XPARTNERS_STATS_SOURCE === "hybrid";
}

/** Pull GetQuickReport from cabinet (needs cookie/login). */
export function shouldFetchStatsFromApi(env: AppEnv): boolean {
  if (env.XPARTNERS_STATS_SOURCE === "quick" || env.XPARTNERS_STATS_SOURCE === "subpartners") {
    return true;
  }
  if (env.XPARTNERS_STATS_SOURCE === "hybrid") {
    return hasXPartnersApiAuth(env);
  }
  return false;
}

export function shouldPreferGraphqlApi(env: AppEnv): boolean {
  const pref = env.XPARTNERS_PREFER_GRAPHQL;
  if (pref === "true" || pref === "1" || pref === "yes") {
    return true;
  }
  if (pref === "false" || pref === "0" || pref === "no") {
    return false;
  }
  return Boolean(process.env.RAILWAY_ENVIRONMENT || process.env.RAILWAY_PROJECT_ID);
}

export function loadEnv(): AppEnv {
  return envSchema.parse(process.env);
}
