import type { PagerMessage } from "./pager-client.js";
import {
  isCustomerSaysNotRegisteredYet,
  recentTextsIndicateNotRegistered,
} from "./customer-clarity.js";
import { registrationResendScriptKeys, customerAgreedAfterOfferTable } from "./funnel-common.js";
import {
  type ClIntent,
  classifyClIntent,
  isAgeAnswer,
  isRegistrationBlocked,
  isClientReadyPhrase,
  isDepositTierChoice,
  isFunnelPositiveReaction,
  isClProfitFigure,
  isClRegistrationHelpRequest,
  isReadyForRegistration,
  isRegistrationAccountQuestion,
  isRegistrationConfirmed,
  isRegistrationPending,
  wantsDetailsAfterIntro,
  wantsRegistrationLink,
} from "./cl-intent.js";

export const CL_SCRIPT_SNIPPETS: Record<string, string> = {
  "01_intro": "Eres de Chile",
  "01_intro_2": "Mon équipe cumule",
  "02_age": "Quel âge",
  "03_steps": "voici comment ça fonctionne",
  "04_tier": "825 CLP",
  "05_registration": "CLE577",
  "06_link": "CLE333",
  "07_chrome": "Google Chrome",
  "08_game_id": "commence par 17",
  "09_deposit": "bouton vert",
  "10_tg_invite": "canal Telegram privé",
  "11_tg_link": "XtIY04zvcVw2YzZi",
};

export const CL_SCRIPT_SEARCH_NEEDLES: Record<string, string[]> = {
  "01_intro": [
    "tu es du chili",
    "eres de chile",
    "are you from chile",
    "bonjour ! tu es du chili",
  ],
  "01_intro_2": [
    "mon équipe cumule",
    "mi equipo suma",
    "my team has years",
    "gagner ensemble",
    "ganar juntos",
    "win together",
  ],
  "02_age": [
    "quel âge",
    "quel age",
    "cuántos años",
    "cuantos anos",
    "how old are you",
  ],
  "03_steps": [
    "voici comment ça fonctionne",
    "así funciona",
    "here's how it works",
    "crée ton compte casino",
    "crea tu cuenta",
    "create your casino account",
    "dépôt minimum",
    "depósito mínimo",
  ],
  "04_tier": [
    "825 clp",
    "8250 clp",
    "1 320 clp",
    "1320 clp",
    "13 200 clp",
    "13200 clp",
    "16 500 clp",
    "16500 clp",
    "22 400 clp",
    "22400 clp",
    "1 650 clp",
    "1650 clp",
    "2 500 clp",
    "que vas-tu choisir",
    "qué vas a elegir",
    "what will you choose",
    "voici ce que tu peux obtenir",
    "esto es lo que puedes obtener",
  ],
  "05_registration": [
    "je vous envoie le lien",
    "te envío el enlace",
    "i'm sending you the link",
    "télécharger l'application",
    "descargar la aplicación",
    "download the app",
    "cle577",
  ],
  "06_link": ["cle333", "tinyurl.com/cle"],
  "07_chrome": ["copiez ce lien", "copia este enlace", "copy this link"],
  "08_game_id": ["commence par 17", "empieza por 17", "starts with 17", "numéro de joueur"],
  "09_deposit": ["bouton vert", "déposer", "deposit", "depositar", "depósito"],
  "10_tg_invite": ["canal telegram privé", "canal telegram prive"],
  "11_tg_link": ["xtiy04zvcvw", "t.me/"],
};

export const CL_SCRIPT_EXCLUDE_SNIPPETS: Record<string, string[]> = {
  "05_registration": ["voici comment ça fonctionne", "así funciona", "here's how it works"],
  "06_link": ["voici comment ça fonctionne", "así funciona"],
  "07_chrome": ["voici comment ça fonctionne", "que vas-tu choisir"],
  "03_steps": ["cle333", "cle577", "google chrome"],
  "04_tier": ["cle333", "cle577", "google chrome"],
};

export const CL_FOLDER_NAME_HINTS = ["chile", "chili", "чili", "cl"];

export const CL_REG_SEND_KEYS = new Set(["05_registration", "06_link", "07_chrome"]);
export const CL_INTRO_SEND_KEYS = new Set(["01_intro", "01_intro_2"]);

const CL_REG_BUNDLE = ["05_registration", "06_link", "07_chrome"] as const;

export function scriptSnippet(key: string): string {
  return CL_SCRIPT_SNIPPETS[key] ?? "";
}

export function scriptSearchNeedles(key: string): string[] {
  return CL_SCRIPT_SEARCH_NEEDLES[key] ?? [scriptSnippet(key)].filter(Boolean);
}

export function clScriptSentInHistory(outgoingTexts: string[], scriptKey: string): boolean {
  if (scriptKey === "01_intro_2") {
    const blob = outgoingTexts.join("\n").toLowerCase();
    if (blob.includes("mon équipe") || blob.includes("mon equipe")) {
      return true;
    }
  }
  if (scriptKey === "04_tier") {
    return tierSentInHistory(outgoingTexts);
  }
  if (scriptKey === "05_registration") {
    return clRegistrationInstructionsSentInHistory(outgoingTexts);
  }
  return scriptSearchNeedles(scriptKey).some((needle) => scriptSentInHistory(outgoingTexts, needle));
}

export function tierSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    blob.includes("825 clp") ||
    blob.includes("8250 clp") ||
    blob.includes("1 320 clp") ||
    blob.includes("1320 clp") ||
    blob.includes("13 200 clp") ||
    blob.includes("13200 clp") ||
    blob.includes("16 500 clp") ||
    blob.includes("16500 clp") ||
    blob.includes("22 400 clp") ||
    blob.includes("22400 clp") ||
    blob.includes("1 650 clp") ||
    blob.includes("1650 clp") ||
    blob.includes("2 500 clp") ||
    blob.includes("1.650 clp") ||
    blob.includes("que vas-tu choisir") ||
    blob.includes("qué vas a elegir") ||
    blob.includes("what will you choose") ||
    blob.includes("voici ce que tu peux obtenir") ||
    blob.includes("esto es lo que puedes obtener") ||
    blob.includes("here's what you can get") ||
    blob.includes("investissement → gain") ||
    blob.includes("investissement -> gain") ||
    blob.includes("obtenir avec mon aide")
  );
}

export function stepsSentInHistory(outgoingTexts: string[]): boolean {
  return clScriptSentInHistory(outgoingTexts, "03_steps");
}

function ageQuestionSentInHistory(outgoingTexts: string[]): boolean {
  if (clScriptSentInHistory(outgoingTexts, "02_age")) {
    return true;
  }
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

export function clAgeQuestionSentInHistory(outgoingTexts: string[]): boolean {
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
  if (clScriptSentInHistory(outgoingTexts, "06_link")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("cle333") || blob.includes("tinyurl.com/cle");
}

export function clRegistrationInstructionsSentInHistory(outgoingTexts: string[]): boolean {
  const blob = outgoingTexts.join("\n").toLowerCase();
  return (
    (blob.includes("je vous envoie le lien") ||
      blob.includes("je t'envoie le lien") ||
      blob.includes("te envío el enlace") ||
      blob.includes("i'm sending you the link") ||
      blob.includes("telecharger l'application") ||
      blob.includes("télécharger l'application") ||
      blob.includes("descargar la aplicación") ||
      blob.includes("download the app") ||
      blob.includes("telecharger l'app") ||
      blob.includes("télécharger l'app")) &&
    blob.includes("cle577")
  );
}

const CL_REGISTRATION_LINK = "https://tinyurl.com/CLE333";

export function clChromeReminderSentInHistory(outgoingTexts: string[]): boolean {
  return outgoingTexts.some((line) => {
    const lower = line.toLowerCase().trim();
    if (
      lower.includes("cle577") ||
      lower.includes("cle333") ||
      lower.includes("lien d'inscription") ||
      lower.includes("registration link") ||
      lower.includes("enlace de registro") ||
      lower.length > 160
    ) {
      return false;
    }
    return (
      lower.includes("copiez ce lien") ||
      lower.includes("copia este enlace") ||
      lower.includes("copy this link") ||
      (lower.includes("google chrome") &&
        (lower.includes("colle") || lower.includes("paste") || lower.includes("pega")))
    );
  });
}

function canSendClRegistration(
  tierSent: boolean,
  tierChoice: boolean,
  linkSent: boolean,
  outgoingTexts: string[],
  customerText = "",
): boolean {
  if (linkSent) {
    return false;
  }
  if (clRegistrationInstructionsSentInHistory(outgoingTexts) && !regLinkSentInHistory(outgoingTexts)) {
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
    isClRegistrationHelpRequest(t) ||
    isRegistrationAccountQuestion(t) ||
    isReadyForRegistration(t) ||
    isDepositTierChoice(t) ||
    customerAgreedAfterOfferTable(t)
  );
}

/** After tier table: registration only once the client picked 1000 or 1500 CFA. */
function clReadyForRegAfterTier(
  text: string,
  intent: ClIntent,
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
    isClRegistrationHelpRequest(t) ||
    isRegistrationAccountQuestion(t) ||
    isDepositTierChoice(t) ||
    customerAgreedAfterOfferTable(t) ||
    intent === "ready"
  );
}

function clRegBundleIfEligible(
  tierSent: boolean,
  tierChoice: boolean,
  linkSent: boolean,
  outgoingTexts: string[],
  customerText = "",
): string[] {
  return canSendClRegistration(tierSent, tierChoice, linkSent, outgoingTexts, customerText)
    ? [...CL_REG_BUNDLE]
    : [];
}

function clTierReminderIfNeeded(tierSent: boolean, tierChoice: boolean): string[] {
  if (tierSent && !tierChoice) {
    return ["04_tier"];
  }
  return [];
}

export function depositSentInHistory(outgoingTexts: string[]): boolean {
  if (clScriptSentInHistory(outgoingTexts, "09_deposit")) {
    return true;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  return blob.includes("bouton vert") || blob.includes("déposer");
}

export function gameIdSentInHistory(outgoingTexts: string[]): boolean {
  if (clScriptSentInHistory(outgoingTexts, "08_game_id")) {
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
  if (t.includes("cle577") || t.includes("cle333") || (t.includes("google chrome") && t.includes("colle"))) {
    return 5;
  }
  if (t.includes("cash056")) {
    return 5;
  }
  if (
    t.includes("16 500 clp") ||
    t.includes("16500 clp") ||
    t.includes("1 650 clp") ||
    t.includes("que vas-tu choisir")
  ) {
    return 4;
  }
  if (
    t.includes("voici comment ça fonctionne") ||
    t.includes("voici comment ca fonctionne") ||
    t.includes("así funciona") ||
    t.includes("asi funciona") ||
    t.includes("here's how it works") ||
    t.includes("heres how it works") ||
    t.includes("crée ton compte casino") ||
    t.includes("cree ton compte casino") ||
    t.includes("crea tu cuenta") ||
    t.includes("create your casino account")
  ) {
    return 3;
  }
  if (
    t.includes("quel âge") ||
    t.includes("quel age") ||
    t.includes("cuántos años") ||
    t.includes("cuantos anos") ||
    t.includes("how old are you")
  ) {
    return 2;
  }
  if (t.includes("mon équipe cumule") || t.includes("mon equipe cumule") || t.includes("mi equipo suma")) {
    return 1;
  }
  if (t.includes("eres de chile") || t.includes("are you from chile") || t.includes("tu es du chili")) {
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
  if (!clScriptSentInHistory(outgoingTexts, "01_intro_2")) {
    return Math.min(step, 1);
  }
  if (!clScriptSentInHistory(outgoingTexts, "02_age") && !ageQuestionSentInHistory(outgoingTexts)) {
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
  intent: ClIntent,
  effectiveStep: number,
): boolean {
  return (
    isFunnelPositiveReaction(text, effectiveStep) ||
    intent === "positive" ||
    intent === "ready" ||
    intent === "interested"
  );
}

export function resolveClFunnelScripts(
  effectiveStep: number,
  text: string,
  intent: ClIntent,
  outgoingTexts: string[],
  options?: { hasImage?: boolean; messageReaction?: string; recentCustomerTexts?: string[] },
): string[] {
  const out = outgoingTexts;
  const t = (text || "").trim();
  const recentTexts = options?.recentCustomerTexts ?? [];
  const registrationHelp =
    isClRegistrationHelpRequest(t) || isRegistrationAccountQuestion(t);

  if (intent === "declined") {
    return [];
  }

  const notRegisteredYet =
    isCustomerSaysNotRegisteredYet(t) || recentTextsIndicateNotRegistered(recentTexts);

  const introSent = clScriptSentInHistory(out, "01_intro");
  const intro2Sent = clScriptSentInHistory(out, "01_intro_2");
  const ageSent = clScriptSentInHistory(out, "02_age") || ageQuestionSentInHistory(out);
  const stepsSent = stepsSentInHistory(out);
  const tierSent = tierSentInHistory(out);
  const linkSent = regLinkSentInHistory(out);
  const tierChoice =
    isDepositTierChoice(t) || recentTexts.some((line) => isDepositTierChoice(line));
  const signal = positiveSignal(t, intent, effectiveStep);

  if (notRegisteredYet) {
    if (!introSent) {
      return ["01_intro", "01_intro_2"];
    }
    if (!intro2Sent) {
      return ["01_intro_2"];
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
      return [...CL_REG_BUNDLE];
    }
    return registrationResendScriptKeys("CM", true);
  }

  if (registrationHelp) {
    if (regLinkSentInHistory(out) && !clChromeReminderSentInHistory(out)) {
      return ["07_chrome"];
    }
    if (regLinkSentInHistory(out)) {
      return ["07_chrome", "06_link"];
    }
    const reg = clRegBundleIfEligible(tierSent, tierChoice, linkSent, out, t);
    if (reg.length) {
      return reg;
    }
    const tierReminder = clTierReminderIfNeeded(tierSent, tierChoice);
    if (tierReminder.length) {
      return tierReminder;
    }
    if (effectiveStep < 3) {
      if (!introSent) {
        return ["01_intro", "01_intro_2"];
      }
      if (!intro2Sent) {
        return ["01_intro_2"];
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
    const reg = clRegBundleIfEligible(tierSent, tierChoice, linkSent, out, t);
    if (reg.length) {
      return reg;
    }
    const tierReminder = clTierReminderIfNeeded(tierSent, tierChoice);
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
    return [...CL_REG_BUNDLE];
  }

  if (clReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
    return [...CL_REG_BUNDLE];
  }

  if (tierSent && tierChoice && !linkSent && isRegistrationAccountQuestion(t)) {
    return [...CL_REG_BUNDLE];
  }

  if (linkSent) {
    if (registrationHelp) {
      return ["07_chrome", "06_link"];
    }
    if (isRegistrationBlocked(t)) {
      return ["07_chrome", "06_link"];
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
        return ["01_intro", "01_intro_2"];
      }
      return [];
    }
    if (introSent && !intro2Sent) {
      return ["01_intro_2"];
    }
    return [];
  }

  if (effectiveStep < 2) {
    if (!ageSent) {
      if (
        ["interested", "positive", "ready", "question"].includes(intent) ||
        signal ||
        wantsDetailsAfterIntro(t) ||
        isClientReadyPhrase(t) ||
        t.length > 0
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
      return [...CL_REG_BUNDLE];
    }
    if (
      wantsRegistrationLink(t) ||
      registrationHelp ||
      isReadyForRegistration(t) ||
      customerAgreedAfterOfferTable(t)
    ) {
      return [...CL_REG_BUNDLE];
    }
  }

  if (effectiveStep < 4) {
    if (tierChoice && tierSent && !linkSent) {
      return [...CL_REG_BUNDLE];
    }
    if (isClProfitFigure(t) && !linkSent) {
      if (!tierSent) {
        return ["04_tier"];
      }
      if (!tierChoice) {
        return ["04_tier"];
      }
      return [...CL_REG_BUNDLE];
    }
    if (stepsSent && !tierSent) {
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
    if (tierSent && tierChoice && !linkSent) {
      return [...CL_REG_BUNDLE];
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
    return [...CL_REG_BUNDLE];
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
    if (clReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
      return [...CL_REG_BUNDLE];
    }
    if (canSendClRegistration(tierSent, tierChoice, linkSent, out, t)) {
      return [...CL_REG_BUNDLE];
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
    return ["01_intro", "01_intro_2"];
  }
  if (introSent && !intro2Sent) {
    return ["01_intro_2"];
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
  if (clReadyForRegAfterTier(t, intent, tierSent, tierChoice, linkSent, signal)) {
    return [...CL_REG_BUNDLE];
  }

  return [];
}

export function classifyClMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): ClIntent {
  return classifyClIntent(text, options);
}

export function regSendTriggersInProgress(scriptKeys: string[]): boolean {
  return scriptKeys.includes("06_link") || scriptKeys.includes("07_chrome");
}

export function clStatusMoveAfterSend(sentScriptKeys: string[]): boolean {
  return sentScriptKeys.includes("06_link") || sentScriptKeys.includes("07_chrome");
}

/** Intro pair and registration trio are multi-send; everything else is one script per customer turn. */
export function limitClScriptsForCustomerTurn(
  scriptKeys: string[],
  outgoingTexts: string[],
): string[] {
  if (!scriptKeys.length) {
    return scriptKeys;
  }
  const tierPending = scriptKeys.includes("04_tier");
  const regPending = scriptKeys.some((key) => CL_REG_SEND_KEYS.has(key));
  if (tierPending && regPending) {
    return tierSentInHistory(outgoingTexts) ? limitClScriptsForCustomerTurn(
      scriptKeys.filter((key) => CL_REG_SEND_KEYS.has(key)),
      outgoingTexts,
    ) : ["04_tier"];
  }
  if (
    scriptKeys.includes("01_intro") &&
    !clScriptSentInHistory(outgoingTexts, "01_intro")
  ) {
    return scriptKeys.filter((key) => key === "01_intro" || key === "01_intro_2");
  }
  if (scriptKeys.some((key) => CL_REG_SEND_KEYS.has(key))) {
    const instructionsSent = clRegistrationInstructionsSentInHistory(outgoingTexts);
    const linkSent = regLinkSentInHistory(outgoingTexts);
    const chromeSent = clChromeReminderSentInHistory(outgoingTexts);

    if (!instructionsSent) {
      return [...CL_REG_BUNDLE];
    }
    const remaining: string[] = [];
    if (!linkSent) {
      remaining.push("06_link");
    }
    if (!chromeSent) {
      remaining.push("07_chrome");
    }
    if (remaining.length) {
      return remaining;
    }
    if (scriptKeys.includes("06_link")) {
      return scriptKeys.filter((key) => key === "06_link" || key === "07_chrome");
    }
    return [];
  }
  return [scriptKeys[0]!];
}

export function clAllowsMultiSend(scriptKeys: string[]): boolean {
  if (scriptKeys.includes("01_intro")) {
    return true;
  }
  return scriptKeys.some((key) => CL_REG_SEND_KEYS.has(key));
}

export { CL_REGISTRATION_LINK };

function isOutgoingDelivered(message: PagerMessage): boolean {
  const direction = (message.messageDirection || "").toLowerCase();
  if (direction !== "outgoing" && direction !== "out") {
    return false;
  }
  return Boolean(message.isDelivered || message.facebookMessageId);
}
