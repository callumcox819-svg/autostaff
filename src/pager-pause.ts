import type { ChatState, StateStore } from "./state-store.js";

export function pagerOrganizationKey(state: ChatState): string | undefined {
  const orgId = state.pagerAccount?.organizationId?.trim();
  if (orgId) {
    return `id:${orgId}`;
  }
  const slug = state.pagerAccount?.organizationSlug?.trim();
  if (slug) {
    return `slug:${slug.toLowerCase()}`;
  }
  return undefined;
}

/** Pause / unpause only this Telegram operator — never mirror across the Pager org. */
export async function applyPagerPause(
  store: StateStore,
  source: ChatState,
  paused: boolean,
): Promise<ChatState[]> {
  const next = await store.patch(source.chatId, { paused });
  return next ? [next] : [];
}

export function describePagerAccount(state: ChatState): string {
  const name =
    state.pagerAccount?.organizationName?.trim() ||
    state.pagerAccount?.organizationSlug?.trim() ||
    state.pagerAccount?.email?.trim() ||
    "Pager";
  return `${name} (chat ${state.chatId})`;
}
