import type { PagerMessage } from "./pager-client.js";
import { isPositiveMessageReaction } from "./message-attachments.js";
import {
  isCustomerClarificationMessage,
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { registrationHelpScriptKeys, registrationLinkScriptKeys, registrationResendScriptKeys } from "./funnel-common.js";
import {
  type EgIntent,
  classifyEgIntent,
  isAppOrBrowserQuestion,
  isDepositConfirmed,
  isEgDepositTierChoice,
  isEgJoinOrRegistrationQuestion,
  isFunnelPositiveReaction,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isRegistrationHelpRequest,
  isRegistrationPending,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./eg-intent.js";

/** Matching pager-ai-bot EG snippets (no Telegram handoff auto-send). */
export const EG_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "إنت من مصر",
  "02_how_it_works": "تمام كده",
  "04_registration": "هبعتلك اللينك دلوقتي",
  "05_link": "tinyurl.com/Egypt0011",
  "06_deposit": "+ الأخضر",
  "07_game_id": "يبدأ ب 17",
  "08_app_or_browser": "ينفع الاتنين",
};

export const EG_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": ["إنت من مصر", "انت من مصر", "بساعد ناس يعملوا شوية دخل", "أهلا", "إنت من مصر؟"],
  "02_how_it_works": ["تمام كده", "كود eg011", "365-550", "730-1100"],
  "04_registration": ["هبعتلك اللينك دلوقتي", "جنيه مصري", "كود eg011"],
  "05_link": ["tinyurl.com/egypt0011", "egypt0011"],
  "06_deposit": ["+ الأخضر", "ابعتلي سكرين لما يخلص"],
  "07_game_id": ["يبدأ ب 17", "رقم الحساب"],
  "08_app_or_browser": ["ينفع الاتنين", "تطبيق أو متصفح"],
};

export const EG_SCRIPT_EXCLUDE_SNIPPETS: Record<string, string[]> = {
  "04_registration": ["تمام كده", "هتعمل إيداع"],
  "05_link": ["هبعتلك اللينك", "تمام كده"],
  "02_how_it_works": ["tinyurl.com", "هبعتلك اللينك"],
};

export const EG_FOLDER_NAME_HINTS = [
  "егип",
  "egypt",
  "hapka",
  "hapkatest",
  "mahmoud",
  "مصر",
];
export const EG_REG_SEND_KEYS = new Set(["04_registration", "05_link"]);
export const EG_EXPLAIN_SEND_KEYS = new Set(["02_how_it_works"]);

export function scriptSnippet(key: string): string {
  return EG_SCRIPT_SNIPPETS[key] ?? "";
}

/** Reject Latin/ZM templates masquerading as Egypt saved replies. */
export function containsArabicScript(text: string): boolean {
  return /[\u0600-\u06FF]/.test(text);
}

export function isEgScriptTextAcceptable(scriptKey: string, text: string): boolean {
  const body = (text || "").trim();
  if (!body) {
    return false;
  }
  if (scriptKey === "05_link") {
    return /tinyurl\.com\/egypt0011/i.test(body) || /^https?:\/\//i.test(body);
  }
  if (scriptKey === "04_registration" && isEgHowItWorksPitchBody(body)) {
    return false;
  }
  if (!containsArabicScript(body)) {
    return false;
  }
  return egScriptSentInHistory([body], scriptKey) || scriptSearchNeedles(scriptKey).some((needle) =>
    body.toLowerCase().includes(needle.toLowerCase()),
  );
}

export function scriptSearchNeedles(key: string): string[] {
  return EG_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
}

/** Human or bot already sent an Arabic intro pitch — do not re-send 01_intro. */
export function egIntroSentInHistory(outgoingTexts: string[]): boolean {
  if (egScriptSentInHistory(outgoingTexts, "01_intro")) {
    return true;
  }
  return outgoingTexts.some((text) => {
    const body = text.trim();
    if (!containsArabicScript(body) || body.length < 50) {
      return false;
    }
    return /أهلا|بساعد|مصر|365|530|1100|eg011|شوية دخل|كازين|casino|analytical|artificial intelligence/i.test(
      body,
    );
  });
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

export function egScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function explainScriptsSentInHistory(outgoingTexts: string[]): boolean {
  return egScriptSentInHistory(outgoingTexts, "02_how_it_works");
}

export function regLinkSentInHistory(outgoingTexts: string[]): boolean {
  if (egScriptSentInHistory(outgoingTexts, "05_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("tinyurl.com/egypt0011") || blob.includes("egypt0011");
}

export function egRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  return egFullRegistrationInstructionsSentInHistory(outgoingTexts);
}

/** Full Arabic reg text (EG011 + country/currency), not a bare link or partial operator line. */
export function egFullRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  return outgoingTexts.some((text) => isEgFullRegistrationBody(text));
}

/** 02_how_it_works mentions EG011 + جنيه — must not count as 04_registration sent. */
export function isEgHowItWorksPitchBody(text: string): boolean {
  const lower = (text || "").trim().toLowerCase();
  if (!lower.includes("تمام كده")) {
    return false;
  }
  return (
    lower.includes("365-550") ||
    lower.includes("730-1100") ||
    lower.includes("هتعمل إيداع") ||
    lower.includes("باخد 5%") ||
    lower.includes("هتعمل حساب من اللينك")
  );
}

function isEgFullRegistrationBody(text: string): boolean {
  const body = (text || "").trim();
  if (!body || !containsArabicScript(body) || body.length < 40) {
    return false;
  }
  const lower = body.toLowerCase();
  if (/^https?:\/\/\S+$/i.test(body)) {
    return false;
  }
  if (isEgHowItWorksPitchBody(body)) {
    return false;
  }
  return (
    lower.includes("هبعتلك اللينك") ||
    (lower.includes("انسخه") &&
      (lower.includes("chrome") || lower.includes("google") || lower.includes("متصفح"))) ||
    (lower.includes("egp") && lower.includes("جنيه مصري")) ||
    (lower.includes("كود eg011") &&
      lower.includes("خلصت") &&
      (lower.includes("chrome") || lower.includes("متصفح") || lower.includes("إيميل")))
  );
}

export function depositSentInHistory(outgoingTexts: string[]): boolean {
  if (egScriptSentInHistory(outgoingTexts, "06_deposit")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("+ الأخضر") ||
    blob.includes("الزر الأخضر") ||
    blob.includes("ابعتلي سكرين لما يخلص") ||
    blob.includes("ابعتلي سكرين واضح يظهر الرصيد") ||
    (blob.includes("إيداع") && blob.includes("اخضر"))
  );
}

export function gameIdSentInHistory(outgoingTexts: string[]): boolean {
  return egScriptSentInHistory(outgoingTexts, "07_game_id");
}

function stepForOutgoingText(text: string): number {
  const t = text.toLowerCase();
  if (t.includes("يبدأ ب 17") || t.includes("رقم الحساب")) {
    return 7;
  }
  if (t.includes("+ الأخضر") || t.includes("ابعتلي سكرين لما يخلص")) {
    return 6;
  }
  if (t.includes("tinyurl.com/egypt0011") || t.includes("egypt0011")) {
    return 4;
  }
  if (t.includes("هبعتلك اللينك") || t.includes("جنيه مصري")) {
    return 3;
  }
  if (t.includes("تمام كده") || t.includes("365-550") || t.includes("730-1100")) {
    return 2;
  }
  if (t.includes("إنت من مصر") || t.includes("انت من مصر") || t.includes("بساعد ناس")) {
    return 1;
  }
  return 0;
}

function isOutgoingScriptCandidate(message: PagerMessage): boolean {
  if (!message.text?.trim()) {
    return false;
  }
  const direction = (message.messageDirection ?? "").toLowerCase();
  return direction === "outgoing" || direction === "out";
}

export function inferStepFromThread(messages: PagerMessage[]): number {
  let step = 0;
  for (const message of messages) {
    // Count failed send attempts too — otherwise EG re-spams the same script after red "!".
    if (!isOutgoingScriptCandidate(message)) {
      continue;
    }
    step = Math.max(step, stepForOutgoingText((message.text || "").trim()));
  }
  return step;
}

/** Matches pager-ai-bot funnel_step_from_script_gaps for geo=eg. */
export function funnelStepFromScriptGaps(outgoingTexts: string[], storedStep = 0): number {
  let step = Math.max(storedStep, 0);
  if (!egIntroSentInHistory(outgoingTexts)) {
    return 0;
  }
  step = Math.max(step, 1);
  if (!explainScriptsSentInHistory(outgoingTexts)) {
    return Math.min(step, 1);
  }
  step = Math.max(step, 2);
  if (!regLinkSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  step = Math.max(step, 4);
  if (!depositSentInHistory(outgoingTexts)) {
    return Math.min(step, 5);
  }
  return Math.max(step, 6);
}

export function collectOutgoingTexts(messages: PagerMessage[]): string[] {
  const chronological = [...messages].sort(
    (left, right) => Date.parse(left.createdAt ?? "") - Date.parse(right.createdAt ?? ""),
  );
  const texts: string[] = [];
  for (const message of chronological) {
    // Include undelivered outgoings so we do not re-send after Messenger red "!".
    if (!isOutgoingScriptCandidate(message)) {
      continue;
    }
    const text = (message.text || "").trim();
    if (text) {
      texts.push(text);
    }
  }
  return texts;
}

export function regSendTriggersInProgress(scriptKeys: string[]): boolean {
  return scriptKeys.some((key) => EG_REG_SEND_KEYS.has(key));
}

/**
 * Only reopen an already-replied EG thread for a clear mid-funnel signal.
 * Never treat bare text / unread as a reason to push deposit / game_id.
 */
export function egFunnelNeedsContinuation(customerText: string, outgoingTexts: string[]): boolean {
  const introSent = egIntroSentInHistory(outgoingTexts);
  const explainSent = explainScriptsSentInHistory(outgoingTexts);
  const linkSent = regLinkSentInHistory(outgoingTexts);
  const depositSent = depositSentInHistory(outgoingTexts);
  const gameIdSent = gameIdSentInHistory(outgoingTexts);
  const t = (customerText || "").trim();
  if (!t) {
    return false;
  }
  if (isCustomerClarificationMessage(t)) {
    return true;
  }

  if (!introSent) {
    return true;
  }
  if (!explainSent) {
    return (
      wantsDetailsAfterIntro(customerText) ||
      isReadyForRegistration(customerText) ||
      isEgJoinOrRegistrationQuestion(customerText) ||
      isFunnelPositiveReaction(customerText, 1)
    );
  }
  if (!linkSent) {
    return (
      isEgJoinOrRegistrationQuestion(customerText) ||
      isEgDepositTierChoice(customerText) ||
      isReadyForRegistration(customerText) ||
      isRegistrationHelpRequest(customerText) ||
      wantsRegistrationLink(customerText) ||
      isFunnelPositiveReaction(customerText, 2)
    );
  }
  if (!depositSent) {
    return (
      isRegistrationConfirmed(customerText) ||
      isRegistrationPending(customerText) ||
      isRegistrationHelpRequest(customerText) ||
      isAppOrBrowserQuestion(customerText)
    );
  }
  if (!gameIdSent) {
    return (
      isDepositConfirmed(customerText) ||
      /\b(17\d{6,}|16\d{6,}|10\d{8,})\b/.test(customerText)
    );
  }
  return false;
}

function shouldSendDepositScript(
  text: string,
  _effectiveStep: number,
  outgoingTexts: string[],
  options?: { hasImage?: boolean },
): boolean {
  if (!regLinkSentInHistory(outgoingTexts)) {
    return false;
  }
  if (depositSentInHistory(outgoingTexts)) {
    return false;
  }
  return isRegistrationConfirmed(text) || isRegistrationPending(text) || Boolean(options?.hasImage);
}

function positiveSignal(text: string, intent: EgIntent, effectiveStep: number): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

function egRegScripts(linkSent: boolean, force = false): string[] {
  if (linkSent && !force) {
    return [];
  }
  return ["04_registration", "05_link"];
}

/**
 * Egypt funnel from pager-ai-bot:
 * 01_intro → 02_how_it_works → 04+05 reg → (08_app_or_browser) → 06_deposit → 07_game_id
 * Telegram handoff is NOT auto-sent.
 */
export function resolveEgFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: EgIntent,
  outgoingTexts: string[],
  options?: { hasImage?: boolean; messageReaction?: string; recentCustomerTexts?: string[] },
): string[] {
  const t = (text || "").trim();
  const out = outgoingTexts;
  const recentTexts = options?.recentCustomerTexts ?? [];
  const howSent = explainScriptsSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const signal = positiveSignal(t, intent, effectiveStep);

  if (intent === "declined") {
    return [];
  }

  const notRegisteredYet =
    isCustomerSaysNotRegisteredYet(t) || recentTextsIndicateNotRegistered(recentTexts);

  if (notRegisteredYet) {
    if (!egIntroSentInHistory(out)) {
      return ["01_intro"];
    }
    if (!howSent) {
      return ["02_how_it_works"];
    }
    return registrationResendScriptKeys("EG", linkSent);
  }

  if (isRegistrationHelpRequest(t) || isEgJoinOrRegistrationQuestion(t)) {
    if (!egIntroSentInHistory(out)) {
      return ["01_intro"];
    }
    if (!howSent) {
      return ["02_how_it_works"];
    }
    return egRegScripts(linkSent, true);
  }

  if (wantsRegistrationLink(t)) {
    if (!egFullRegistrationInstructionsSentInHistory(out)) {
      return ["04_registration", "05_link"];
    }
    return registrationLinkScriptKeys("EG", linkSent);
  }

  if (howSent && !linkSent) {
    if (
      wantsRegistrationLink(t) ||
      isReadyForRegistration(t) ||
      isRegistrationPending(t) ||
      signal ||
      intent === "ready" ||
      intent === "positive" ||
      intent === "question" ||
      intent === "interested" ||
      isEgDepositTierChoice(t) ||
      /استثمر|أريد|اريد|ايو|نجرب|مهتم|تمام/i.test(t)
    ) {
      return egRegScripts(linkSent);
    }
  }

  if (
    isAppOrBrowserQuestion(t) &&
    effectiveStep >= 2 &&
    effectiveStep < 6 &&
    !egScriptSentInHistory(out, "08_app_or_browser")
  ) {
    return ["08_app_or_browser"];
  }

  if (effectiveStep < 1) {
    if (egIntroSentInHistory(out)) {
      if (signal || intent === "question" || wantsDetailsAfterIntro(t) || t.length > 0) {
        return howSent ? egRegScripts(linkSent) : ["02_how_it_works"];
      }
      return resolveEgBacklogFallback(effectiveStep, out, intent, t, options);
    }
    if (
      ["interested", "positive", "ready", "question", "unknown"].includes(intent) ||
      signal ||
      t.length > 0
    ) {
      return ["01_intro"];
    }
    return resolveEgBacklogFallback(effectiveStep, out, intent, t, options);
  }

  if (effectiveStep < 2) {
    if (howSent) {
      if (
        isReadyForRegistration(t) ||
        wantsRegistrationLink(t) ||
        signal ||
        intent === "ready" ||
        intent === "positive" ||
        intent === "question" ||
        intent === "interested" ||
        intent === "unknown" ||
        /استثمر|أريد|اريد|ايو|نجرب|مهتم|تمام/i.test(t) ||
        t.length > 0
      ) {
        return egRegScripts(linkSent);
      }
      return resolveEgBacklogFallback(effectiveStep, out, intent, t, options);
    }
    if (
      intent === "interested" ||
      intent === "positive" ||
      intent === "ready" ||
      intent === "question" ||
      wantsDetailsAfterIntro(t) ||
      isReadyForRegistration(t) ||
      signal ||
      /استثمر|أريد أن|اريد ان|أنا مهتم|موضوع|شغل|ازاي|إزاي/i.test(t) ||
      t.length > 0
    ) {
      return ["02_how_it_works"];
    }
    return resolveEgBacklogFallback(effectiveStep, out, intent, t, options);
  }

  if (effectiveStep < 4) {
    if (
      isReadyForRegistration(t) ||
      wantsRegistrationLink(t) ||
      intent === "ready" ||
      intent === "positive" ||
      intent === "question" ||
      intent === "interested" ||
      intent === "unknown" ||
      signal ||
      isEgDepositTierChoice(t) ||
      t.length > 0
    ) {
      return egRegScripts(linkSent);
    }
    return resolveEgBacklogFallback(effectiveStep, out, intent, t, options);
  }

  if (isRegistrationPending(t)) {
    return egRegScripts(linkSent);
  }

  if (effectiveStep < 7) {
    if (intent === "game_id_text") {
      return depositSentInHistory(out) && !gameIdSentInHistory(out) ? ["07_game_id"] : [];
    }
    if (isRegistrationConfirmed(t) || intent === "joined") {
      return shouldSendDepositScript(t, effectiveStep, out, options) ? ["06_deposit"] : [];
    }
    // Deposit only after clear reg confirm / pending / proof image — never on bare text.
    if (linkSent && !depositSentInHistory(out) && shouldSendDepositScript(t, effectiveStep, out, options)) {
      return ["06_deposit"];
    }
    if (
      !linkSent &&
      (intent === "interested" ||
        intent === "positive" ||
        intent === "ready" ||
        intent === "question" ||
        signal ||
        isEgDepositTierChoice(t) ||
        wantsRegistrationLink(t) ||
        isReadyForRegistration(t))
    ) {
      return egRegScripts(linkSent);
    }
    return [];
  }

  if (effectiveStep < 8 && intent === "game_id_text") {
    if (gameIdSentInHistory(out)) {
      return [];
    }
    if (depositSentInHistory(out)) {
      return ["07_game_id"];
    }
    return [];
  }

  // Game ID ask only after deposit confirm / proof — never re-nudge on silence.
  if (
    depositSentInHistory(out) &&
    !gameIdSentInHistory(out) &&
    (isDepositConfirmed(t) ||
      intent === "deposit_done" ||
      intent === "image_only" ||
      options?.hasImage ||
      isPositiveMessageReaction(options?.messageReaction))
  ) {
    return ["07_game_id"];
  }

  if (linkSent && (isRegistrationHelpRequest(t) || isEgJoinOrRegistrationQuestion(t) || wantsRegistrationLink(t) || isAppOrBrowserQuestion(t))) {
    if (isAppOrBrowserQuestion(t) && !egScriptSentInHistory(out, "08_app_or_browser")) {
      return ["08_app_or_browser"];
    }
    return [...registrationHelpScriptKeys("EG")];
  }

  return [];
}

/**
 * Early-funnel catch-up only (intro → explain → reg).
 * Never auto-push deposit / game_id without a clear customer signal.
 */
export function resolveEgBacklogFallback(
  effectiveStep: number,
  outgoingTexts: string[],
  intent: EgIntent = "unknown",
  text = "",
  options?: { hasImage?: boolean; messageReaction?: string },
): string[] {
  const out = outgoingTexts;
  const introSent = egIntroSentInHistory(out);
  const howSent = explainScriptsSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const depositSent = depositSentInHistory(out);
  const gameIdSent = gameIdSentInHistory(out);
  const t = (text || "").trim();

  if (intent === "declined") {
    return [];
  }
  if (!introSent) {
    return t ? ["01_intro"] : [];
  }
  if (!howSent) {
    if (
      wantsDetailsAfterIntro(t) ||
      isReadyForRegistration(t) ||
      isEgJoinOrRegistrationQuestion(t) ||
      isFunnelPositiveReaction(t, 1) ||
      intent === "interested" ||
      intent === "positive" ||
      intent === "ready" ||
      intent === "question"
    ) {
      return ["02_how_it_works"];
    }
    return [];
  }
  if (!linkSent) {
    if (
      wantsRegistrationLink(t) ||
      isReadyForRegistration(t) ||
      isEgDepositTierChoice(t) ||
      isEgJoinOrRegistrationQuestion(t) ||
      isRegistrationHelpRequest(t) ||
      isFunnelPositiveReaction(t, 2) ||
      intent === "interested" ||
      intent === "positive" ||
      intent === "ready" ||
      intent === "question"
    ) {
      return ["04_registration", "05_link"];
    }
    return [];
  }
  if (!depositSent && shouldSendDepositScript(t, effectiveStep, out, options)) {
    return ["06_deposit"];
  }
  if (
    depositSent &&
    !gameIdSent &&
    (isDepositConfirmed(t) ||
      intent === "deposit_done" ||
      intent === "image_only" ||
      options?.hasImage ||
      isPositiveMessageReaction(options?.messageReaction))
  ) {
    return ["07_game_id"];
  }
  return [];
}

const EG_REG_BUNDLE = ["04_registration", "05_link"] as const;

/** One funnel stage per customer message — reg text+link go together. */
export function limitEgScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  if (scriptKeys.includes("01_intro") && !egIntroSentInHistory(outgoingTexts)) {
    return ["01_intro"];
  }
  if (
    scriptKeys.some((key) => EG_EXPLAIN_SEND_KEYS.has(key)) &&
    !explainScriptsSentInHistory(outgoingTexts)
  ) {
    return ["02_how_it_works"];
  }
  if (scriptKeys.includes("08_app_or_browser")) {
    return ["08_app_or_browser"];
  }
  if (scriptKeys.some((key) => EG_REG_SEND_KEYS.has(key))) {
    const fullRegSent = egFullRegistrationInstructionsSentInHistory(outgoingTexts);
    const linkSent = regLinkSentInHistory(outgoingTexts);
    if (!fullRegSent) {
      return [...EG_REG_BUNDLE];
    }
    if (!linkSent) {
      return ["05_link"];
    }
    if (scriptKeys.length === 1 && scriptKeys[0] === "05_link") {
      return ["05_link"];
    }
    return scriptKeys.filter((key) => !EG_REG_SEND_KEYS.has(key)).slice(0, 1);
  }
  return [scriptKeys[0]!];
}

export function egAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return true;
  }
  if (scriptKeys.some((key) => EG_EXPLAIN_SEND_KEYS.has(key))) {
    return true;
  }
  return scriptKeys.some((key) => EG_REG_SEND_KEYS.has(key));
}

export function classifyEgMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): EgIntent {
  return classifyEgIntent(text, options);
}
