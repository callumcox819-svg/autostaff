import type { PagerMessage } from "./pager-client.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { registrationResendScriptKeys, customerAgreedAfterOfferTable } from "./funnel-common.js";
import {
  type CmIntent,
  classifyCmIntent,
  isAgeAnswer,
  isRegistrationBlocked,
  isClientReadyPhrase,
  isDepositTierChoice,
  isFunnelPositiveReaction,
  isCmProfitFigure,
  isCmRegistrationHelpRequest,
  isReadyForRegistration,
  isRegistrationAccountQuestion,
  isRegistrationConfirmed,
  isRegistrationPending,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./cm-intent.js";

export const CM_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "Tu es du Cameroun",
  "01_intro_2": "L'IA analyse",
  "01_intro_3": "Mon équipe cumule",
  "02_age": "Quel âge avez-vous",
  "03_steps": "voici comment ça fonctionne",
  "04_tier": "140 000 CFA",
  "05_registration": "CASH056",
  "06_link": "CMR056",
  "07_chrome": "Copiez ce lien",
  "07_mtn_tip": "ne s'ouvre pas sur MTN",
  "08_game_id": "commence par 17",
  "09_deposit": "bouton vert",
  "10_tg_invite": "canal Telegram privé",
  "11_tg_link": "XtIY04zvcVw2YzZi",
};

export const CM_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": ["tu es du cameroun", "bonjour ! tu es du cameroun", "bonjour !tu es du cameroun"],
  "01_intro_2": [
    "l'ia analyse",
    "l ia analyse",
    "approche « insider »",
    'approche "insider"',
    "gagner ensemble",
  ],
  "01_intro_3": [
    "mon équipe cumule",
    "mon equipe cumule",
    "ans d'expérience sur le terrain",
    "ans d'experience sur le terrain",
    "pour moi, c'est un business",
    "personnes sérieuses",
    "gagner ensemble",
  ],
  "02_age": ["quel âge", "quel age", "age avez-vous", "age as-tu"],
  "03_steps": [
    "voici comment ça fonctionne",
    "d'accord, voici comment",
    "crée ton compte casino",
    "cree ton compte casino",
    "dépôt minimum de 1 000",
  ],
  "04_tier": [
    "140 000 cfa",
    "190 000 cfa",
    "240 000 cfa",
    "290 000 cfa",
    "340 000 cfa",
    "1000 cfa - 140 000",
    "1500 cfa - 190 000",
    "2000 cfa - 240 000",
    "2500 cfa - 290 000",
    "3000 cfa - 340 000",
    "1 000 cfa — 140 000",
    "1 000 cfa - 140 000",
    "que vas-tu choisir",
    "tu choisis quoi",
    "voici ce que tu peux obtenir",
    "investissement → gain",
    "bénéfice",
  ],
  "05_registration": ["je vais vous envoyer", "lien d'inscription spécial", "code promotionnel", "cash056"],
  "06_link": ["cmr056", "tinyurl.com/cmr056"],
  "07_chrome": ["copiez ce lien", "navigateur google chrome"],
  "07_mtn_tip": ["ne s'ouvre pas sur mtn", "essayez le wi-fi", "autre opérateur mobile"],
  "08_game_id": ["commence par 17", "numéro de joueur"],
  "09_deposit": ["bouton vert", "déposer", "deposer", "mtn", "orange"],
  "10_tg_invite": ["canal telegram privé", "canal telegram prive"],
  "11_tg_link": ["xtiy04zvcvw", "t.me/"],
};

export const CM_SCRIPT_EXCLUDE_SNIPPETS: Record<string, string[]> = {
  "05_registration": ["voici comment ça fonctionne", "d'accord, voici comment", "crée ton compte casino"],
  "06_link": ["voici comment ça fonctionne", "d'accord, voici comment"],
  "07_chrome": ["voici comment ça fonctionne", "que vas-tu choisir"],
  "03_steps": ["cash056", "cmr056", "camerun01", "google chrome"],
  "04_tier": ["cash056", "cmr056", "camerun01", "google chrome"],
};

export const CM_FOLDER_NAME_HINTS = ["камерун", "cameroon", "cameroun", "cm"];

/** Initial reg send: instructions + link only. Chrome/MTN tip are help-only, never after folder move. */
export const CM_REG_SEND_KEYS = new Set(["05_registration", "06_link", "07_chrome", "07_mtn_tip"]);
export const CM_INTRO_SEND_KEYS = new Set(["01_intro", "01_intro_3"]);

const CM_INTRO_BUNDLE = ["01_intro", "01_intro_3"] as const;
const CM_REG_BUNDLE = ["05_registration", "06_link"] as const;

export function scriptSnippet(key: string): string {
  return CM_SCRIPT_SNIPPETS[key] ?? "";
}

export function scriptSearchNeedles(key: string): string[] {
  return CM_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
}

export function cmScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  if (scriptKey === "01_intro_2") {
    const blob = outgoingTexts.join("\n").toLowerCase();
    if (blob.includes("l'ia analyse") || blob.includes("l ia analyse")) {
      return true;
    }
  }
  if (scriptKey === "01_intro_3") {
    const blob = outgoingTexts.join("\n").toLowerCase();
    if (blob.includes("gagner ensemble")) {
      return true;
    }
    if (blob.includes("mon équipe") || blob.includes("mon equipe")) {
      return blob.includes("pour moi, c'est un business") || blob.includes("personnes sérieuses");
    }
    return false;
  }
  if (scriptKey === "04_tier") {
    return tierSentInHistory(outgoingTexts);
  }
  if (scriptKey === "05_registration") {
    return cmRegistrationInstructionsSentInHistory(outgoingTexts);
  }
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function tierSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("140 000 cfa") ||
    blob.includes("190 000 cfa") ||
    blob.includes("240 000 cfa") ||
    blob.includes("290 000 cfa") ||
    blob.includes("340 000 cfa") ||
    blob.includes("1000 cfa - 140") ||
    blob.includes("1500 cfa - 190") ||
    blob.includes("2000 cfa - 240") ||
    blob.includes("2500 cfa - 290") ||
    blob.includes("3000 cfa - 340") ||
    blob.includes("que vas-tu choisir") ||
    blob.includes("tu choisis quoi") ||
    blob.includes("voici ce que tu peux obtenir") ||
    blob.includes("investissement → gain") ||
    blob.includes("investissement -> gain") ||
    blob.includes("obtenir avec mon aide")
  );
}

export function stepsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("voici comment ça fonctionne") ||
    blob.includes("voici comment ca fonctionne") ||
    blob.includes("d'accord, voici comment") ||
    blob.includes("d accord, voici comment") ||
    ((blob.includes("crée ton compte casino") || blob.includes("cree ton compte casino")) &&
      blob.includes("dépôt minimum"))
  );
}

function ageQuestionSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("quel âge") ||
    blob.includes("quel age") ||
    blob.includes("age avez-vous") ||
    blob.includes("age as-tu") ||
    blob.includes("âge avez") ||
    blob.includes("age as tu")
  );
}

export function cmAgeQuestionSentInHistory(outgoingTexts: string[]): boolean {
  return ageQuestionSentInHistory(outgoingTexts);
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

export function regLinkSentInHistory(outgoingTexts: string[]): boolean {
  if (cmScriptSentInHistory(outgoingTexts, "06_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("cmr056") ||
    blob.includes("camerun01") ||
    blob.includes("tinyurl.com/cmr") ||
    blob.includes("tinyurl.com/camerun")
  );
}

export function cmRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  if (!blob.includes("cash056")) {
    return false;
  }
  return (
    blob.includes("je vais vous envoyer") ||
    blob.includes("je vais vous envoyer") ||
    blob.includes("je vous envoie le lien") ||
    blob.includes("je t'envoie le lien") ||
    blob.includes("lien d'inscription spécial") ||
    blob.includes("lien d'inscription special") ||
    blob.includes("telecharger l'application") ||
    blob.includes("télécharger l'application") ||
    blob.includes("telecharger l'app") ||
    blob.includes("télécharger l'app")
  );
}

const CM_REGISTRATION_LINK = "https://tinyurl.com/CMR056";

/** Short Chrome reminder only — not the long 05_registration text (also mentions Chrome). */
export function cmMtnTipSentInHistory(outgoingTexts: string[]): boolean {
  if (cmScriptSentInHistory(outgoingTexts, "07_mtn_tip")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("ne s'ouvre pas sur mtn") || blob.includes("ne s ouvre pas sur mtn");
}

export function cmChromeReminderSentInHistory(outgoingTexts: string[]): boolean {
  return outgoingTexts.some((line) => {
    const lower = line.toLowerCase().trim();
    if (!lower.includes("google chrome")) {
      return false;
    }
    // Registration script embeds "Google Chrome" + "colle" — exclude it.
    if (
      lower.includes("cash056") ||
      lower.includes("code promotionnel") ||
      lower.includes("lien d'inscription") ||
      lower.includes("cmr056") ||
      lower.length > 160
    ) {
      return false;
    }
    return (
      lower.includes("copiez ce lien") ||
      (lower.includes("colle") && lower.includes("navigateur"))
    );
  });
}

function canSendCmRegistration(
  tierSent: boolean,
  tierChoice: boolean,
  linkSent: boolean,
  outgoingTexts: string[],
  customerText = "",
): boolean {
  if (linkSent) {
    return false;
  }
  if (cmRegistrationInstructionsSentInHistory(outgoingTexts) && !regLinkSentInHistory(outgoingTexts)) {
    return true;
  }
  if (!tierSent) {
    return false;
  }
  if (tierChoice) {
    return true;
  }
  const t = customerText.trim();
  if (!t) {
    return false;
  }
  return (
    wantsRegistrationLink(t) ||
    isCmRegistrationHelpRequest(t) ||
    isRegistrationAccountQuestion(t) ||
    isReadyForRegistration(t) ||
    customerAgreedAfterOfferTable(t)
  );
}

/** After tier table: registration only once the client picked 1000 or 1500 CFA. */
function cmReadyForRegAfterTier(
  text: string,
  intent: CmIntent,
  tierSent: boolean,
  tierChoice: boolean,
  linkSent: boolean,
  _signal: boolean,
): boolean {
  if (!tierSent || linkSent) {
    return false;
  }
  if (tierChoice) {
    return true;
  }
  const t = text.trim();
  return (
    wantsRegistrationLink(t) ||
    isCmRegistrationHelpRequest(t) ||
    isRegistrationAccountQuestion(t) ||
    customerAgreedAfterOfferTable(t) ||
    intent === "ready"
  );
}

function cmRegBundleIfEligible(
  tierSent: boolean,
  tierChoice: boolean,
  linkSent: boolean,
  outgoingTexts: string[],
  customerText = "",
): string[] {
  return canSendCmRegistration(tierSent, tierChoice, linkSent, outgoingTexts, customerText)
    ? [...CM_REG_BUNDLE]
    : [];
}

function cmTierReminderIfNeeded(tierSent: boolean, tierChoice: boolean): string[] {
  if (tierSent && !tierChoice) {
    return ["04_tier"];
  }
  return [];
}

export function depositSentInHistory(outgoingTexts: string[]): boolean {
  if (cmScriptSentInHistory(outgoingTexts, "09_deposit")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("bouton vert") || blob.includes("déposer");
}

export function gameIdSentInHistory(outgoingTexts: string[]): boolean {
  if (cmScriptSentInHistory(outgoingTexts, "08_game_id")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("commence par 17") || blob.includes("numéro de joueur") || blob.includes("numero de joueur");
}

function stepForOutgoingText(text: string): number {
  const t = text.toLowerCase();
  if (t.includes("xtiy04zvcvw") || t.includes("t.me/+")) {
    return 9;
  }
  if (t.includes("canal telegram") && (t.includes("privé") || t.includes("prive"))) {
    return 8;
  }
  if (t.includes("bouton vert") || (t.includes("déposer") && t.includes("mtn"))) {
    return 7;
  }
  if (t.includes("commence par 17")) {
    return 6;
  }
  if (
    t.includes("cmr056") ||
    t.includes("camerun01") ||
    (t.includes("google chrome") && t.includes("colle"))
  ) {
    return 5;
  }
  if (t.includes("cash056")) {
    return 5;
  }
  if (t.includes("140 000 cfa") || t.includes("190 000 cfa") || t.includes("que vas-tu choisir")) {
    return 4;
  }
  if (
    t.includes("voici comment ça fonctionne") ||
    t.includes("voici comment ca fonctionne") ||
    t.includes("crée ton compte casino") ||
    t.includes("cree ton compte casino")
  ) {
    return 3;
  }
  if (t.includes("quel âge") || t.includes("quel age") || t.includes("age avez-vous")) {
    return 2;
  }
  if (t.includes("mon équipe cumule") || t.includes("mon equipe cumule")) {
    return 1;
  }
  if (t.includes("tu es du cameroun") || t.includes("cameroun")) {
    return 1;
  }
  return 0;
}

export function inferStepFromThread(messages: PagerMessage[]): number {
  let step = 0;
  for (const message of messages) {
    if (!isOutgoingDelivered(message)) {
      continue;
    }
    const text = (message.text || "").trim();
    if (!text) {
      continue;
    }
    step = Math.max(step, stepForOutgoingText(text));
  }
  return step;
}

export function funnelStepFromScriptGaps(
  outgoingTexts: string[],
  storedStep = 0,
): number {
  let step = Math.max(storedStep, 0);
  if (!scriptSentInHistory(outgoingTexts, scriptSnippet("01_intro"))) {
    return 0;
  }
  step = Math.max(step, 1);
  if (!cmScriptSentInHistory(outgoingTexts, "01_intro_3")) {
    return Math.min(step, 1);
  }
  if (!cmScriptSentInHistory(outgoingTexts, "02_age") && !ageQuestionSentInHistory(outgoingTexts)) {
    return Math.min(step, 1);
  }
  step = Math.max(step, 2);
  if (!stepsSentInHistory(outgoingTexts)) {
    return Math.min(step, 2);
  }
  if (!tierSentInHistory(outgoingTexts)) {
    return Math.min(step, 3);
  }
  if (!regLinkSentInHistory(outgoingTexts)) {
    return Math.min(step, 4);
  }
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

function positiveSignal(
  text: string,
  intent: CmIntent,
  effectiveStep: number,
): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

export function resolveCmFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: CmIntent,
  outgoingTexts: string[],
  options?: { hasImage?: boolean; messageReaction?: string; recentCustomerTexts?: string[] },
): string[] {
  const out = outgoingTexts;
  const t = (text || "").trim();
  const recentTexts = options?.recentCustomerTexts ?? [];
  const registrationHelp =
    isCmRegistrationHelpRequest(t) || isRegistrationAccountQuestion(t);

  if (intent === "declined") {
    return [];
  }

  const notRegisteredYet =
    isCustomerSaysNotRegisteredYet(t) || recentTextsIndicateNotRegistered(recentTexts);

  const introSent = cmScriptSentInHistory(out, "01_intro");
  const intro3Sent = cmScriptSentInHistory(out, "01_intro_3");
  const ageSent = cmScriptSentInHistory(out, "02_age") || ageQuestionSentInHistory(out);
  const stepsSent = stepsSentInHistory(out);
  const tierSent = tierSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const tierChoice =
    isDepositTierChoice(t) || recentTexts.some((line) => isDepositTierChoice(line));
  const signal = positiveSignal(t, intent, effectiveStep);

  if (notRegisteredYet) {
    if (!introSent) {
      return [...CM_INTRO_BUNDLE];
    }
    if (!intro3Sent) {
      return ["01_intro_3"];
    }
    if (!ageSent) {
      return ["02_age"];
    }
    if (!stepsSent) {
      return ["03_steps"];
    }
    if (!tierSent) {
      return ["04_tier"];
    }
    if (!linkSent) {
      return [...CM_REG_BUNDLE];
    }
    return registrationResendScriptKeys("CM", true);
  }

  if (registrationHelp) {
    if (regLinkSentInHistory(out)) {
      return ["06_link"];
    }
    const reg = cmRegBundleIfEligible(tierSent, tierChoice, linkSent, out, t);
    if (reg.length) {
      return reg;
    }
    const tierReminder = cmTierReminderIfNeeded(tierSent, tierChoice);
    if (tierReminder.length) {
      return tierReminder;
    }
    if (effectiveStep < 3) {
      if (!introSent) {
        return [...CM_INTRO_BUNDLE];
      }
      const remainingIntro = CM_INTRO_BUNDLE.filter((key) => !cmScriptSentInHistory(out, key));
      if (remainingIntro.length) {
        return [...remainingIntro];
      }
      if (!ageSent) {
        return ["02_age"];
      }
      if (!stepsSent) {
        return ["03_steps"];
      }
      if (!tierSent) {
        return ["04_tier"];
      }
      return [];
    }
    if (!tierSent && stepsSent) {
      return ["04_tier"];
    }
    return [];
  }

  if (wantsRegistrationLink(t)) {
    const reg = cmRegBundleIfEligible(tierSent, tierChoice, linkSent, out, t);
    if (reg.length) {
      return reg;
    }
    const tierReminder = cmTierReminderIfNeeded(tierSent, tierChoice);
    if (tierReminder.length) {
      return tierReminder;
    }
    if (stepsSent && !tierSent) {
      return ["04_tier"];
    }
    return [];
  }

  if (intent === "game_id_text") {
    if (depositSentInHistory(out) && !gameIdSentInHistory(out)) {
      return ["08_game_id"];
    }
    return [];
  }

  if (tierSent && tierChoice && !linkSent) {
    return [...CM_REG_BUNDLE];
  }

  if (cmReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
    return [...CM_REG_BUNDLE];
  }

  if (tierSent && tierChoice && !linkSent && isRegistrationAccountQuestion(t)) {
    return [...CM_REG_BUNDLE];
  }

  if (linkSent) {
    if (registrationHelp) {
      return ["06_link"];
    }
    if (isRegistrationBlocked(t)) {
      return ["06_link"];
    }
    if (
      (options?.hasImage || isRegistrationConfirmed(t) || intent === "image_only") &&
      !depositSentInHistory(out)
    ) {
      return ["09_deposit"];
    }
    if (isRegistrationConfirmed(t) && !depositSentInHistory(out)) {
      return ["09_deposit"];
    }
    if (
      !depositSentInHistory(out) &&
      (intent === "positive" ||
        intent === "ready" ||
        intent === "interested" ||
        isReadyForRegistration(t) ||
        isClientReadyPhrase(t))
    ) {
      return ["09_deposit"];
    }
    // Game ID only after clear deposit proof — never on bare Oui/Ok in old threads.
    if (
      depositSentInHistory(out) &&
      !gameIdSentInHistory(out) &&
      (intent === "deposit_done" ||
        intent === "image_only" ||
        options?.hasImage ||
        isRegistrationConfirmed(t))
    ) {
      return ["08_game_id"];
    }
    return [];
  }

  if (effectiveStep < 1) {
    if (!introSent) {
      if (
        ["interested", "positive", "ready", "question"].includes(intent) ||
        signal ||
        t.length > 0
      ) {
        return [...CM_INTRO_BUNDLE];
      }
      return [];
    }
    const remainingIntro = CM_INTRO_BUNDLE.filter((key) => !cmScriptSentInHistory(out, key));
    if (remainingIntro.length) {
      return [...remainingIntro];
    }
    return [];
  }

  if (effectiveStep < 2) {
    if (!ageSent) {
      if (
        ["interested", "positive", "ready", "question"].includes(intent) ||
        signal ||
        wantsDetailsAfterIntro(t) ||
        isClientReadyPhrase(t)
      ) {
        return ["02_age"];
      }
    } else if (!stepsSent) {
      if (
        isAgeAnswer(t) ||
        ["positive", "ready", "interested", "question"].includes(intent) ||
        signal ||
        wantsDetailsAfterIntro(t) ||
        isClientReadyPhrase(t) ||
        t.length > 0
      ) {
        return ["03_steps"];
      }
    }
    return [];
  }

  if (effectiveStep < 3) {
    if (!stepsSent) {
      if (
        isAgeAnswer(t) ||
        ["positive", "ready", "interested", "question"].includes(intent) ||
        signal ||
        wantsDetailsAfterIntro(t) ||
        wantsRegistrationLink(t) ||
        isClientReadyPhrase(t) ||
        t.length > 0
      ) {
        return ["03_steps"];
      }
    } else if (!tierSent) {
      if (
        ["positive", "ready", "interested", "question"].includes(intent) ||
        signal ||
        isReadyForRegistration(t) ||
        wantsDetailsAfterIntro(t) ||
        wantsRegistrationLink(t) ||
        isClientReadyPhrase(t) ||
        t.length > 0
      ) {
        return ["04_tier"];
      }
    }
    return [];
  }

  if (effectiveStep >= 4 && tierSent && !linkSent) {
    if (tierChoice || isDepositTierChoice(t)) {
      return [...CM_REG_BUNDLE];
    }
    if (
      wantsRegistrationLink(t) ||
      registrationHelp ||
      isReadyForRegistration(t) ||
      customerAgreedAfterOfferTable(t)
    ) {
      return [...CM_REG_BUNDLE];
    }
  }

  if (effectiveStep < 4) {
    if (tierChoice && tierSent && !linkSent) {
      return [...CM_REG_BUNDLE];
    }
    if (isCmProfitFigure(t) && !linkSent) {
      if (!tierSent) {
        return ["04_tier"];
      }
      if (!tierChoice) {
        return ["04_tier"];
      }
      return [...CM_REG_BUNDLE];
    }
    if (stepsSent && !tierSent) {
      if (
        ["positive", "ready", "interested", "question"].includes(intent) ||
        signal ||
        isReadyForRegistration(t) ||
        wantsDetailsAfterIntro(t) ||
        wantsRegistrationLink(t)
      ) {
        return ["04_tier"];
      }
    }
    if (tierSent && tierChoice && !linkSent) {
      return [...CM_REG_BUNDLE];
    }
    if (tierSent && !linkSent && t.length > 0 && t.length <= 24) {
      return ["04_tier"];
    }
    return [];
  }

  if (isRegistrationConfirmed(t) && linkSent) {
    if (!depositSentInHistory(out)) {
      return ["09_deposit"];
    }
    return [];
  }

  if (isRegistrationPending(t) && tierSent && tierChoice && !linkSent) {
    return [...CM_REG_BUNDLE];
  }

  if (effectiveStep < 7) {
    if (isRegistrationConfirmed(t) || intent === "joined") {
      if (!depositSentInHistory(out)) {
        return ["09_deposit"];
      }
      if (!gameIdSentInHistory(out)) {
        return ["08_game_id"];
      }
    }
    if (cmReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
      return [...CM_REG_BUNDLE];
    }
    if (canSendCmRegistration(tierSent, tierChoice, linkSent, out, t)) {
      return [...CM_REG_BUNDLE];
    }
    if (
      stepsSent &&
      !tierSent &&
      (signal ||
        intent === "interested" ||
        intent === "positive" ||
        intent === "ready" ||
        intent === "question" ||
        isReadyForRegistration(t) ||
        /\b(application|appli|lien|aide|explique|comment)\b/i.test(t))
    ) {
      return ["04_tier"];
    }
    if (linkSent && !depositSentInHistory(out) && (signal || options?.hasImage || intent === "ready" || intent === "positive" || isReadyForRegistration(t))) {
      return ["09_deposit"];
    }
    if (
      depositSentInHistory(out) &&
      !gameIdSentInHistory(out) &&
      (intent === "deposit_done" || intent === "image_only" || options?.hasImage || isRegistrationConfirmed(t))
    ) {
      return ["08_game_id"];
    }
    return [];
  }

  if (
    depositSentInHistory(out) &&
    !gameIdSentInHistory(out) &&
    (intent === "deposit_done" ||
      intent === "image_only" ||
      options?.hasImage ||
      isRegistrationConfirmed(t))
  ) {
    return ["08_game_id"];
  }

  if (
    !introSent &&
    (t.length > 0 || signal || intent === "interested" || intent === "question")
  ) {
    return [...CM_INTRO_BUNDLE];
  }
  const remainingIntro = CM_INTRO_BUNDLE.filter((key) => !cmScriptSentInHistory(out, key));
  if (remainingIntro.length) {
    return [...remainingIntro];
  }
  if (introSent && !ageSent && (t.length > 0 || signal)) {
    return ["02_age"];
  }
  if (ageSent && !stepsSent && (t.length > 0 || signal || isAgeAnswer(t))) {
    return ["03_steps"];
  }
  if (stepsSent && !tierSent && (t.length > 0 || signal)) {
    return ["04_tier"];
  }
  if (cmReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
    return [...CM_REG_BUNDLE];
  }

  return [];
}

export function classifyCmMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): CmIntent {
  return classifyCmIntent(text, options);
}

export function regSendTriggersInProgress(scriptKeys: string[]): boolean {
  return scriptKeys.includes("06_link") || scriptKeys.includes("07_chrome");
}

/** Move to «в процессе» once the registration link (or chrome reminder) went out. */
export function cmStatusMoveAfterSend(sentScriptKeys: string[]): boolean {
  return sentScriptKeys.includes("06_link") || sentScriptKeys.includes("07_chrome");
}

/** Intro pair and registration trio are multi-send; everything else is one script per customer turn. */
export function limitCmScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  const tierPending = scriptKeys.includes("04_tier");
  const regPending = scriptKeys.some((key) => CM_REG_SEND_KEYS.has(key));
  if (tierPending && regPending) {
    return tierSentInHistory(outgoingTexts) ? limitCmScriptsForCustomerTurn(
      scriptKeys.filter((key) => CM_REG_SEND_KEYS.has(key)),
      outgoingTexts,
    ) : ["04_tier"];
  }
  if (scriptKeys.some((key) => CM_INTRO_SEND_KEYS.has(key))) {
    const remaining = CM_INTRO_BUNDLE.filter((key) => !cmScriptSentInHistory(outgoingTexts, key));
    if (remaining.length) {
      return [...remaining];
    }
  }
  if (scriptKeys.some((key) => CM_REG_SEND_KEYS.has(key))) {
    const instructionsSent = cmRegistrationInstructionsSentInHistory(outgoingTexts);
    const linkSent = regLinkSentInHistory(outgoingTexts);

    // First reg turn: only instructions + link, then stop (folder move). No chrome/Wi‑Fi.
    const isInitialReg =
      scriptKeys.includes("05_registration") ||
      scriptKeys.includes("06_link") ||
      (!linkSent && scriptKeys.every((key) => CM_REG_SEND_KEYS.has(key)));
    if (!linkSent && isInitialReg) {
      if (!instructionsSent) {
        return [...CM_REG_BUNDLE];
      }
      return ["06_link"];
    }

    // Help / resend only — never auto-append Wi‑Fi tip.
    const remaining = scriptKeys.filter(
      (key) =>
        CM_REG_SEND_KEYS.has(key) &&
        key !== "07_mtn_tip" &&
        !cmScriptSentInHistory(outgoingTexts, key),
    );
    return remaining.length ? remaining : [];
  }
  return [scriptKeys[0]!];
}

export function cmAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return true;
  }
  return scriptKeys.some((key) => CM_REG_SEND_KEYS.has(key));
}

export { CM_REGISTRATION_LINK };

function isOutgoingDelivered(message: PagerMessage): boolean {
  const direction = (message.messageDirection || "").toLowerCase();
  if (direction !== "outgoing" && direction !== "out") {
    return false;
  }
  return Boolean(message.isDelivered || message.facebookMessageId);
}
