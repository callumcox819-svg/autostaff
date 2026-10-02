import type { PagerMessage } from "./pager-client.js";
import type { ProofKind } from "./config.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import {
  customerAgreedAfterOfferTable,
  registrationResendScriptKeys,
} from "./funnel-common.js";
import {
  type MgIntent,
  classifyMgIntent,
  isFunnelPositiveReaction,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isRegistrationHelpRequest,
  isMgRegistrationAccountQuestion,
  isBarePostLinkAcknowledgment,
  isMgDepositAmountChoice,
  isMgOfferTableChoice,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./mg-intent.js";

const MG_GAME_ID_RE = /\b(17\d{6,}|16\d{6,})\b/;

export const MG_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "augmenter vos revenus",
  "02_how_it_works": "Comment ça marche",
  "03_mga_table": "5000 MGA - 20000 MGA",
  "04_registration": "code promo MAD778",
  "05_link": "tinyurl.com/mdg56",
  "06_deposit": "bouton vert",
  "07_game_id": "identifiant de jeu",
};

export const MG_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": [
    "augmenter vos revenus",
    "plateformes de casino",
    "intelligence artificielle analyse",
  ],
  "02_how_it_works": ["comment ça marche", "dépôt minimum", "5000 mga"],
  "03_mga_table": [
    "5000 mga - 20000 mga",
    "8000 mga - 40000 mga",
    "15000 mga - 120000 mga",
    "30000 mga - 240000 mga",
    "lequel préférez-vous",
    "grâce à mon aide",
  ],
  "04_registration": [
    "lien d'inscription spécial",
    "google chrome",
    "code promo mad778",
    "en un seul clic",
  ],
  "05_link": ["tinyurl.com/mdg56"],
  "06_deposit": ["déposer", "bouton vert", "capture d'écran pour confirmation"],
  "07_game_id": ["identifiant de jeu", "commence par les chiffres 17"],
};

export const MG_FOLDER_NAME_HINTS = ["мадаг", "madag", "madagascar", "mg", "mdg"];
export const MG_REG_SEND_KEYS = new Set(["04_registration", "05_link"]);
export const MG_EXPLAIN_SEND_KEYS = new Set(["02_how_it_works", "03_mga_table"]);

const MG_REG_BUNDLE = ["04_registration", "05_link"] as const;
export const MG_REGISTRATION_LINK = "https://tinyurl.com/MDG56";

export function scriptSnippet(key: string): string {
  return MG_SCRIPT_SNIPPETS[key] ?? "";
}

export function scriptSearchNeedles(key: string): string[] {
  return MG_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
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

export function mgScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  if (scriptKey === "04_registration") {
    return mgRegistrationInstructionsSentInHistory(outgoingTexts);
  }
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function explainScriptsSentInHistory(outgoingTexts: string[]): boolean {
  return (
    mgScriptSentInHistory(outgoingTexts, "02_how_it_works") &&
    mgScriptSentInHistory(outgoingTexts, "03_mga_table")
  );
}

/** One explain bubble per customer turn (02, then 03) — never both at once. */
export function nextMgExplainScript(outgoingTexts: string[]): string | null {
  if (!mgScriptSentInHistory(outgoingTexts, "02_how_it_works")) {
    return "02_how_it_works";
  }
  if (!mgScriptSentInHistory(outgoingTexts, "03_mga_table")) {
    return "03_mga_table";
  }
  return null;
}

export function regLinkSentInHistory(outgoingTexts: string[]): boolean {
  if (mgScriptSentInHistory(outgoingTexts, "05_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("tinyurl.com/mdg56");
}

export function mgRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  if (!blob.includes("mad778")) {
    return false;
  }
  return (
    blob.includes("lien d'inscription spécial") ||
    blob.includes("lien d'inscription special") ||
    (blob.includes("google chrome") && blob.includes("code promo")) ||
    blob.includes("en un seul clic")
  );
}

export function gameIdSentInHistory(outgoingTexts: string[]): boolean {
  return mgScriptSentInHistory(outgoingTexts, "07_game_id");
}

export function gameIdReceivedInText(text: string): boolean {
  return MG_GAME_ID_RE.test((text || "").trim());
}

export function gameIdReceivedFromProof(proofKind: ProofKind | undefined, proofText: string): boolean {
  if (!proofKind || !proofText.trim()) {
    return false;
  }
  if (proofKind === "id_screenshot") {
    return true;
  }
  if (gameIdReceivedInText(proofText)) {
    return true;
  }
  return false;
}

function customerIdReceived(
  text: string,
  recentTexts: string[],
  proofKind?: ProofKind,
  proofText?: string,
): boolean {
  const blob = [text, proofText ?? "", ...recentTexts].filter(Boolean).join("\n");
  return gameIdReceivedInText(blob) || gameIdReceivedFromProof(proofKind, blob);
}

export function depositSentInHistory(outgoingTexts: string[]): boolean {
  if (mgScriptSentInHistory(outgoingTexts, "06_deposit")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("bouton vert") && blob.includes("déposer");
}

function stepForOutgoingText(text: string): number {
  const t = text.toLowerCase();
  if (t.includes("bouton vert") || t.includes("après le dépôt, envoie-moi")) {
    return 7;
  }
  if (t.includes("identifiant de jeu") || t.includes("commence par les chiffres 17")) {
    return 6;
  }
  if (t.includes("tinyurl.com/mdg56") || t.includes("code promo mad778")) {
    return 4;
  }
  if (
    t.includes("5000 mga") ||
    t.includes("4000 mga") ||
    t.includes("lequel préférez-vous")
  ) {
    return 3;
  }
  if (t.includes("comment ça marche") && (t.includes("1.") || t.includes("1)"))) {
    return 2;
  }
  if (t.includes("augmenter vos revenus") || t.includes("plateformes de casino")) {
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

export function inferStepFromThread(messages: PagerMessage[]): number {
  let step = 0;
  for (const message of messages) {
    if (!isOutgoingDelivered(message)) {
      continue;
    }
    step = Math.max(step, stepForOutgoingText((message.text || "").trim()));
  }
  return step;
}

export function funnelStepFromScriptGaps(outgoingTexts: string[], storedStep = 0): number {
  let step = Math.max(storedStep, 0);
  if (!mgScriptSentInHistory(outgoingTexts, "01_intro")) {
    return 0;
  }
  step = Math.max(step, 1);
  if (!explainScriptsSentInHistory(outgoingTexts)) {
    return Math.min(step, 2);
  }
  step = Math.max(step, 3);
  if (!regLinkSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  step = Math.max(step, 4);
  if (!gameIdSentInHistory(outgoingTexts)) {
    return Math.min(step, 4);
  }
  step = Math.max(step, 5);
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

export function regSendTriggersInProgress(scriptKeys: string[]): boolean {
  return scriptKeys.includes("05_link");
}

export function limitMgScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  if (scriptKeys.includes("01_intro") && !mgScriptSentInHistory(outgoingTexts, "01_intro")) {
    return ["01_intro"];
  }
  if (
    scriptKeys.some((key) => MG_EXPLAIN_SEND_KEYS.has(key)) &&
    !explainScriptsSentInHistory(outgoingTexts)
  ) {
    const next = nextMgExplainScript(outgoingTexts);
    return next ? [next] : [];
  }
  if (scriptKeys.some((key) => MG_REG_SEND_KEYS.has(key))) {
    const instructionsSent = mgRegistrationInstructionsSentInHistory(outgoingTexts);
    const linkSent = regLinkSentInHistory(outgoingTexts);
    if (!linkSent) {
      if (!instructionsSent) {
        return [...MG_REG_BUNDLE];
      }
      return ["05_link"];
    }
    return [];
  }
  return [scriptKeys[0]!];
}

export function mgAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return true;
  }
  // 02 and 03 are always one-per-turn — never batch them.
  if (scriptKeys.some((key) => MG_EXPLAIN_SEND_KEYS.has(key))) {
    return false;
  }
  return scriptKeys.some((key) => MG_REG_SEND_KEYS.has(key));
}

export type MgStatusMoveTarget = "in_progress_registration" | "registration_complete";

export function mgStatusMoveTarget(sentScriptKeys: string[]): MgStatusMoveTarget | null {
  if (sentScriptKeys.includes("06_deposit")) {
    return "registration_complete";
  }
  if (sentScriptKeys.includes("05_link")) {
    return "in_progress_registration";
  }
  return null;
}

export function mgStatusMoveAfterSend(sentScriptKeys: string[]): boolean {
  return mgStatusMoveTarget(sentScriptKeys) !== null;
}

function positiveSignal(text: string, intent: MgIntent, effectiveStep: number): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

function wantsExplain(text: string, intent: MgIntent, effectiveStep: number): boolean {
  return (
    wantsDetailsAfterIntro(text) ||
    ["interested", "positive", "ready", "question"].includes(intent) ||
    positiveSignal(text, intent, effectiveStep)
  );
}

function isGreeting(text: string): boolean {
  return /^(salut|bonjour|bonsoir|hey|hello|hi|yo)([\s,!.]|$)/i.test((text || "").trim());
}

function hasUsableFollowUp(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return !/\b(fuck|scam|arnaque|laisse[- ]moi|stop|pas intéressé)\b/i.test(t);
}

function wantsDepositNow(text: string, intent: MgIntent): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    intent === "ready" ||
    /\b(faire (un )?dépôt|ready to deposit|je dépose|je depose|deposit now)\b/i.test(t)
  );
}

function wantsRegistrationBundle(text: string, intent: MgIntent, effectiveStep: number): boolean {
  return (
    isReadyForRegistration(text) ||
    wantsRegistrationLink(text) ||
    isRegistrationHelpRequest(text) ||
    customerAgreedAfterOfferTable(text) ||
    isMgOfferTableChoice(text) ||
    isMgDepositAmountChoice(text) ||
    intent === "ready" ||
    intent === "interested" ||
    intent === "positive" ||
    (positiveSignal(text, intent, effectiveStep) && effectiveStep >= 2)
  );
}

export function resolveMgFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: MgIntent,
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

  const introSent = mgScriptSentInHistory(out, "01_intro");
  const explainSent = explainScriptsSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const gameIdAskSent = gameIdSentInHistory(out);
  const depositSent = depositSentInHistory(out);
  const signal = positiveSignal(t, intent, effectiveStep);
  const idReceived = customerIdReceived(t, recentTexts, options?.proofKind, options?.proofText);

  if (notRegisteredYet) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      const next = nextMgExplainScript(out);
      return next ? [next] : [];
    }
    if (
      linkSent &&
      !wantsRegistrationLink(t) &&
      !isRegistrationHelpRequest(t) &&
      !isMgRegistrationAccountQuestion(t)
    ) {
      if (
        !gameIdAskSent &&
        !depositSent &&
        (isRegistrationConfirmed(t) || intent === "joined" || idReceived)
      ) {
        return ["07_game_id"];
      }
      return [];
    }
    return registrationResendScriptKeys("ZM", linkSent);
  }

  if (isRegistrationHelpRequest(t) || isMgRegistrationAccountQuestion(t)) {
    if (!introSent) {
      return ["01_intro"];
    }
    if (!explainSent) {
      const next = nextMgExplainScript(out);
      return next ? [next] : [];
    }
    if (!linkSent) {
      return ["04_registration", "05_link"];
    }
    if (
      !gameIdAskSent &&
      !depositSent &&
      (isRegistrationConfirmed(t) || intent === "joined" || idReceived)
    ) {
      return ["07_game_id"];
    }
    if (!depositSent && (idReceived || signal || options?.hasImage)) {
      return ["06_deposit"];
    }
    return [];
  }

  if (!introSent) {
    // First touch: any customer text/image starts the MG funnel (declined already returned above).
    if (t || options?.hasImage || options?.messageReaction) {
      return ["01_intro"];
    }
    return [];
  }

  if (!explainSent) {
    // One explain bubble per turn: 02, then wait; next turn 03.
    if (wantsExplain(t, intent, effectiveStep) || signal || t || options?.hasImage || options?.messageReaction) {
      const next = nextMgExplainScript(out);
      return next ? [next] : [];
    }
    return [];
  }

  if (!linkSent) {
    // After the MGA table: tier pick / oui / prêt → registration scripts (not AI).
    if (wantsRegistrationBundle(t, intent, effectiveStep)) {
      return ["04_registration", "05_link"];
    }
    return [];
  }

  if (!depositSent && idReceived) {
    return ["06_deposit"];
  }

  if (!gameIdAskSent && !depositSent) {
    if (!t && !options?.hasImage) {
      return [];
    }
    if (isBarePostLinkAcknowledgment(t, intent)) {
      return [];
    }
    if (
      isRegistrationConfirmed(t) ||
      intent === "joined" ||
      intent === "game_id_text" ||
      idReceived
    ) {
      return ["07_game_id"];
    }
    return [];
  }

  if (depositSent && !gameIdAskSent) {
    if (
      intent === "deposit_done" ||
      isRegistrationConfirmed(t) ||
      intent === "joined" ||
      idReceived ||
      intent === "game_id_text" ||
      options?.hasImage
    ) {
      return ["07_game_id"];
    }
    return [];
  }

  if (gameIdAskSent && !depositSent) {
    if (
      idReceived ||
      options?.hasImage ||
      intent === "game_id_text" ||
      intent === "image_only" ||
      isRegistrationConfirmed(t) ||
      intent === "joined" ||
      wantsDepositNow(t, intent) ||
      (signal && !isBarePostLinkAcknowledgment(t, intent))
    ) {
      return ["06_deposit"];
    }
    return [];
  }

  return [];
}

export function classifyMgMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): MgIntent {
  return classifyMgIntent(text, options);
}

export { MG_REG_BUNDLE };
