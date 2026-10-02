import type { AppEnv } from "./env.js";
import { shouldFetchStatsFromApi } from "./env.js";
import type { AppMetaStore } from "./app-meta-store.js";
import {
  getXPartnersClient,
  cookiesFromEnv,
  curlHeadersFromEnv,
  XPARTNERS_LOGIN_META_KEY,
  XPARTNERS_PASSWORD_META_KEY,
  XPARTNERS_SESSION_META_KEY,
  type XPartnersClient,
} from "./xpartners-client.js";

export {
  XPARTNERS_LOGIN_META_KEY,
  XPARTNERS_PASSWORD_META_KEY,
  XPARTNERS_SESSION_META_KEY,
  type XPartnersSessionStatus,
} from "./xpartners-client.js";

export async function ensureXPartnersSession(env: AppEnv): Promise<XPartnersClient | null> {
  const client = getXPartnersClient(env);
  if (!client) {
    return null;
  }
  await client.ensureSession();
  return client;
}

export async function describeXPartnersSession(
  env: AppEnv,
  meta?: AppMetaStore,
): Promise<import("./xpartners-client.js").XPartnersSessionStatus> {
  const client = getXPartnersClient(env);
  if (!client) {
    return {
      connected: false,
      source: "none",
      hasStoredCookie: false,
      hasStoredCredentials: false,
      hasEnvCookie: false,
      hasEnvCredentials: false,
      message: "1xPartners выключен (XPARTNERS_ENABLED=false).",
    };
  }
  return client.describeSessionStatus(meta);
}

export async function saveXPartnersCredentials(
  meta: AppMetaStore,
  login: string,
  password: string,
): Promise<void> {
  await meta.set(XPARTNERS_LOGIN_META_KEY, login.trim());
  await meta.set(XPARTNERS_PASSWORD_META_KEY, password);
}

export async function clearXPartnersStoredAuth(meta: AppMetaStore): Promise<void> {
  await meta.set(XPARTNERS_SESSION_META_KEY, "");
  await meta.set(XPARTNERS_LOGIN_META_KEY, "");
  await meta.set(XPARTNERS_PASSWORD_META_KEY, "");
}

export function maskXPartnersLogin(login?: string): string {
  const value = (login || "").trim();
  if (!value) {
    return "не задан";
  }
  if (value.includes("@")) {
    const [name, domain] = value.split("@");
    if (!domain) {
      return value;
    }
    if (name.length <= 2) {
      return `${name[0] ?? "*"}*@${domain}`;
    }
    return `${name.slice(0, 2)}***@${domain}`;
  }
  if (value.length <= 3) {
    return `${value[0] ?? "*"}**`;
  }
  return `${value.slice(0, 3)}***`;
}

export function warmupXPartnersSession(env: AppEnv): void {
  const client = getXPartnersClient(env);
  if (!client) {
    return;
  }
  if (!shouldFetchStatsFromApi(env)) {
    console.log(`1xPartners: ${env.XPARTNERS_STATS_SOURCE} stats — cookie not required for display`);
    return;
  }
  const envCookie = cookiesFromEnv(env);
  if (envCookie) {
    const curlMode = Boolean(curlHeadersFromEnv(env));
    console.log(
      `1xPartners: XPARTNERS_COOKIE loaded (len=${envCookie.length}, accessToken=ok, refreshToken=${/refreshToken=/i.test(envCookie) ? "ok" : "MISSING"}, curl=${curlMode ? "yes" : "no"}, stats=${env.XPARTNERS_STATS_SOURCE})`,
    );
  } else {
    console.warn("1xPartners: XPARTNERS_COOKIE missing or invalid (need accessToken= in variable)");
  }
  void client
    .ensureSession()
    .then(() => console.log("1xPartners: session warmup OK"))
    .catch((error) => {
      console.warn("1xPartners: session warmup failed:", formatError(error));
    });
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
