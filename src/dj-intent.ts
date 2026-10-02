import { isPositiveMessageReaction } from "./message-attachments.js";
import { isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";
import { isDepositTierChoice } from "./cm-intent.js";
import {
  customerAgreedAfterOfferTable,
  customerRequestsRegistrationMaterials,
} from "./funnel-common.js";
import {
  isCustomMarketDepositAmount,
  normalizeDepositText,
  type CustomDepositRules,
} from "./market-deposit-choice.js";

export type DjIntent =
  | "interested"
  | "positive"
  | "ready"
  | "question"
  | "declined"
  | "unknown"
  | "joined"
  | "deposit_done"
  | "game_id_text"
  | "image_only";

export const DJ_CUSTOM_DEPOSIT_RULES: CustomDepositRules = {
  min: 40,
  max: 500_000,
  bareMin: 40,
  currencyPattern: /(?:\b(?:djf|fdj)\b)|(?:\d\s*(?:djf|fdj)\b)/i,
  depositIntentPattern:
    /\b(deposit|depot|start with|begin with|invest|put in|with|can i start|want to start|ready to start|mets|mettre|investir|avec|pour|commencer|prefere|choisir|maintenant|demarrer|pret)\b/i,
};

/** JS `\b` breaks on accented French — always match on folded text. */
function normalizeDjText(text: string): string {
  return (text || "")
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’']/g, "'")
    .replace(/\s+/g, " ");
}

const INTERESTED =
  /\b(interesse|ca m'interesse|cela m'interesse|dis[- ]moi|explique|je veux|j'aimerais|aimerais|en savoir plus|interested|tell me more|inscri|pret|demarrer)\b/i;
const POSITIVE =
  /\b(oui|ouais|ok|okay|okey|d'accord|daccord|dac|bien|super|parfait|merci|yes|yeah|yep|sure|continue|vas[- ]y|choisis|je choisis)\b/i;
const READY =
  /\b(je suis pret|je suis prete|pret|prete|ready|on commence|allons[- ]y|je suis partant|c'est bon|j'aimerais inscri|demarrer|je demarre)\b/i;
const GREETING = /^(salut|bonjour|bonsoir|hey|hello|hi|yo)([\s,!.]|$)/i;
const JOINED =
  /\b(je me suis inscrit|inscrit|inscription (faite|terminee|termine)|j'ai cree|j ai cree|account created|registered)\b/i;
const DECLINED = /\b(pas interesse|non merci|stop|arnaque|scam|laisse[- ]moi)\b/i;
const BARE_DECLINED = /^(non|nah|nope|jamais|rien|non merci)\.?!*$/i;
const DEPOSIT_DONE =
  /\b(j'ai (fait|depose)|depot (fait|termine)|deposit done|deposited|apres (le )?depot)\b/i;
const GAME_ID = /\b(17\d{6,}|16\d{6,}|identifiant\s*\d+|id\s*\d+)\b/i;
const POSITIVE_EMOJI = /^[\s👍👌✅🔥❤️🙏😊🙂]+$/u;
const FR_LINK_ASK =
  /\b(?:envoie|envoyer|envoyez|donne|donner|besoin|veux|veut|ou|recu|pas).{0,40}\b(?:lien|link)\b|\b(?:lien|link)\b.{0,28}\b(?:svp|s'il|sil|please|inscription|register|plateforme|pas|encore)\b|\blien\s+d['']inscription\b|\bpas (encore )?(recu|eu|avoir).{0,20}\b(lien|link)\b/i;
const REGISTRATION_HELP =
  /\b(code promo|quel code|quel promo|creer (le )?compte|comment (m')?inscri|comment s'inscri|prochaine etape|quoi faire|bji777)\b/i;

export function classifyDjIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): DjIntent {
  const raw = (text || "").trim();
  const t = normalizeDjText(raw);
  if (!t && options?.hasImage) {
    return "image_only";
  }
  if (!t) {
    if (isPositiveMessageReaction(options?.messageReaction)) {
      return "positive";
    }
    return "unknown";
  }
  if (BARE_DECLINED.test(t) || DECLINED.test(t)) {
    return "declined";
  }
  if (GAME_ID.test(t)) {
    return "game_id_text";
  }
  if (DEPOSIT_DONE.test(t)) {
    return "deposit_done";
  }
  if (JOINED.test(t)) {
    return "joined";
  }
  if (READY.test(t)) {
    return "ready";
  }
  if (INTERESTED.test(t)) {
    return "interested";
  }
  if (POSITIVE.test(t) || POSITIVE_EMOJI.test(raw) || isPositiveMessageReaction(options?.messageReaction)) {
    return "positive";
  }
  if (/\?/.test(raw) || /^(comment|pourquoi|c'est quoi|cest quoi|quoi)/i.test(t)) {
    return "question";
  }
  if (GREETING.test(t)) {
    return "interested";
  }
  if (isDjOfferTableChoice(raw)) {
    return "positive";
  }
  return "unknown";
}

export function isFunnelPositiveReaction(text: string, _effectiveStep: number): boolean {
  const raw = (text || "").trim();
  const t = normalizeDjText(raw);
  return POSITIVE.test(t) || READY.test(t) || POSITIVE_EMOJI.test(raw) || INTERESTED.test(t);
}

export function isReadyForRegistration(text: string): boolean {
  const t = normalizeDjText(text);
  return (
    READY.test(t) ||
    customerAgreedAfterOfferTable(text) ||
    isDjDepositAmountChoice(text) ||
    /\b(pret|prete|ready|commencer|demarrer|on y va|c'est parti|300\s*djf)\b/i.test(t)
  );
}

export function isRegistrationConfirmed(text: string): boolean {
  const t = normalizeDjText(text);
  return (
    JOINED.test(t) ||
    /\b(deja inscrit|j'ai (fini|fait|inscrit|enregistr)|c'est (fait|bon)|je suis inscrit|termine)\b/i.test(t)
  );
}

export function isRegistrationHelpRequest(text: string): boolean {
  const t = normalizeDjText(text);
  return REGISTRATION_HELP.test(t) || customerRequestsRegistrationMaterials(text);
}

export function isDjRegistrationAccountQuestion(text: string): boolean {
  const raw = (text || "").trim();
  const t = normalizeDjText(raw);
  return (
    /\b(compte|account|inscription|register|email|e-mail|chrome|navigateur|code promo|bji777)\b/i.test(t) &&
    (/\?/.test(raw) || /\b(comment|aide|help|probleme)\b/i.test(t))
  );
}

export function isBarePostLinkAcknowledgment(text: string, intent: DjIntent): boolean {
  const t = normalizeDjText(text);
  if (!t) {
    return false;
  }
  if (intent === "declined" || intent === "joined" || intent === "deposit_done" || intent === "game_id_text") {
    return false;
  }
  return /^(ok|okay|okey|oui|d'accord|daccord|merci|thanks|thank you|super|parfait|hum+|hm+|mhm+)[.!\s]*$/i.test(
    t,
  );
}

export function wantsDetailsAfterIntro(text: string): boolean {
  const t = normalizeDjText(text);
  return (
    INTERESTED.test(t) ||
    POSITIVE.test(t) ||
    READY.test(t) ||
    /\b(detail|explique|comment|plus|suite|continue)\b/i.test(t)
  );
}

export function wantsRegistrationLink(text: string): boolean {
  const t = normalizeDjText(text);
  return FR_LINK_ASK.test(t) || customerRequestsRegistrationMaterials(text);
}

/** Table / ready-ask picks: «100 DJF», «Le premier», «300», «oui». */
export function isDjOfferTableChoice(text: string): boolean {
  const raw = (text || "").trim();
  if (!raw) {
    return false;
  }
  if (isDepositTierChoice(raw)) {
    return true;
  }
  const t = normalizeDjText(raw);
  if (
    /^(le\s+)?(1|2|3|4|1er|1ere|2e|2eme|3e|3eme|4e|4eme|premier|premiere|deuxieme|second|troisieme|quatrieme)\.?$/i.test(
      t,
    )
  ) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|je prefere|prefere|choisis|prends|celui|celle)\b/i.test(t) &&
    /(?:^|[^\d])(100|200|300|500|1000|1|2|3|4)(?:[^\d]|$)/i.test(t)
  ) {
    return true;
  }
  return isDjDepositAmountChoice(raw);
}

export function isDjDepositAmountChoice(text: string): boolean {
  const folded = normalizeDjText(normalizeDepositText(text));
  if (!folded) {
    return false;
  }
  const hasTableAmount =
    /(?:^|[^\d])(100|200|300|500|1000|1\s*000)(?:\s*(?:djf|fdj))?(?![0-9])/i.test(folded);
  if (hasTableAmount) {
    if (
      /\b(djf|fdj)\b/i.test(folded) ||
      /(?:100|200|300|500|1000)\s*(?:djf|fdj)/i.test(folded) ||
      /\b(deposit|depot|choisir|prefere|celui|celle|maintenant|veux|prends|demarrer|pret)\b/i.test(
        folded,
      ) ||
      folded.length < 56
    ) {
      return true;
    }
  }
  return isCustomMarketDepositAmount(text, DJ_CUSTOM_DEPOSIT_RULES);
}

export { isCustomerSaysNotRegisteredYet };
