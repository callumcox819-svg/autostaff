import makeFetchCookie from "fetch-cookie";
import { CookieJar } from "tough-cookie";

type ClerkClientContext = {
  fetchWithCookies: typeof fetch;
  jar: CookieJar;
};

type ClerkClientPayload = {
  response?: {
    sessions?: Array<{
      status?: string;
      last_active_token?: {
        jwt?: string;
      };
      last_active_organization_id?: string | null;
      active_organization_id?: string | null;
      user?: {
        id?: string;
        organization_memberships?: Array<{
          organization?: { id?: string };
        }>;
        public_metadata?: { orgId?: string; organizationId?: string };
        publicMetadata?: { orgId?: string; organizationId?: string };
      };
    }>;
    last_active_organization_id?: string | null;
    active_organization_id?: string | null;
  };
};

type ClerkSignInResponse = {
  response?: {
    id?: string;
    status?: string;
    created_session_id?: string | null;
    supported_first_factors?: Array<{
      strategy?: string;
    }>;
  };
  client?: {
    last_active_session_id?: string | null;
  };
  errors?: Array<{
    message?: string;
    long_message?: string;
    code?: string;
  }>;
};

export type ClerkLoginResult = {
  cookieHeader: string;
  organizationId?: string;
  pagerUserId?: string;
};

export class ClerkPasswordAuthClient {
  private readonly queryString =
    "__clerk_api_version=2024-10-01&_clerk_js_version=5.68.0";
  private readonly pagerBaseUrl = "https://www.pager.co.ua";
  private readonly userAgent =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

  constructor(
    private readonly options: {
      frontendApi: string;
    },
  ) {}

  async signInWithPassword(email: string, password: string): Promise<ClerkLoginResult> {
    const client = await this.createClient();

    const signInAttempt = await this.createSignInAttempt(client, email);
    if (signInAttempt.response?.status !== "needs_first_factor") {
      const error =
        signInAttempt.errors?.[0]?.long_message ??
        signInAttempt.errors?.[0]?.message;
      throw new Error(error ?? "Clerk did not enter password sign-in stage.");
    }

    const supportsPassword = signInAttempt.response?.supported_first_factors?.some(
      (factor) => factor.strategy === "password",
    );
    if (!supportsPassword) {
      throw new Error("This account does not offer password sign-in.");
    }

    const attempt = await this.attemptPasswordFactor(
      client,
      signInAttempt.response.id ?? "",
      password,
    );
    const error = attempt.errors?.[0]?.long_message ?? attempt.errors?.[0]?.message;
    if (error) {
      throw new Error(error);
    }

    const clerkClient = await this.fetchClientState(client);
    let sessionInfo = extractClerkSessionInfo(clerkClient);
    const jwt = this.extractSessionJwt(clerkClient);
    if (!jwt) {
      throw new Error("Clerk session JWT was not found after login.");
    }

    for (const path of ["/chats", "/uk/chats"]) {
      await client.fetchWithCookies(`${this.pagerBaseUrl}${path}`, {
        method: "GET",
        headers: this.baseHeaders(),
        redirect: "follow",
      });
    }

    const jarCookies = await jarToCookieDict(client.jar, [
      this.pagerBaseUrl,
      `https://${this.options.frontendApi}`,
    ]);
    const cookies = mergeClerkSessionCookies(jarCookies, clerkClient, jwt);
    if (sessionInfo.organizationId) {
      cookies._pager_org_id = sessionInfo.organizationId;
    }
    if (sessionInfo.pagerUserId) {
      cookies._pager_user_id = sessionInfo.pagerUserId;
    }

    return {
      cookieHeader: cookiesToHeader(cookies),
      organizationId: sessionInfo.organizationId,
      pagerUserId: sessionInfo.pagerUserId,
    };
  }

  private async createClient(): Promise<ClerkClientContext> {
    const headers = this.baseHeaders();
    const jar = new CookieJar();
    const fetchWithCookies = makeFetchCookie(fetch, jar);

    await fetchWithCookies(`${this.pagerBaseUrl}/sign-in`, {
      method: "GET",
      headers,
    });

    await fetchWithCookies(`https://${this.options.frontendApi}/v1/client?${this.queryString}`, {
      method: "POST",
      headers: {
        ...headers,
        "content-type": "application/json",
      },
      body: JSON.stringify({}),
    });

    return { fetchWithCookies, jar };
  }

  private async createSignInAttempt(
    client: ClerkClientContext,
    email: string,
  ): Promise<ClerkSignInResponse> {
    const response = await client.fetchWithCookies(
      `https://${this.options.frontendApi}/v1/client/sign_ins?${this.queryString}`,
      {
        method: "POST",
        headers: this.buildHeaders(),
        body: new URLSearchParams({
          identifier: email,
        }),
      },
    );

    return (await response.json()) as ClerkSignInResponse;
  }

  private async attemptPasswordFactor(
    client: ClerkClientContext,
    signInId: string,
    password: string,
  ): Promise<ClerkSignInResponse> {
    const response = await client.fetchWithCookies(
      `https://${this.options.frontendApi}/v1/client/sign_ins/${signInId}/attempt_first_factor?${this.queryString}`,
      {
        method: "POST",
        headers: this.buildHeaders(),
        body: new URLSearchParams({
          strategy: "password",
          password,
        }),
      },
    );

    return (await response.json()) as ClerkSignInResponse;
  }

  private async fetchClientState(client: ClerkClientContext): Promise<ClerkClientPayload> {
    const response = await client.fetchWithCookies(
      `https://${this.options.frontendApi}/v1/client?${this.queryString}`,
      {
        method: "GET",
        headers: this.buildHeaders(),
      },
    );

    return (await response.json()) as ClerkClientPayload;
  }

  private buildHeaders(): Record<string, string> {
    return {
      ...this.baseHeaders(),
      "content-type": "application/x-www-form-urlencoded",
    };
  }

  private extractSessionJwt(payload: ClerkClientPayload): string {
    const sessions = payload.response?.sessions ?? [];
    for (const session of sessions) {
      const status = String(session.status ?? "").toLowerCase();
      if (status && status !== "active" && status !== "pending") {
        continue;
      }
      const jwt = session.last_active_token?.jwt?.trim();
      if (jwt) {
        return jwt;
      }
    }
    return "";
  }

  private baseHeaders(): Record<string, string> {
    return {
      "user-agent": this.userAgent,
      origin: this.pagerBaseUrl,
      referer: `${this.pagerBaseUrl}/sign-in`,
    };
  }
}

export function extractPagerBearerToken(cookieHeader: string): string | undefined {
  const cookies = parseCookieHeader(cleanPagerCookies(cookieHeader));
  const direct = cookies.__session?.trim();
  if (direct && looksLikeJwt(direct)) {
    return direct;
  }
  for (const [key, value] of Object.entries(cookies)) {
    if (!key.startsWith("__session_") || !value?.trim()) {
      continue;
    }
    const token = value.trim();
    if (looksLikeJwt(token)) {
      return token;
    }
  }
  return undefined;
}

function looksLikeJwt(token: string): boolean {
  return token.split(".").length === 3 && token.length > 20;
}

export function parseCookieHeader(raw: string): Record<string, string> {
  const trimmed = raw.trim();
  if (!trimmed) {
    return {};
  }

  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      return Object.fromEntries(
        Object.entries(parsed).map(([key, value]) => [key, String(value)]),
      );
    } catch {
      return {};
    }
  }

  const cookies: Record<string, string> = {};
  for (const part of trimmed.split(";")) {
    const piece = part.trim();
    if (!piece.includes("=")) {
      continue;
    }
    const [key, ...rest] = piece.split("=");
    cookies[key.trim()] = rest.join("=").trim();
  }
  return cookies;
}

export function cookiesToHeader(cookies: Record<string, string>): string {
  return Object.entries(cookies)
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}=${value}`)
    .join("; ");
}

const PAGER_COOKIE_KEEP = new Set(["_pager_org_id", "_pager_user_id"]);

export function cleanPagerCookies(cookieHeader: string): string {
  const cookies = parseCookieHeader(cookieHeader);
  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(cookies)) {
    if (key.startsWith("_pager_") && !PAGER_COOKIE_KEEP.has(key)) {
      continue;
    }
    if (value) {
      cleaned[key] = value;
    }
  }
  return cookiesToHeader(cleaned);
}

export function enrichPagerCookies(
  cookieHeader: string,
  session: {
    organizationId?: string;
    organizationSlug?: string;
    pagerUserId?: string;
  },
): string {
  const cookies = parseCookieHeader(cleanPagerCookies(cookieHeader));
  const orgId = session.organizationId?.trim();
  if (orgId?.startsWith("org_")) {
    cookies._pager_org_id = orgId;
  }
  const userId = session.pagerUserId?.trim();
  if (userId?.startsWith("user_")) {
    cookies._pager_user_id = userId;
  }
  return cleanPagerCookies(cookiesToHeader(cookies));
}

function extractClerkSessionInfo(payload: ClerkClientPayload): {
  organizationId?: string;
  pagerUserId?: string;
} {
  const client = payload.response;
  if (!client) {
    return {};
  }

  let organizationId =
    client.last_active_organization_id ||
    client.active_organization_id ||
    undefined;

  const sessions = client.sessions ?? [];
  const session = sessions[0];
  const user = session?.user;
  const pagerUserId = user?.id;

  for (const membership of user?.organization_memberships ?? []) {
    const orgId = membership.organization?.id;
    if (orgId) {
      organizationId = orgId;
      break;
    }
  }

  if (!organizationId) {
    const metadata = user?.public_metadata ?? user?.publicMetadata ?? {};
    organizationId = metadata.orgId || metadata.organizationId;
  }

  if (!organizationId && session) {
    organizationId =
      session.last_active_organization_id ||
      session.active_organization_id ||
      undefined;
  }

  return {
    organizationId: organizationId || undefined,
    pagerUserId: pagerUserId || undefined,
  };
}

function mergeClerkSessionCookies(
  jarCookies: Record<string, string>,
  clerkPayload: ClerkClientPayload,
  jwt: string,
): Record<string, string> {
  const merged = { ...jarCookies };
  merged.__session = jwt;

  const clientUat = Math.floor(Date.now() / 1000);
  merged.__client_uat = String(clientUat);

  let suffix = "";
  for (const key of Object.keys(merged)) {
    if (key.startsWith("__client_uat_")) {
      suffix = key.slice("__client_uat_".length);
      break;
    }
  }
  if (suffix) {
    merged[`__session_${suffix}`] = jwt;
  }

  const info = extractClerkSessionInfo(clerkPayload);
  if (info.organizationId) {
    merged._pager_org_id = info.organizationId;
  }
  if (info.pagerUserId) {
    merged._pager_user_id = info.pagerUserId;
  }

  return merged;
}

async function jarToCookieDict(jar: CookieJar, urls: string[]): Promise<Record<string, string>> {
  const merged: Record<string, string> = {};
  for (const url of urls) {
    const cookies = await jar.getCookies(url);
    for (const cookie of cookies) {
      merged[cookie.key] = cookie.value;
    }
  }
  return merged;
}
