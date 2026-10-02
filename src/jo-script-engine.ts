import type { PagerMessage } from "./pager-client.js";
import type { ProofKind } from "./config.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { customerAgreedAfterOfferTable } from "./funnel-common.js";
import {
  type JoIntent,
  classifyJoIntent,
  isFunnelPositiveReaction,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isRegistrationHelpRequest,
  isJoRegistrationAccountQuestion,
  isBarePostLinkAcknowledgment,
  isJoDepositAmountChoice,
  isJoOfferTableChoice,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./jo-intent.js";

export const JO_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "منصات الكازينو",
  "02_how_it_works": "2 دينار أردني",
  "03_jod_table": "2 دينار أردني – 30 دينار أردني",
  "04_registration": "الرمز الترويجي JOR778",
  "05_link": "tinyurl.com/jor77",
};

export const JO_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": ["منصات الكازينو", "الذكاء الاصطناعي", "إذا كنت مهتمًا"],
  "02_how_it_works": ["كيف يعمل الأمر", "2 دينار أردني", "الموثوقية مضمونة"],
  "03_jod_table": [
    "2 دينار أردني – 30 دينار أردني",
    "5 دينار أردني – 75 دينار أردني",
    "15 دينار أردني – 120 دينار أردني",
    "ماذا ستختار يا صديقي",
  ],
  "04_registration": [
    "رابطًا خاصًا للتسجيل",
    "رابطا خاصا للتسجيل",
    "jor778",
    "google chrome",
    "إليك الرابط",
  ],
  "05_link": ["tinyurl.com/jor77"],
};

export const JO_FOLDER_NAME_HINTS = ["йордан", "jordan", "jo", "jod", "jor"];
export const JO_EXPLAIN_SEND_KEYS = new Set(["02_how_it_works", "03_jod_table"]);
export const JO_REG_SEND_KEYS = new Set(["04_registration", "05_link"]);
export const JO_REG_BUNDLE = ["04_registration", "05_link"] as const;
export const JO_REGISTRATION_LINK = "https://tinyurl.com/JOR77";

export function scriptSnippet(key: string): string {
  return JO_SCRIPT_SNIPPETS[key] ?? "";
}

export function scriptSearchNeedles(key: string): string[] {
  return JO_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
}

export function scriptSentInHistory(outgoingTexts: string[], snippet: string): boolean {
  const needle = snippet.trim().toLowerCase();
  if (!needle) {
    return false;
  }
  return outgoingTexts.some((text) => {
    const body = text.toLowerCase();
    return body.includes(needle) || needle.includes(body.slice(0, 80));
  });
}

export function joScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  if (scriptKey === "04_registration") {
    return joRegistrationInstructionsSentInHistory(outgoingTexts);
  }
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function howItWorksSentInHistory(outgoingTexts: string[]): boolean {
  return joScriptSentInHistory(outgoingTexts, "02_how_it_works");
}

export function tableSentInHistory(outgoingTexts: string[]): boolean {
  return joScriptSentInHistory(outgoingTexts, "03_jod_table");
}

export function explainScriptsSentInHistory(outgoingTexts: string[]): boolean {
  return howItWorksSentInHistory(outgoingTexts) && tableSentInHistory(outgoingTexts);
}

/** One explain bubble per turn: 02, then 03. */
export function nextJoExplainScript(outgoingTexts: string[]): string | null {
  if (!howItWorksSentInHistory(outgoingTexts)) {
    return "02_how_it_works";
  }
  if (!tableSentInHistory(outgoingTexts)) {
    return "03_jod_table";
  }
  return null;
}

export function regLinkSentInHistory(outgoingTexts: string[]): boolean {
  if (joScriptSentInHistory(outgoingTexts, "05_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("tinyurl.com/jor77");
}

export function joRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  if (!blob.includes("jor778")) {
    return false;
  }
  return (
    blob.includes("رابطًا خاصًا للتسجيل") ||
    blob.includes("رابطا خاصا للتسجيل") ||
    blob.includes("google chrome") ||
    blob.includes("إليك الرابط") ||
    blob.includes("اليك الرابط")
  );
}

function stepForOutgoingText(text: string): number {
  const t = text.toLowerCase();
  if (t.includes("tinyurl.com/jor77") || t.includes("jor778")) {
    return 4;
  }
  if (t.includes("ماذا ستختار") || t.includes("30 دينار")) {
    return 3;
  }
  if (t.includes("كيف يعمل الأمر") || t.includes("2 دينار أردني")) {
    return 2;
  }
  if (t.includes("منصات الكازينو") || t.includes("إذا كنت مهتمًا")) {
    return 1;
  }
  return 0;
}

function isOutgoingDelivered(message: PagerMessage): boolean {
  const direction = (message.messageDirection ?? "").toLowerCase();
  if (direction !== "outgoing" && direction !== "out") {
    return false;
  }
  return true;
}

export function joInferStepFromThread(messages: PagerMessage[]): number {
  let step = 0;
  for (const message of messages) {
    if (!isOutgoingDelivered(message)) {
      continue;
    }
    step = Math.max(step, stepForOutgoingText((message.text || "").trim()));
  }
  return step;
}

export function joFunnelStepFromScriptGaps(outgoingTexts: string[], storedStep = 0): number {
  let step = Math.max(storedStep, 0);
  if (!joScriptSentInHistory(outgoingTexts, "01_intro")) {
    return 0;
  }
  step = Math.max(step, 1);
  if (!howItWorksSentInHistory(outgoingTexts)) {
    return Math.min(step, 2);
  }
  step = Math.max(step, 2);
  if (!tableSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  step = Math.max(step, 3);
  if (!regLinkSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  return Math.max(step, 4);
}

export function collectOutgoingTexts(messages: PagerMessage[]): string[] {
  const chronological = [...messages].sort(
    (left, right) => Date.parse(left.createdAt ?? "") - Date.parse(right.createdAt ?? ""),
  );
  const texts: string[] = [];
  for (const message of chronological) {
    if (!isOutgoingDelivered(message)) {
      continue;
    }
    const text = (message.text || "").trim();
    if (text) {
      texts.push(text);
    }
  }
  return texts;
}

export function collectJoOutgoingTexts(messages: PagerMessage[]): string[] {
  return collectOutgoingTexts(messages);
}

export function nextJoRegScripts(outgoingTexts: string[]): string[] {
  const keys: string[] = [];
  if (!joRegistrationInstructionsSentInHistory(outgoingTexts)) {
    keys.push("04_registration");
  }
  if (!regLinkSentInHistory(outgoingTexts)) {
    keys.push("05_link");
  }
  return keys;
}

export function limitJoScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  if (scriptKeys.includes("01_intro") && !joScriptSentInHistory(outgoingTexts, "01_intro")) {
    return ["01_intro"];
  }
  if (
    scriptKeys.some((key) => JO_EXPLAIN_SEND_KEYS.has(key)) &&
    !explainScriptsSentInHistory(outgoingTexts)
  ) {
    const next = nextJoExplainScript(outgoingTexts);
    return next ? [next] : [];
  }
  if (scriptKeys.some((key) => JO_REG_SEND_KEYS.has(key))) {
    return nextJoRegScripts(outgoingTexts);
  }
  return [scriptKeys[0]!];
}

export function joAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return false;
  }
  if (scriptKeys.some((key) => JO_EXPLAIN_SEND_KEYS.has(key))) {
    return false; // 02 then 03 one per turn
  }
  return scriptKeys.some((key) => JO_REG_SEND_KEYS.has(key));
}

export type JoStatusMoveTarget = "in_progress_registration" | "registration_complete";

export function joStatusMoveTarget(sentScriptKeys: string[]): JoStatusMoveTarget | null {
  if (sentScriptKeys.includes("05_link")) {
    return "in_progress_registration";
  }
  return null;
}

function positiveSignal(text: string, intent: JoIntent, effectiveStep: number): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

function wantsExplain(text: string, intent: JoIntent, effectiveStep: number): boolean {
  return (
    wantsDetailsAfterIntro(text) ||
    ["interested", "positive", "ready", "question"].includes(intent) ||
    positiveSignal(text, intent, effectiveStep)
  );
}

function wantsRegistrationBundle(text: string, intent: JoIntent, effectiveStep: number): boolean {
  return (
    isReadyForRegistration(text) ||
    wantsRegistrationLink(text) ||
    isRegistrationHelpRequest(text) ||
    customerAgreedAfterOfferTable(text) ||
    isJoOfferTableChoice(text) ||
    isJoDepositAmountChoice(text) ||
    intent === "ready" ||
    intent === "interested" ||
    intent === "positive" ||
    (positiveSignal(text, intent, effectiveStep) && effectiveStep >= 2)
  );
}

export function resolveJoFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: JoIntent,
  outgoingTexts: string[],
  options?: {
    hasImage?: boolean;
    messageReaction?: string;
    recentCustomerTexts?: string[];
    proofKind?: ProofKind;
    proofText?: string;
  },
): string[] {
  const t = (text || "").trim();
  const out = outgoingTexts;
  const recentTexts = options?.recentCustomerTexts ?? [];

  if (intent === "declined") {
    return [];
  }

  const notRegisteredYet =
    isCustomerSaysNotRegisteredYet(t) || recentTextsIndicateNotRegistered(recentTexts);

  const introSent = joScriptSentInHistory(out, "01_intro");
  const explainSent = explainScriptsSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const signal = positiveSignal(t, intent, effectiveStep);

  if (notRegisteredYet) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      const next = nextJoExplainScript(out);
      return next ? [next] : [];
    }
    if (linkSent && !wantsRegistrationLink(t) && !isRegistrationHelpRequest(t)) {
      return [];
    }
    return nextJoRegScripts(out);
  }

  if (isRegistrationHelpRequest(t) || isJoRegistrationAccountQuestion(t)) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      const next = nextJoExplainScript(out);
      return next ? [next] : [];
    }
    if (!linkSent) {
      return [...JO_REG_BUNDLE];
    }
    return nextJoRegScripts(out);
  }

  if (!introSent) {
    if (t || options?.hasImage || options?.messageReaction) {
      return ["01_intro"];
    }
    return [];
  }

  if (!explainSent) {
    if (wantsExplain(t, intent, effectiveStep) || signal || t || options?.hasImage || options?.messageReaction) {
      const next = nextJoExplainScript(out);
      return next ? [next] : [];
    }
    return [];
  }

  if (!linkSent) {
    if (wantsRegistrationBundle(t, intent, effectiveStep)) {
      return [...JO_REG_BUNDLE];
    }
    return [];
  }

  if (isBarePostLinkAcknowledgment(t, intent)) {
    return [];
  }

  void options?.proofKind;
  void options?.proofText;
  void isRegistrationConfirmed;

  return [];
}

export function classifyJoMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): JoIntent {
  return classifyJoIntent(text, options);
}
