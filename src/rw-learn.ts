import type { PagerConversation, PagerMessage } from "./pager-client.js";
import { isCustomerMessage as pagerIsCustomerMessage } from "./pager-client.js";
import { isOperatorOutgoingMessage } from "./conversation-reply.js";
import {
  mergeRwScriptDraftsFromOperatorText,
  type RwScriptDraft,
  type RwScriptDrafts,
} from "./rw-script-engine.js";
import {
  isInProgressStatusConversation,
  isNoStatusConversation,
  isRwCompletedConversation,
} from "./status-folders.js";

/** Каналы с первого скрина — наблюдение до полноценных шаблонов RW. */
export const RW_LEARN_CHANNEL_HINTS = [
  "remorseful respectful",
  "ekambi aboubakar",
  "patrick uwimana",
] as const;

export type WorkerCountry = "ZM" | "CM" | "EG" | "RW" | "CL" | "MG" | "DJ" | "JO";

export type RwLearningEventKind =
  | "no_status_lead"
  | "status_changed"
  | "customer_message"
  | "operator_message"
  | "completed_harvest"
  | "transcript_customer"
  | "transcript_operator";

export type RwLearningEvent = {
  at: string;
  channelId: string;
  channelName: string;
  conversationId: string;
  kind: RwLearningEventKind;
  statusName?: string;
  previousStatusName?: string;
  textPreview?: string;
};

export type RwLearningWatchEntry = {
  channelId: string;
  channelName: string;
  statusId?: string;
  statusName?: string;
  lastCustomerMessageId?: string;
  lastOperatorMessageId?: string;
  firstSeenAt: string;
  updatedAt: string;
};

export type { RwScriptDraft, RwScriptDrafts } from "./rw-script-engine.js";

export type RwLearningState = {
  watch: Record<string, RwLearningWatchEntry>;
  events: RwLearningEvent[];
  /** Уже снята полная переписка из «Завершено». */
  harvestedCompleted?: Record<
    string,
    { at: string; channelName: string; turns: number }
  >;
  /** Черновики шаблонов, собранные из операторских сообщений. */
  scriptDrafts?: RwScriptDrafts;
};

const MAX_EVENTS = 800;
const MAX_TRANSCRIPT_TURNS = 80;

export function isRwLearnChannelName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return RW_LEARN_CHANNEL_HINTS.some((hint) => {
    const parts = hint.split(/\s+/).filter(Boolean);
    return parts.every((part) => normalized.includes(part));
  });
}

/** Live Pager channels that run the Chile funnel (local scripts/cl, not CM Pager bank). */
const CL_CHANNEL_HINTS = ["javier soto"];

/** Madagascar funnel — French local scripts/mg. */
const MG_CHANNEL_HINTS = ["madagascar", "madagasikara"];

/** Djibouti funnel — French local scripts/dj. */
const DJ_CHANNEL_HINTS = ["djibouti", "djibout"];

/** Jordan funnel — Arabic local scripts/jo. */
const JO_CHANNEL_HINTS = ["jordan", "الأردن", "الاردن"];

export function isClChannelName(name: string): boolean {
  const normalized = name.toLowerCase();
  if (/\bchile\b|\bchili\b|\bcl\b/.test(normalized)) {
    return true;
  }
  if (normalized.includes("javier") && normalized.includes("soto")) {
    return true;
  }
  return CL_CHANNEL_HINTS.some((hint) => {
    const parts = hint.split(/\s+/).filter(Boolean);
    return parts.every((part) => normalized.includes(part));
  });
}

export function isMgChannelName(name: string): boolean {
  const normalized = name.toLowerCase();
  if (/\bmadagascar\b|\bmadagasikara\b|\bmdg\b|\bmga\b/.test(normalized)) {
    return true;
  }
  return MG_CHANNEL_HINTS.some((hint) => normalized.includes(hint));
}

export function isDjChannelName(name: string): boolean {
  const normalized = name.toLowerCase();
  if (/\bdjibouti\b|\bdjibout\b|\bdjf\b|\bbji\b/.test(normalized)) {
    return true;
  }
  return DJ_CHANNEL_HINTS.some((hint) => normalized.includes(hint));
}

export function isJoChannelName(name: string): boolean {
  const normalized = name.toLowerCase();
  if (/\bjordan\b|\bjod\b|\bjor\b|\bamman\b/.test(normalized)) {
    return true;
  }
  if (/الأردن|الاردن|اردن/.test(name)) {
    return true;
  }
  return JO_CHANNEL_HINTS.some((hint) => normalized.includes(hint) || name.includes(hint));
}

export function resolveWorkerCountryForChannel(
  channelName: string,
  savedCountry?: WorkerCountry,
  yamlCountry?: WorkerCountry,
): WorkerCountry {
  // Operator override always wins (e.g. Tchouameni channel set to MG manually).
  if (savedCountry) {
    return savedCountry;
  }
  if (isClChannelName(channelName)) {
    return "CL";
  }
  if (isMgChannelName(channelName)) {
    return "MG";
  }
  if (isDjChannelName(channelName)) {
    return "DJ";
  }
  if (isJoChannelName(channelName)) {
    return "JO";
  }
  return yamlCountry ?? defaultCountryForChannelName(channelName);
}

export function defaultCountryForChannelName(name: string): WorkerCountry {
  if (isRwLearnChannelName(name)) {
    return "RW";
  }
  if (isClChannelName(name)) {
    return "CL";
  }
  if (isMgChannelName(name)) {
    return "MG";
  }
  if (isDjChannelName(name)) {
    return "DJ";
  }
  if (isJoChannelName(name)) {
    return "JO";
  }
  const normalized = name.toLowerCase();
  if (/mahmoud|anas|ahmad|moulaye|egypt|eg/.test(normalized)) {
    return "EG";
  }
  if (/moukoko|ndzi|cameroon|cm|tchouameni/.test(normalized)) {
    return "CM";
  }
  return "ZM";
}

function truncateText(text: string, max = 120): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) {
    return t;
  }
  return `${t.slice(0, max - 1)}…`;
}

function isRwCustomerMessage(
  message: PagerMessage,
  conv: PagerConversation,
  operatorUserId?: string,
): boolean {
  return pagerIsCustomerMessage(message, conv, operatorUserId);
}

function isRwOperatorMessage(
  message: PagerMessage,
  conv: PagerConversation,
  operatorUserId?: string,
): boolean {
  return isOperatorOutgoingMessage(message, conv, operatorUserId, "CM");
}

function applyOperatorDraftFromMessage(
  drafts: RwScriptDrafts | undefined,
  message: PagerMessage,
  convId: string,
  channelName: string,
): RwScriptDrafts {
  const text = (message.text || "").trim();
  if (!text) {
    return drafts ?? {};
  }
  return mergeRwScriptDraftsFromOperatorText(drafts, {
    text,
    source: `${channelName} · ${convId.slice(0, 8)}`,
    at: message.createdAt ?? new Date().toISOString(),
  });
}

export function mergeRwLearningState(
  current: RwLearningState | undefined,
  patch: {
    watch?: Record<string, RwLearningWatchEntry>;
    events?: RwLearningEvent[];
    harvestedCompleted?: Record<string, { at: string; channelName: string; turns: number }>;
    scriptDrafts?: RwScriptDrafts;
  },
): RwLearningState {
  const watch = { ...(current?.watch ?? {}), ...(patch.watch ?? {}) };
  const events = [...(current?.events ?? []), ...(patch.events ?? [])].slice(-MAX_EVENTS);
  const harvestedCompleted = {
    ...(current?.harvestedCompleted ?? {}),
    ...(patch.harvestedCompleted ?? {}),
  };
  const scriptDrafts = patch.scriptDrafts ?? current?.scriptDrafts;
  return { watch, events, harvestedCompleted, scriptDrafts };
}

export function harvestRwCompletedConversation(input: {
  conv: PagerConversation;
  channelId: string;
  channelName: string;
  messages: PagerMessage[];
  operatorUserId?: string;
  learning?: RwLearningState;
}): { next: RwLearningState; newEvents: RwLearningEvent[] } {
  const { conv, channelId, channelName, messages, operatorUserId, learning } = input;
  const convId = conv.id;
  const now = new Date().toISOString();

  if (learning?.harvestedCompleted?.[convId]) {
    return { next: learning, newEvents: [] };
  }

  const statusName = (conv.status?.name || "Завершено").trim();
  const sorted = [...messages].sort(
    (a, b) => Date.parse(a.createdAt ?? "") - Date.parse(b.createdAt ?? ""),
  );

  const newEvents: RwLearningEvent[] = [
    {
      at: now,
      channelId,
      channelName,
      conversationId: convId,
      kind: "completed_harvest",
      statusName,
      textPreview: `${sorted.length} сообщ. в треде`,
    },
  ];

  let turns = 0;
  let scriptDrafts = learning?.scriptDrafts;
  for (const message of sorted) {
    if (turns >= MAX_TRANSCRIPT_TURNS) {
      break;
    }
    const text = (message.text || "").trim();
    if (!text) {
      continue;
    }
    if (isRwCustomerMessage(message, conv, operatorUserId)) {
      newEvents.push({
        at: message.createdAt ?? now,
        channelId,
        channelName,
        conversationId: convId,
        kind: "transcript_customer",
        statusName,
        textPreview: truncateText(text, 240),
      });
      turns += 1;
    } else if (isRwOperatorMessage(message, conv, operatorUserId)) {
      scriptDrafts = applyOperatorDraftFromMessage(scriptDrafts, message, convId, channelName);
      newEvents.push({
        at: message.createdAt ?? now,
        channelId,
        channelName,
        conversationId: convId,
        kind: "transcript_operator",
        statusName,
        textPreview: truncateText(text, 240),
      });
      turns += 1;
    }
  }

  const next = mergeRwLearningState(learning, {
    events: newEvents,
    harvestedCompleted: {
      [convId]: { at: now, channelName, turns },
    },
    scriptDrafts,
  });

  for (const event of newEvents) {
    console.log(
      `RW learn · ${event.channelName} · ${event.conversationId.slice(0, 8)} · ${event.kind}${event.textPreview ? ` · ${event.textPreview}` : ""}`,
    );
  }

  return { next, newEvents };
}

export function observeRwConversation(input: {
  conv: PagerConversation;
  channelId: string;
  channelName: string;
  messages: PagerMessage[];
  operatorUserId?: string;
  learning?: RwLearningState;
}): { next: RwLearningState; newEvents: RwLearningEvent[] } {
  const { conv, channelId, channelName, messages, operatorUserId, learning } = input;
  const convId = conv.id;
  const now = new Date().toISOString();
  const prev = learning?.watch[convId];
  const statusId = conv.statusId ?? "";
  const statusName = (conv.status?.name || (isNoStatusConversation(conv) ? "Без статусу" : "")).trim();

  const sorted = [...messages].sort(
    (a, b) => Date.parse(a.createdAt ?? "") - Date.parse(b.createdAt ?? ""),
  );

  const newEvents: RwLearningEvent[] = [];

  if (!prev && isNoStatusConversation(conv)) {
    newEvents.push({
      at: now,
      channelId,
      channelName,
      conversationId: convId,
      kind: "no_status_lead",
      statusName,
    });
  }

  if (prev && (prev.statusId !== statusId || prev.statusName !== statusName)) {
    newEvents.push({
      at: now,
      channelId,
      channelName,
      conversationId: convId,
      kind: "status_changed",
      previousStatusName: prev.statusName || "—",
      statusName: statusName || "—",
    });
    if (isInProgressStatusConversation(conv)) {
      console.log(
        `RW learn · ${channelName} · ${convId.slice(0, 8)} · funnel: «Без статусу» → «В процессе» (как CM/ZM, свои шаблоны позже)`,
      );
    }
  }

  let lastCustomerMessageId = prev?.lastCustomerMessageId;
  let lastOperatorMessageId = prev?.lastOperatorMessageId;

  let latestCustomer: PagerMessage | undefined;
  let latestOperator: PagerMessage | undefined;
  let scriptDrafts = learning?.scriptDrafts;
  for (const message of sorted) {
    if (isRwCustomerMessage(message, conv, operatorUserId)) {
      latestCustomer = message;
    } else if (isRwOperatorMessage(message, conv, operatorUserId)) {
      latestOperator = message;
    }
  }

  const sawNewLead = newEvents.some((e) => e.kind === "no_status_lead");

  if (latestCustomer?.id) {
    lastCustomerMessageId = latestCustomer.id;
    const isNewCustomerMsg =
      latestCustomer.id !== prev?.lastCustomerMessageId &&
      (prev != null || sawNewLead);
    if (isNewCustomerMsg) {
      newEvents.push({
        at: now,
        channelId,
        channelName,
        conversationId: convId,
        kind: "customer_message",
        statusName,
        textPreview: truncateText(latestCustomer.text || "[media]"),
      });
    }
  }

  if (latestOperator?.id) {
    lastOperatorMessageId = latestOperator.id;
    const isNewOperatorMsg =
      latestOperator.id !== prev?.lastOperatorMessageId &&
      (prev != null || sawNewLead);
    if (isNewOperatorMsg) {
      const opText = (latestOperator.text || "").trim();
      if (opText) {
        scriptDrafts = applyOperatorDraftFromMessage(scriptDrafts, latestOperator, convId, channelName);
      }
      newEvents.push({
        at: now,
        channelId,
        channelName,
        conversationId: convId,
        kind: "operator_message",
        statusName,
        textPreview: truncateText(latestOperator.text || "[media/template]"),
      });
    }
  }

  const watchEntry: RwLearningWatchEntry | undefined =
    isNoStatusConversation(conv) ||
    prev ||
    newEvents.some((e) => e.kind === "status_changed" || e.kind === "customer_message")
      ? {
          channelId,
          channelName,
          statusId,
          statusName,
          lastCustomerMessageId,
          lastOperatorMessageId,
          firstSeenAt: prev?.firstSeenAt ?? now,
          updatedAt: now,
        }
      : undefined;

  const next = mergeRwLearningState(learning, {
    watch: watchEntry ? { [convId]: watchEntry } : undefined,
    events: newEvents,
    scriptDrafts,
  });

  for (const event of newEvents) {
    console.log(
      `RW learn · ${event.channelName} · ${event.conversationId.slice(0, 8)} · ${event.kind}${event.statusName ? ` · ${event.statusName}` : ""}${event.textPreview ? ` · ${event.textPreview}` : ""}`,
    );
  }

  return { next, newEvents };
}

export function formatRwAutoFunnelHelp(): string {
  return [
    "Руанда (RW): авто-воронка включена.",
    "Скан «Завершено» и режим обучения отключены.",
    "",
    "Сценарий:",
    "1) intro после интереса клиента",
    "2) How it works + таблица RWF (два сообщения)",
    "3) регистрация RND555 + https://tinyurl.com/rund555",
    "4) статус «В процессе реєстрації» после ссылки",
    "",
    "Каналы: Remorseful Respectful, Ekambi Aboubakar, Patrick Uwimana.",
    "В боте включите «Без статусу» для новых лидов.",
    "",
    "Пауза без деплоя: RW_FUNNEL_ENABLED=false на Railway.",
  ].join("\n");
}

export function formatRwLearningSummary(_learning?: RwLearningState): string {
  return formatRwAutoFunnelHelp();
}
