import type { PagerMessage } from "./pager-client.js";
import type { ProofKind } from "./config.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { customerAgreedAfterOfferTable } from "./funnel-common.js";
import {
  type DjIntent,
  classifyDjIntent,
  isFunnelPositiveReaction,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isRegistrationHelpRequest,
  isDjRegistrationAccountQuestion,
  isBarePostLinkAcknowledgment,
  isDjDepositAmountChoice,
  isDjOfferTableChoice,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./dj-intent.js";

export const DJ_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "gagner de l'argent dans les casinos",
  "02_how_it_works": "dépôt minimum 40 DJF",
  "03_djf_table": "100 DJF - 1000 DJF",
  "04_ready_ask": "démarrer avec 300 DJF",
  "05_registration": "code promo BJI777",
  "06_link": "tinyurl.com/bji777",
  "07_promo": "code promo",
};

export const DJ_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": [
    "gagner de l'argent dans les casinos",
    "approche fondée sur les données",
    "systèmes analytiques",
  ],
  "02_how_it_works": ["dépôt minimum 40 djf", "40 djf", "groupe privé"],
  "03_djf_table": [
    "100 djf - 1000 djf",
    "200 djf - 5000 djf",
    "500 djf - 12000 djf",
    "1000 djf - 35000 djf",
    "que choisiras-tu",
  ],
  "04_ready_ask": ["300 djf", "es-tu prêt à démarrer", "pret a demarrer"],
  "05_registration": [
    "lien d'inscription spécial",
    "code promo bji777",
    "voici le lien",
    "en un seul clic",
  ],
  "06_link": ["tinyurl.com/bji777"],
  "07_promo": ["code promo\nbji777", "code promo"],
};

export const DJ_FOLDER_NAME_HINTS = ["джибут", "djibouti", "djib", "djf", "bji"];
export const DJ_OFFER_SEND_KEYS = new Set(["03_djf_table", "04_ready_ask"]);
export const DJ_REG_SEND_KEYS = new Set(["05_registration", "06_link", "07_promo"]);
export const DJ_REG_BUNDLE = ["05_registration", "06_link", "07_promo"] as const;
export const DJ_REGISTRATION_LINK = "https://tinyurl.com/BJI777";

export function scriptSnippet(key: string): string {
  return DJ_SCRIPT_SNIPPETS[key] ?? "";
}

export function scriptSearchNeedles(key: string): string[] {
  return DJ_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
}

export function scriptSentInHistory(outgoingTexts: string[], snippet: string): boolean {
  const needle = snippet.trim().toLowerCase();
  if (!needle) {
    return false;
  }
  return outgoingTexts.some((text) => {
    const body = (text || "").trim().toLowerCase();
    if (!body) {
      return false;
    }
    if (body.includes(needle)) {
      return true;
    }
    // Reverse match only for substantial bodies — empty/short strings made
    // `needle.includes("")` / `includes("bji777")` falsely mark the link as sent.
    if (body.length >= 20 && needle.includes(body.slice(0, 80))) {
      return true;
    }
    return false;
  });
}

export function djScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  if (scriptKey === "05_registration") {
    return djRegistrationInstructionsSentInHistory(outgoingTexts);
  }
  if (scriptKey === "07_promo") {
    return promoSentInHistory(outgoingTexts);
  }
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function howItWorksSentInHistory(outgoingTexts: string[]): boolean {
  return djScriptSentInHistory(outgoingTexts, "02_how_it_works");
}

export function offerScriptsSentInHistory(outgoingTexts: string[]): boolean {
  return (
    djScriptSentInHistory(outgoingTexts, "03_djf_table") &&
    djScriptSentInHistory(outgoingTexts, "04_ready_ask")
  );
}

/** After how-it-works: send table + ready-ask together (two bubbles). */
export function nextDjOfferScripts(outgoingTexts: string[]): string[] {
  const keys: string[] = [];
  if (!djScriptSentInHistory(outgoingTexts, "03_djf_table")) {
    keys.push("03_djf_table");
  }
  if (!djScriptSentInHistory(outgoingTexts, "04_ready_ask")) {
    keys.push("04_ready_ask");
  }
  return keys;
}

export function regLinkSentInHistory(outgoingTexts: string[]): boolean {
  if (djScriptSentInHistory(outgoingTexts, "06_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("tinyurl.com/bji777");
}

export function promoSentInHistory(outgoingTexts: string[]): boolean {
  // Only the standalone promo bubble counts — not the BJI777 mention inside 05_registration.
  return outgoingTexts.some((text) => {
    const t = text.trim().toLowerCase().replace(/\r\n/g, "\n");
    if (t.includes("lien d'inscription") || t.includes("voici le lien") || t.includes("tinyurl.com")) {
      return false;
    }
    return (
      /^code promo\s*\n\s*bji777\.?$/i.test(t) ||
      /^code promo\s+bji777\.?$/i.test(t) ||
      /^bji777\.?$/i.test(t)
    );
  });
}

export function djRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  if (!blob.includes("bji777")) {
    return false;
  }
  return (
    blob.includes("lien d'inscription spécial") ||
    blob.includes("lien d'inscription special") ||
    blob.includes("voici le lien") ||
    (blob.includes("inscription") && blob.includes("code promo"))
  );
}

function stepForOutgoingText(text: string): number {
  const t = text.toLowerCase();
  if (t.includes("tinyurl.com/bji777") || /^bji777$/i.test(t.trim())) {
    return 5;
  }
  if (t.includes("300 djf") && t.includes("démarrer")) {
    return 4;
  }
  if (t.includes("100 djf - 1000 djf") || t.includes("que choisiras-tu")) {
    return 3;
  }
  if (t.includes("40 djf") && (t.includes("1)") || t.includes("étape"))) {
    return 2;
  }
  if (t.includes("gagner de l'argent") || t.includes("casinos en ligne")) {
    return 1;
  }
  return 0;
}

function isOutgoingDelivered(message: PagerMessage): boolean {
  const direction = (message.messageDirection ?? "").toLowerCase();
  if (direction !== "outgoing" && direction !== "out") {
    return false;
  }
  const text = (message.text || "").trim();
  if (text) {
    return true;
  }
  return Boolean(message.isDelivered || message.facebookMessageId);
}

export function djInferStepFromThread(messages: PagerMessage[]): number {
  let step = 0;
  for (const message of messages) {
    if (!isOutgoingDelivered(message)) {
      continue;
    }
    step = Math.max(step, stepForOutgoingText((message.text || "").trim()));
  }
  return step;
}

export function djFunnelStepFromScriptGaps(outgoingTexts: string[], storedStep = 0): number {
  let step = Math.max(storedStep, 0);
  if (!djScriptSentInHistory(outgoingTexts, "01_intro")) {
    return 0;
  }
  step = Math.max(step, 1);
  if (!howItWorksSentInHistory(outgoingTexts)) {
    return Math.min(step, 2);
  }
  step = Math.max(step, 2);
  if (!offerScriptsSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  step = Math.max(step, 4);
  if (!regLinkSentInHistory(outgoingTexts)) {
    return Math.min(step, 4);
  }
  return Math.max(step, 5);
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

export function collectDjOutgoingTexts(messages: PagerMessage[]): string[] {
  return collectOutgoingTexts(messages);
}

export function limitDjScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  if (scriptKeys.includes("01_intro") && !djScriptSentInHistory(outgoingTexts, "01_intro")) {
    return ["01_intro"];
  }
  if (scriptKeys.includes("02_how_it_works") && !howItWorksSentInHistory(outgoingTexts)) {
    return ["02_how_it_works"];
  }
  if (scriptKeys.some((key) => DJ_OFFER_SEND_KEYS.has(key)) && !offerScriptsSentInHistory(outgoingTexts)) {
    return nextDjOfferScripts(outgoingTexts);
  }
  if (scriptKeys.some((key) => DJ_REG_SEND_KEYS.has(key))) {
    return nextDjRegScripts(outgoingTexts);
  }
  return [scriptKeys[0]!];
}

export function nextDjRegScripts(outgoingTexts: string[]): string[] {
  const keys: string[] = [];
  if (!djRegistrationInstructionsSentInHistory(outgoingTexts)) {
    keys.push("05_registration");
  }
  if (!regLinkSentInHistory(outgoingTexts)) {
    keys.push("06_link");
  }
  if (!promoSentInHistory(outgoingTexts) || !regLinkSentInHistory(outgoingTexts)) {
    if (!promoSentInHistory(outgoingTexts)) {
      keys.push("07_promo");
    }
  }
  // Dedupe while preserving order
  return [...new Set(keys)];
}

export function djAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro") || scriptKeys.includes("02_how_it_works")) {
    return false;
  }
  if (scriptKeys.some((key) => DJ_OFFER_SEND_KEYS.has(key))) {
    return true; // table + ready_ask together
  }
  return scriptKeys.some((key) => DJ_REG_SEND_KEYS.has(key));
}

export type DjStatusMoveTarget = "in_progress_registration" | "registration_complete";

export function djStatusMoveTarget(sentScriptKeys: string[]): DjStatusMoveTarget | null {
  if (sentScriptKeys.includes("06_link")) {
    return "in_progress_registration";
  }
  return null;
}

function positiveSignal(text: string, intent: DjIntent, effectiveStep: number): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

function wantsExplain(text: string, intent: DjIntent, effectiveStep: number): boolean {
  return (
    wantsDetailsAfterIntro(text) ||
    ["interested", "positive", "ready", "question"].includes(intent) ||
    positiveSignal(text, intent, effectiveStep)
  );
}

function wantsRegistrationBundle(text: string, intent: DjIntent, effectiveStep: number): boolean {
  return (
    isReadyForRegistration(text) ||
    wantsRegistrationLink(text) ||
    isRegistrationHelpRequest(text) ||
    customerAgreedAfterOfferTable(text) ||
    isDjOfferTableChoice(text) ||
    isDjDepositAmountChoice(text) ||
    intent === "ready" ||
    intent === "interested" ||
    intent === "positive" ||
    (positiveSignal(text, intent, effectiveStep) && effectiveStep >= 2)
  );
}

export function resolveDjFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: DjIntent,
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

  const introSent = djScriptSentInHistory(out, "01_intro");
  const howSent = howItWorksSentInHistory(out);
  const offerSent = offerScriptsSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const signal = positiveSignal(t, intent, effectiveStep);

  if (notRegisteredYet) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!howSent) {
      return ["02_how_it_works"];
    }
    if (!offerSent) {
      return nextDjOfferScripts(out);
    }
    if (linkSent && !wantsRegistrationLink(t) && !isRegistrationHelpRequest(t)) {
      return [];
    }
    return nextDjRegScripts(out);
  }

  if (isRegistrationHelpRequest(t) || isDjRegistrationAccountQuestion(t)) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!howSent) {
      return ["02_how_it_works"];
    }
    if (!offerSent) {
      return nextDjOfferScripts(out);
    }
    if (!linkSent) {
      return [...DJ_REG_BUNDLE];
    }
    return nextDjRegScripts(out);
  }

  if (!introSent) {
    if (t || options?.hasImage || options?.messageReaction) {
      return ["01_intro"];
    }
    return [];
  }

  if (!howSent) {
    if (wantsExplain(t, intent, effectiveStep) || signal || t || options?.hasImage || options?.messageReaction) {
      return ["02_how_it_works"];
    }
    return [];
  }

  if (!offerSent) {
    if (wantsExplain(t, intent, effectiveStep) || signal || t || options?.hasImage || options?.messageReaction) {
      return nextDjOfferScripts(out);
    }
    return [];
  }

  if (!linkSent) {
    // Reg already went out without URL — always finish with link+promo (even «Dsl» / short replies).
    if (djRegistrationInstructionsSentInHistory(out)) {
      return nextDjRegScripts(out);
    }
    if (wantsRegistrationBundle(t, intent, effectiveStep)) {
      return [...DJ_REG_BUNDLE];
    }
    return [];
  }

  // After link: fill missing promo if needed; otherwise scripts done (support AI / follow-up).
  const missingReg = nextDjRegScripts(out);
  if (missingReg.length && !isBarePostLinkAcknowledgment(t, intent)) {
    if (isRegistrationConfirmed(t) || intent === "joined" || wantsRegistrationLink(t) || signal) {
      return missingReg;
    }
  }

  return [];
}

export function classifyDjMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): DjIntent {
  return classifyDjIntent(text, options);
}

export { DJ_REG_BUNDLE as DJ_REGISTRATION_BUNDLE };
