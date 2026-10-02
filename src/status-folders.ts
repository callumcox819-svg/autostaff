import type { PagerConversation } from "./pager-client.js";

export const NO_STATUS_FOLDER_ID = "";
export const ALL_INBOX_FOLDER_ID = "*";

export type StatusFolderState = {
  id: string;
  name: string;
  /** Bot scripts / funnel processing. */
  enabled: boolean;
  /** AI agent replies. When unset, follows `enabled`. */
  aiEnabled?: boolean;
};

export function isNoStatusConversation(conv: PagerConversation): boolean {
  if (!conv.statusId) {
    return true;
  }
  const name = (conv.status?.name || "").trim().toLowerCase();
  return name.includes("без статус") || name === "" || name === "—" || name === "-";
}

export function conversationFolderKey(conv: PagerConversation): string {
  if (isNoStatusConversation(conv)) {
    return NO_STATUS_FOLDER_ID;
  }
  return conv.statusId || "";
}

export function normalizeEnabledFolders(enabled: Set<string>): {
  specific: Set<string>;
  allInbox: boolean;
} {
  const specific = new Set([...enabled].filter((id) => id !== ALL_INBOX_FOLDER_ID));
  const allInbox = enabled.has(ALL_INBOX_FOLDER_ID);
  if (specific.size > 0) {
    return { specific, allInbox: false };
  }
  return { specific, allInbox };
}

export function conversationAllowedInFolders(
  conv: PagerConversation,
  enabled: Set<string>,
): boolean {
  if (!enabled.size) {
    return false;
  }

  const { specific, allInbox } = normalizeEnabledFolders(enabled);
  if (allInbox) {
    return true;
  }
  if (!specific.size) {
    return false;
  }

  return specific.has(conversationFolderKey(conv));
}

export function hasEnabledStatusFolders(state: {
  statusFolders?: StatusFolderState[];
  operatorSettings?: { statusFolders?: StatusFolderState[] };
}): boolean {
  const folders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  return folders?.some((folder) => folder.enabled) ?? false;
}

export function getEnabledFolderIds(state: {
  statusFolders?: StatusFolderState[];
  operatorSettings?: { statusFolders?: StatusFolderState[] };
}): Set<string> | null {
  const folders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  if (!folders?.length) {
    return null;
  }

  return new Set(folders.filter((folder) => folder.enabled).map((folder) => folder.id));
}

export function isAiFolderEnabled(folder: StatusFolderState): boolean {
  return folder.aiEnabled ?? folder.enabled;
}

export function getAiEnabledFolderIds(state: {
  statusFolders?: StatusFolderState[];
  operatorSettings?: { statusFolders?: StatusFolderState[] };
}): Set<string> | null {
  const folders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  if (!folders?.length) {
    return null;
  }

  return new Set(folders.filter((folder) => isAiFolderEnabled(folder)).map((folder) => folder.id));
}

export function isConversationInAiEnabledFolders(
  conv: PagerConversation,
  state: {
    statusFolders?: StatusFolderState[];
    operatorSettings?: { statusFolders?: StatusFolderState[] };
  },
): boolean {
  const enabled = getAiEnabledFolderIds(state);
  if (!enabled || enabled.size === 0) {
    return false;
  }
  return conversationAllowedInFolders(conv, enabled);
}

export function isInProgressStatusConversation(conv: PagerConversation): boolean {
  const name = (conv.status?.name || "").trim().toLowerCase();
  return isFunnelFollowUpFolderName(name);
}

/** Status folders the bot moves chats into mid-funnel — must still receive follow-up replies. */
export function isClosedRegistrationStatusConversation(conv: PagerConversation): boolean {
  const name = (conv.status?.name || "").trim().toLowerCase();
  if (!name) {
    return false;
  }
  if (isIgnoreStatusName(name)) {
    return true;
  }
  return /скасован|cancel|cancelled|canceled|заверш|complete|completed|registered|^win$|deposit|выигр/i.test(
    name,
  );
}

/** Follow-up only when operator explicitly enabled the «в процессе» status folder (not via «Всі»). */
export function isInProgressFollowUpFolderEnabled(
  conv: PagerConversation,
  folders: StatusFolderState[] | undefined,
): boolean {
  if (!isInProgressStatusConversation(conv)) {
    return false;
  }
  const statusId = (conv.statusId || "").trim();
  const statusName = (conv.status?.name || "").trim().toLowerCase();
  if (!statusId && !statusName) {
    return false;
  }

  for (const folder of folders ?? []) {
    if (!folder.enabled) {
      continue;
    }
    if (folder.id === ALL_INBOX_FOLDER_ID || folder.id === NO_STATUS_FOLDER_ID) {
      continue;
    }
    const folderName = folder.name.trim().toLowerCase();
    const matchesStatus =
      (statusId && folder.id === statusId) ||
      (statusName && folderName === statusName) ||
      (statusName && isFunnelFollowUpFolderName(folder.name) && isFunnelFollowUpFolderName(statusName));
    if (!matchesStatus) {
      continue;
    }
    return isFunnelFollowUpFolderName(folder.name) || isFunnelFollowUpFolderName(statusName);
  }
  return false;
}

export function isFunnelFollowUpFolderName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  return (
    isZmInProgressRegistrationStatusName(normalized) ||
    isZmRegistrationCompleteStatusName(normalized) ||
    /в процес|у процес|процес|process|рега|реєстраці|чекаю id|не заверш|en cours|in progress/i.test(
      normalized,
    )
  );
}

export function isZmInProgressRegistrationStatusName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  // UA: «В процесі реєстрації» · RU: «В процессе регистрации» · EN
  return (
    /в\s*процес[сеіi]*.{0,8}ре(єстр|гистр|еєстр|г[іиi]стр)/i.test(normalized) ||
    /у\s*процес[сеіi]*.{0,8}ре(єстр|гистр)/i.test(normalized) ||
    /процес[сеіi]*.{0,8}ре(єстр|гистр)/i.test(normalized) ||
    /in\s*registration\s*process|registration\s*process|en\s*cours.*inscri/i.test(normalized)
  );
}

export function isZmRegistrationCompleteStatusName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  if (isZmInProgressRegistrationStatusName(normalized)) {
    return false;
  }
  if (/^реєстрація$|^registration$/i.test(normalized)) {
    return true;
  }
  return normalized.includes("реєстраці") && !normalized.includes("процес");
}

export function isConversationInOperatorEnabledFolders(
  conv: PagerConversation,
  state: {
    statusFolders?: StatusFolderState[];
    operatorSettings?: { statusFolders?: StatusFolderState[] };
  },
): boolean {
  const folders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  // Folders configured but none enabled → process nothing (never fall back to all inbox).
  if (folders?.length) {
    const enabled = getEnabledFolderIds(state);
    if (!enabled || enabled.size === 0) {
      return false;
    }
    return conversationAllowedInFolders(conv, enabled);
  }
  // No folder menu yet — do not process until the operator picks folders.
  return false;
}

/** «Завершено» / completed — эталонные чаты с депозитом для RW-обучения. */
export function isRwCompletedStatusName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  return /заверш|complete|completed|finished|done|deposit.*ok|усп/i.test(normalized);
}

export function isRwCompletedConversation(conv: PagerConversation): boolean {
  const name = (conv.status?.name || "").trim();
  return name.length > 0 && isRwCompletedStatusName(name);
}

export function isIgnoreStatusName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  return /^игнор$|^ignore$|игнорир|не\s*серьез|not\s*serious|troll|spam/i.test(normalized);
}

export function isIgnoreStatusConversation(conv: PagerConversation): boolean {
  const name = (conv.status?.name || "").trim();
  return name.length > 0 && isIgnoreStatusName(name);
}

export function findIgnoreStatusId(state: {
  statusFolders?: StatusFolderState[];
  operatorSettings?: { statusFolders?: StatusFolderState[] };
}): string | undefined {
  for (const folder of state.operatorSettings?.statusFolders ?? state.statusFolders ?? []) {
    if (!folder.id || folder.id === NO_STATUS_FOLDER_ID || folder.id === ALL_INBOX_FOLDER_ID) {
      continue;
    }
    if (isIgnoreStatusName(folder.name)) {
      return folder.id;
    }
  }
  return undefined;
}

export function findCompletedFolderIds(folders: StatusFolderState[]): string[] {
  return folders
    .filter(
      (folder) =>
        folder.id &&
        folder.id !== NO_STATUS_FOLDER_ID &&
        folder.id !== ALL_INBOX_FOLDER_ID &&
        isRwCompletedStatusName(folder.name),
    )
    .map((folder) => folder.id);
}

/** RW: всегда смотрим «Завершено» + папки, включённые оператором в боте. */
export function expandRwLearnFolderIds(
  enabledFolderIds: Set<string> | null,
  statusFolders: StatusFolderState[] | undefined,
): Set<string> | null {
  const completedIds = findCompletedFolderIds(statusFolders ?? []);
  if (!completedIds.length && (!enabledFolderIds || enabledFolderIds.size === 0)) {
    return enabledFolderIds;
  }
  const merged = new Set(enabledFolderIds ?? []);
  for (const id of completedIds) {
    merged.add(id);
  }
  return merged;
}

/** Operator folders are strict — never auto-add «в процессе» / mid-funnel folders. */
export function expandEnabledFolderIds(
  _state: { statusFolders?: StatusFolderState[] },
  enabledFolderIds: Set<string> | null,
): Set<string> | null {
  return enabledFolderIds;
}

export function countApiStatusFolders(folders?: StatusFolderState[]): number {
  return folders?.filter((folder) => folder.id !== "" && folder.id !== "*").length ?? 0;
}

export function stripChannelNamesFromFolders(
  folders: StatusFolderState[],
  liveChannels?: Array<{ id: string; name: string }>,
): StatusFolderState[] {
  const channelIds = new Set(
    (liveChannels ?? []).map((channel) => channel.id).filter(Boolean),
  );
  const channelNames = new Set(
    (liveChannels ?? [])
      .map((channel) => channel.name.trim().toLowerCase())
      .filter(Boolean),
  );

  return folders.filter((folder) => {
    if (folder.id === NO_STATUS_FOLDER_ID || folder.id === ALL_INBOX_FOLDER_ID) {
      return true;
    }
    if (channelIds.has(folder.id)) {
      return false;
    }
    const name = folder.name.trim().toLowerCase();
    if (channelNames.has(name)) {
      return false;
    }
    // Pager sometimes leaks messenger/page channels into the status list.
    if (looksLikeLeakedChannelFolder(folder.name)) {
      return false;
    }
    return true;
  });
}

/** Heuristic: person-name / page-style channel labels that are not real status folders. */
export function looksLikeLeakedChannelFolder(name: string): boolean {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 60) {
    return false;
  }
  const lower = trimmed.toLowerCase();
  if (isKnownChatStatusFolderName(lower)) {
    return false;
  }
  // "Brice Moukoko", "Mahmoud Fathy" — messenger page / agent names.
  if (/^[A-ZÀ-ÖØ-Þ][\p{L}'’.-]*(?:\s+[A-ZÀ-ÖØ-Þ][\p{L}'’.-]*){1,3}$/u.test(trimmed)) {
    return true;
  }
  // "ZenHaven", "EcoRiors" — single-word CamelCase channel/page brands.
  if (/^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$/.test(trimmed)) {
    return true;
  }
  return false;
}

function isKnownChatStatusFolderName(lower: string): boolean {
  return /без статус|всі|все|в процес|процес|реєстрац|регистрац|заверш|чекаю|waiting|interested|complete|completed|deposit|en cours|registration|registered|process|^win$|игнор|ignore/i.test(
    lower,
  );
}

export function buildStatusFoldersFromPager(
  apiStatuses: Array<{ id: string; name: string }>,
  existing?: StatusFolderState[],
  liveChannels?: Array<{ id: string; name: string }>,
): StatusFolderState[] {
  return stripChannelNamesFromFolders(mergeStatusFolderList(apiStatuses, existing), liveChannels);
}

export function mergeStatusFolderList(
  apiStatuses: Array<{ id: string; name: string }>,
  existing?: StatusFolderState[],
): StatusFolderState[] {
  const hasSavedApiFolders = existing?.some(
    (folder) => folder.id !== NO_STATUS_FOLDER_ID && folder.id !== ALL_INBOX_FOLDER_ID,
  );
  if (!apiStatuses.length && hasSavedApiFolders) {
    return existing!;
  }
  return buildStatusFolderList(apiStatuses, existing);
}

export function buildStatusFolderList(
  apiStatuses: Array<{ id: string; name: string }>,
  existing?: StatusFolderState[],
): StatusFolderState[] {
  const preserved = new Map(
    (existing ?? []).map((folder) => [folder.id, { enabled: folder.enabled, aiEnabled: folder.aiEnabled }]),
  );
  const hasExisting = Boolean(existing?.length);

  const folders: StatusFolderState[] = [
    {
      id: NO_STATUS_FOLDER_ID,
      name: "Без статусу",
      enabled: preserved.get(NO_STATUS_FOLDER_ID)?.enabled ?? false,
      aiEnabled: preserved.get(NO_STATUS_FOLDER_ID)?.aiEnabled,
    },
    {
      id: ALL_INBOX_FOLDER_ID,
      name: "Всі",
      enabled: preserved.get(ALL_INBOX_FOLDER_ID)?.enabled ?? !hasExisting,
      aiEnabled: preserved.get(ALL_INBOX_FOLDER_ID)?.aiEnabled,
    },
  ];

  for (const status of apiStatuses) {
    const saved = preserved.get(status.id);
    folders.push({
      id: status.id,
      name: status.name,
      enabled: saved?.enabled ?? false,
      aiEnabled: saved?.aiEnabled,
    });
  }

  return folders;
}

export function setAllStatusFolders(
  folders: StatusFolderState[],
  enabled: boolean,
): StatusFolderState[] {
  return folders.map((folder) => ({ ...folder, enabled }));
}

export function toggleStatusFolder(
  folders: StatusFolderState[],
  index: number,
): StatusFolderState[] {
  const next = [...folders];
  const folder = next[index];
  if (!folder) {
    return folders;
  }
  next[index] = { ...folder, enabled: !folder.enabled };
  return next;
}

export function toggleAiStatusFolder(
  folders: StatusFolderState[],
  index: number,
): StatusFolderState[] {
  const next = [...folders];
  const folder = next[index];
  if (!folder) {
    return folders;
  }
  const current = isAiFolderEnabled(folder);
  next[index] = { ...folder, aiEnabled: !current };
  return next;
}

export function setAllAiStatusFolders(
  folders: StatusFolderState[],
  aiEnabled: boolean,
): StatusFolderState[] {
  return folders.map((folder) => ({ ...folder, aiEnabled }));
}
