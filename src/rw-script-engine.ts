import type { PagerMessage } from "./pager-client.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { registrationResendScriptKeys } from "./funnel-common.js";
import {
  type ZmIntent,
  classifyZmIntent,
  isFunnelPositiveReaction,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isRegistrationHelpRequest,
  isZmRegistrationAccountQuestion,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./zm-intent.js";
import { collectOutgoingTexts as zmCollectOutgoingTexts } from "./zm-script-engine.js";
import { loadLocalRwScript } from "./rw-local-scripts.js";

export const RW_SCRIPT_KEYS = [
  "01_intro",
  "02_how_it_works",
  "03_deposit_table",
  "04_registration",
  "05_link",
] as const;

export type RwScriptKey = (typeof RW_SCRIPT_KEYS)[number];

export type RwScriptDraft = {
  text: string;
  source: string;
  at: string;
  samples: number;
};

export type RwScriptDrafts = Partial<Record<RwScriptKey, RwScriptDraft>>;

export const RW_EXPLAIN_SEND_KEYS = new Set<RwScriptKey>(["02_how_it_works", "03_deposit_table"]);
export const RW_REG_SEND_KEYS = new Set<RwScriptKey>(["04_registration", "05_link"]);

/** Эталонная воронка RW — дублирует scripts/rw/*.txt (fallback). */
export const RW_BUILTIN_SCRIPTS: Record<RwScriptKey, string> = {
  "01_intro":
    "Hi! I want to show you how I work with casino platforms. I use analytical systems and artificial intelligence tools to identify the best moments to enter the game. This is not random gambling. It is a method based on data, statistics, discipline and strategy. The AI analyzes many game sessions and statistics to find better opportunities, while my experience helps to understand how the platform works. For me this is like a business: you enter at the right moment, follow the instructions, and exit at the right time. I only work with serious people who are ready to follow instructions and work responsibly. If you are interested, I can explain step by step how it works and how you can start.",
  "02_how_it_works":
    "How it works:\n1) You create your own account at the casino using my link and enter my promo code.\n2) You make the first deposit up from 1000 RWF\n3) I will send you clear instructions (screenshots and detailed explanations). Everything has been tested by my team - reliability guaranteed! ✅\n4) Your task is to follow the steps exactly, without personal initiative. You will play only the games that we have carefully tested and that bring profit. 💰",
  "03_deposit_table":
    "Here's what you can get with my help:\nThe first amount is your deposit.\nThe second amount is your profit.\n2000 RWF - 10000 RWF\n5000 RWF - 20000 RWF\n10000 RWF - 50000 RWF\n20000 RWF - 100000 RWF\nAre you ready to start today?",
  "04_registration":
    "I will send you a special registration link.\nCopy it and paste it into your Google Chrome browser.\nTap on Registration\nYou can make registration by \"one click\" or e-mail\nWhen registering, select your country and currency.\nUse the promo code RND555\nAfter registration, text me here.\nHere is the link:",
  "05_link": "https://tinyurl.com/rund555",
};

export function rwScriptText(key: RwScriptKey, drafts?: RwScriptDrafts): string {
  const fromDraft = drafts?.[key]?.text?.trim();
  if (fromDraft) {
    return fromDraft;
  }
  const fromLocal = loadLocalRwScript(key);
  if (fromLocal?.trim()) {
    return fromLocal;
  }
  return RW_BUILTIN_SCRIPTS[key]?.trim() ?? "";
}

export function rwActiveScriptDrafts(drafts?: RwScriptDrafts): RwScriptDrafts {
  const merged: RwScriptDrafts = {};
  for (const key of RW_SCRIPT_KEYS) {
    const text = rwScriptText(key, drafts);
    if (text) {
      merged[key] = drafts?.[key] ?? {
        text,
        source: "builtin",
        at: "",
        samples: 0,
      };
    }
  }
  return merged;
}

export const RW_FOLDER_NAME_HINTS = ["ruand", "rwand", "rw", "руанд"];

/** Pager saved-reply names that also map to RW script keys. */
export const RW_SCRIPT_KEY_ALIASES: Record<string, string[]> = {
  "03_deposit_table": ["03_zmw_table"],
};

export function rwScriptSnippet(key: string): string {
  return RW_GENERIC_NEEDLES[key as RwScriptKey]?.[0] ?? "";
}

export function rwScriptSearchNeedles(key: string): string[] {
  return RW_GENERIC_NEEDLES[key as RwScriptKey] ?? [];
}

const RW_GENERIC_NEEDLES: Record<RwScriptKey, string[]> = {
  "01_intro": ["analytical systems", "artificial intelligence", "hi! i want to show you"],
  "02_how_it_works": ["how it works:", "1000 rwf", "your own account", "first deposit up from"],
  "03_deposit_table": [
    "2000 rwf - 10000 rwf",
    "5000 rwf - 20000 rwf",
    "10000 rwf - 50000 rwf",
    "20000 rwf - 100000 rwf",
    "ready to start today",
    "here's what you can get",
  ],
  "04_registration": [
    "special registration link",
    "paste it into your google chrome",
    "here is the link:",
    "rnd555",
  ],
  "05_link": ["tinyurl.com/rund555", "rund555"],
};

const RW_REG_BUNDLE: RwScriptKey[] = ["04_registration", "05_link"];

function needlesForKey(key: RwScriptKey, drafts?: RwScriptDrafts): string[] {
  const fromDraft = drafts?.[key]?.text?.trim();
  const needles: string[] = [];
  if (fromDraft) {
    const lower = fromDraft.toLowerCase();
    needles.push(lower.slice(0, Math.min(80, lower.length)));
    if (lower.length > 40) {
      needles.push(lower.slice(0, 40));
    }
  }
  for (const generic of RW_GENERIC_NEEDLES[key] ?? []) {
    if (!needles.includes(generic)) {
      needles.push(generic);
    }
  }
  return needles.filter(Boolean);
}

function scriptSentInHistory(outgoingTexts: string[], needle: string): boolean {
  const n = needle.trim().toLowerCase();
  if (!n) {
    return false;
  }
  return outgoingTexts.some((text) => {
    const body = text.toLowerCase();
    return body.includes(n) || n.includes(body.slice(0, 80));
  });
}

export function rwScriptSentInHistory(
  outgoingTexts: string[],
  scriptKey: RwScriptKey,
  drafts?: RwScriptDrafts,
): boolean {
  return needlesForKey(scriptKey, drafts).some((needle) =>
    scriptSentInHistory(outgoingTexts, needle),
  );
}

export function rwExplainScriptsSentInHistory(
  outgoingTexts: string[],
  drafts?: RwScriptDrafts,
): boolean {
  return (
    rwScriptSentInHistory(outgoingTexts, "02_how_it_works", drafts) &&
    rwScriptSentInHistory(outgoingTexts, "03_deposit_table", drafts)
  );
}

export function rwRegLinkSentInHistory(outgoingTexts: string[], drafts?: RwScriptDrafts): boolean {
  if (rwScriptSentInHistory(outgoingTexts, "05_link", drafts)) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("tinyurl.com/");
}

export function rwRegistrationInstructionsSentInHistory(
  outgoingTexts: string[],
  drafts?: RwScriptDrafts,
): boolean {
  if (rwScriptSentInHistory(outgoingTexts, "04_registration", drafts)) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  // «How it works» mentions promo code — do not treat that as the reg bundle.
  return (
    (blob.includes("special registration link") ||
      blob.includes("paste it into your google chrome") ||
      blob.includes("one click") ||
      blob.includes("here is the link:")) &&
    blob.includes("rnd555")
  );
}

export function collectRwOutgoingTexts(messages: PagerMessage[]): string[] {
  return zmCollectOutgoingTexts(messages);
}

export function rwFunnelStepFromScriptGaps(
  outgoingTexts: string[],
  baseStep: number,
  drafts?: RwScriptDrafts,
): number {
  let step = baseStep;
  if (!rwScriptSentInHistory(outgoingTexts, "01_intro", drafts)) {
    return step;
  }
  step = Math.max(step, 1);
  if (!rwExplainScriptsSentInHistory(outgoingTexts, drafts)) {
    return Math.min(step, 1);
  }
  step = Math.max(step, 2);
  if (!rwRegLinkSentInHistory(outgoingTexts, drafts)) {
    return Math.min(step, 3);
  }
  return Math.max(step, 4);
}

function isGreeting(text: string): boolean {
  return /^(hi|hello|hey|morning|good morning|good evening|yo)([\s,!.]|$)/i.test(
    (text || "").trim(),
  );
}

function hasUsableFollowUp(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return !/\b(fuck|scam|leave me alone|stop texting|not interested|no thanks|get out)\b/i.test(t);
}

function positiveSignal(text: string, intent: ZmIntent, effectiveStep: number): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

function wantsExplain(text: string, intent: ZmIntent, effectiveStep: number): boolean {
  const t = (text || "").trim();
  return (
    wantsDetailsAfterIntro(text) ||
    /^how\??$/i.test(t) ||
    /\bshow me examples?\b/i.test(t) ||
    /\blet\s*'?s?\s*do\s*it\b/i.test(t) ||
    intent === "question" ||
    intent === "interested" ||
    intent === "ready" ||
    positiveSignal(text, intent, effectiveStep)
  );
}

function wantsRegistrationBundle(
  text: string,
  intent: ZmIntent,
  effectiveStep: number,
): boolean {
  const t = (text || "").trim();
  return (
    isReadyForRegistration(text) ||
    wantsRegistrationLink(text) ||
    /\b(create account for me|can you create|make an account for me|create the account for me)\b/i.test(
      t,
    ) ||
    intent === "ready" ||
    (positiveSignal(text, intent, effectiveStep) && effectiveStep >= 2)
  );
}

export function resolveRwFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: ZmIntent,
  outgoingTexts: string[],
  drafts?: RwScriptDrafts,
  options?: {
    recentCustomerTexts?: string[];
  },
): RwScriptKey[] {
  const t = (text || "").trim();
  const out = outgoingTexts;
  const recentTexts = options?.recentCustomerTexts ?? [];

  if (intent === "declined") {
    return [];
  }

  const notRegisteredYet =
    isCustomerSaysNotRegisteredYet(t) || recentTextsIndicateNotRegistered(recentTexts);

  const introSent = rwScriptSentInHistory(out, "01_intro", drafts);
  const explainSent = rwExplainScriptsSentInHistory(out, drafts);
  const linkSent = rwRegLinkSentInHistory(out, drafts);
  const signal = positiveSignal(t, intent, effectiveStep);

  if (notRegisteredYet) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      return ["02_how_it_works", "03_deposit_table"];
    }
    if (linkSent && !wantsRegistrationLink(t) && !isRegistrationHelpRequest(t)) {
      return [];
    }
    return registrationResendScriptKeys("ZM", linkSent).filter((key): key is RwScriptKey =>
      RW_SCRIPT_KEYS.includes(key as RwScriptKey),
    );
  }

  if (isRegistrationHelpRequest(t) || isZmRegistrationAccountQuestion(t)) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      return ["02_how_it_works", "03_deposit_table"];
    }
    if (!linkSent) {
      return ["04_registration", "05_link"];
    }
    return [];
  }

  if (!introSent) {
    // First SMS: always script 1 — any text (money ask, hello, etc.).
    if (t) {
      return ["01_intro"];
    }
    return [];
  }

  if (!explainSent) {
    if (wantsExplain(t, intent, effectiveStep) || signal || intent === "interested") {
      return ["02_how_it_works", "03_deposit_table"];
    }
    return [];
  }

  if (!linkSent) {
    if (
      wantsRegistrationBundle(t, intent, effectiveStep) ||
      /\b(create account for me|can you create|make an account for me)\b/i.test(t) ||
      (explainSent && /^(ok|okay|yes|yeah|sure|alright|yep)\.?$/i.test(t))
    ) {
      return ["04_registration", "05_link"];
    }
    return [];
  }

  if (isRegistrationConfirmed(t) && signal) {
    return [];
  }

  return [];
}

export function limitRwScriptsForCustomerTurn(
  scriptKeys: RwScriptKey[],
  outgoingTexts: string[],
  drafts?: RwScriptDrafts,
): RwScriptKey[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  if (scriptKeys.includes("01_intro") && !rwScriptSentInHistory(outgoingTexts, "01_intro", drafts)) {
    return ["01_intro"];
  }
  if (
    scriptKeys.some((key) => RW_EXPLAIN_SEND_KEYS.has(key)) &&
    !rwExplainScriptsSentInHistory(outgoingTexts, drafts)
  ) {
    return ["02_how_it_works", "03_deposit_table"];
  }
  if (scriptKeys.some((key) => RW_REG_SEND_KEYS.has(key))) {
    const instructionsSent = rwRegistrationInstructionsSentInHistory(outgoingTexts, drafts);
    const linkSent = rwRegLinkSentInHistory(outgoingTexts, drafts);
    if (!instructionsSent) {
      return [...RW_REG_BUNDLE];
    }
    if (!linkSent) {
      return ["05_link"];
    }
    return [];
  }
  return [scriptKeys[0]!];
}

export function rwAllowsMultiSend(scriptKeys: RwScriptKey[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return true;
  }
  if (scriptKeys.some((key) => RW_EXPLAIN_SEND_KEYS.has(key))) {
    return true;
  }
  return scriptKeys.some((key) => RW_REG_SEND_KEYS.has(key));
}

export function rwStatusMoveAfterSend(sentScriptKeys: string[]): boolean {
  return sentScriptKeys.includes("05_link");
}

export function classifyRwMessage(
  text: string,
  effectiveStep: number,
  _outgoingTexts: string[],
  _drafts?: RwScriptDrafts,
): ZmIntent {
  return classifyZmIntent(text, { funnelStep: effectiveStep });
}

export function hasMinimumRwScriptDrafts(_drafts?: RwScriptDrafts): boolean {
  return RW_SCRIPT_KEYS.every((key) => Boolean(RW_BUILTIN_SCRIPTS[key]?.trim()));
}

export function inferRwScriptKeyFromOperatorText(text: string): RwScriptKey | "operator_other" | null {
  const t = text.toLowerCase();
  if (!t.trim()) {
    return null;
  }
  if (/tinyurl\.com|https?:\/\//.test(t) && t.length < 280 && !/how it works/i.test(t)) {
    return "05_link";
  }
  if (/google chrome|registration link|promo code|paste it/i.test(t)) {
    return "04_registration";
  }
  if (/ready to start today|\brwf\b|1000.*profit|profit.*1000/i.test(t)) {
    return "03_deposit_table";
  }
  if (/how it works|step 1|1\.|1\)|create a casino account/i.test(t)) {
    return "02_how_it_works";
  }
  if (/analytical|artificial intelligence|casino platforms|hi! i want/i.test(t)) {
    return "01_intro";
  }
  if (text.trim().length >= 40) {
    return "operator_other";
  }
  return null;
}

export function mergeRwScriptDraftsFromOperatorText(
  drafts: RwScriptDrafts | undefined,
  input: { text: string; source: string; at: string },
): RwScriptDrafts {
  const key = inferRwScriptKeyFromOperatorText(input.text);
  if (!key || key === "operator_other") {
    return drafts ?? {};
  }
  const text = input.text.trim();
  const prev = drafts?.[key];
  if (prev && prev.text.length >= text.length) {
    return drafts ?? {};
  }
  return {
    ...(drafts ?? {}),
    [key]: {
      text,
      source: input.source,
      at: input.at,
      samples: (prev?.samples ?? 0) + 1,
    },
  };
}
