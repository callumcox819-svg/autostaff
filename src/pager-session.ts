import { ClerkPasswordAuthClient, enrichPagerCookies } from "./clerk-auth.js";
import { isPagerSessionError, PagerClient } from "./pager-client.js";
import type { AppEnv } from "./env.js";
import type { ChatState, StateStore } from "./state-store.js";

export type PagerSessionResult = {
  state: ChatState;
  client: PagerClient;
};

export function resolvePagerOrgSlug(state: ChatState): string | undefined {
  return (
    state.pagerAccount?.organizationSlug ??
    state.pagerAccount?.organizationName?.toLowerCase()
  );
}

export function buildPagerAccountPatch(
  state: ChatState,
  session: {
    organizationId?: string;
    organizationSlug?: string;
    organizationName?: string;
    cookieHeader: string;
    pagerUserId?: string;
  },
): NonNullable<ChatState["pagerAccount"]> {
  const base =
    state.pagerAccount ?? { authMode: "cookies", connectedAt: new Date().toISOString() };
  return {
    ...base,
    cookies: enrichPagerCookies(session.cookieHeader, {
      organizationId: session.organizationId ?? base.organizationId,
      pagerUserId: session.pagerUserId ?? base.pagerUserId,
    }),
    organizationId: session.organizationId ?? base.organizationId,
    organizationSlug: session.organizationSlug ?? base.organizationSlug,
    organizationName: session.organizationName ?? base.organizationName,
    pagerUserId: session.pagerUserId ?? base.pagerUserId,
  };
}

function buildPagerClient(state: ChatState, env: AppEnv, cookieHeader: string, orgId?: string) {
  return new PagerClient({
    baseUrl: env.PAGER_BASE_URL,
    webBaseUrl: env.PAGER_WEB_URL,
    cookieHeader: enrichPagerCookies(cookieHeader, {
      organizationId: orgId ?? state.pagerAccount?.organizationId,
      pagerUserId: state.pagerAccount?.pagerUserId,
    }),
    orgId: orgId ?? state.pagerAccount?.organizationId,
    orgSlug: resolvePagerOrgSlug(state),
    locale: "uk",
    sessionUserId: state.pagerAccount?.pagerUserId,
  });
}

async function finalizeSession(
  deps: { env: AppEnv; stateStore: StateStore },
  state: ChatState,
  client: PagerClient,
  pagerUserId?: string,
): Promise<PagerSessionResult> {
  await client.verifyApiSession();
  const bootstrap = await client.bootstrapSession();
  const probedUserId = (await client.probeOperatorUserId()) || pagerUserId;
  const patched = await deps.stateStore.patch(state.chatId, {
    pagerAccount: buildPagerAccountPatch(state, {
      ...bootstrap,
      cookieHeader: client.getCookieHeader(),
      pagerUserId: probedUserId,
    }),
  });
  return { state: patched ?? state, client };
}

export async function ensurePagerSession(
  deps: { env: AppEnv; stateStore: StateStore },
  state: ChatState,
): Promise<PagerSessionResult | null> {
  const account = state.pagerAccount;
  const storedCookies = account?.cookies?.trim();
  const hasCredentials = Boolean(account?.email && account?.password);

  if (!storedCookies && !hasCredentials) {
    return null;
  }

  if (storedCookies) {
    const client = buildPagerClient(state, deps.env, storedCookies);
    try {
      return await finalizeSession(deps, state, client);
    } catch (error) {
      if (!hasCredentials) {
        console.error(
          `Pager session invalid for chat ${state.chatId} and no stored credentials:`,
          formatError(error),
        );
        return null;
      }
      console.warn(
        `Pager cookie session invalid for chat ${state.chatId}, re-login with stored password:`,
        formatError(error),
      );
    }
  }

  if (hasCredentials) {
    return refreshPagerSessionWithCredentials(deps, state);
  }

  return null;
}

export async function refreshPagerSessionWithCredentials(
  deps: { env: AppEnv; stateStore: StateStore },
  state: ChatState,
): Promise<PagerSessionResult | null> {
  const account = state.pagerAccount;
  if (!account?.email || !account.password) {
    return null;
  }

  const login = await new ClerkPasswordAuthClient({ frontendApi: "clerk.pager.co.ua" }).signInWithPassword(
    account.email,
    account.password,
  );

  const client = buildPagerClient(state, deps.env, login.cookieHeader, login.organizationId);

  try {
    const session = await client.validateSession();
    const result = await finalizeSession(deps, state, client, login.pagerUserId);
    const patched = await deps.stateStore.patch(state.chatId, {
      pagerAccount: {
        ...(result.state.pagerAccount ?? account),
        authMode: "credentials",
        email: account.email,
        password: account.password,
        cookies: result.state.pagerAccount?.cookies ?? account.cookies,
        pagerUserId: result.state.pagerAccount?.pagerUserId ?? login.pagerUserId,
        organizationId:
          result.state.pagerAccount?.organizationId ??
          session.organizationId ??
          login.organizationId,
        organizationName: result.state.pagerAccount?.organizationName ?? session.organizationName,
        organizationSlug: result.state.pagerAccount?.organizationSlug ?? session.organizationSlug,
        liveChannels: session.channels.map((channel) => ({
          id: channel.id,
          name: channel.name,
          channelSource: channel.channelSource,
        })),
        liveTemplateBanks: session.templateBanks.map((bank) => ({
          id: bank.id,
          name: bank.name,
          replyCount: bank.replyCount,
        })),
      },
    });
    console.log(
      `Pager session auto-refreshed for chat ${state.chatId} operator=${result.state.pagerAccount?.pagerUserId?.slice(0, 16) ?? "?"}`,
    );
    return { state: patched ?? result.state, client: result.client };
  } catch (error) {
    console.error(`Pager credential refresh failed for chat ${state.chatId}:`, formatError(error));
    if (isPagerSessionError(error)) {
      return null;
    }
    throw error;
  }
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
