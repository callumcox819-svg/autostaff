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

export type MgIntent =
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

export const MG_CUSTOM_DEPOSIT_RULES: CustomDepositRules = {
  min: 500,
  max: 500_000,
  bareMin: 800,
  currencyPattern: /(?:\b(?:mga|ariary)\b)|(?:\d\s*(?:mga|ariary|ar)\b)|(?:^|[^a-z])ar(?:[^a-z]|$)/i,
  depositIntentPattern:
    /\b(deposit|depot|start with|begin with|invest|put in|with|can i start|want to start|ready to start|mets|mettre|investir|avec|pour|commencer|prefere|choisir|maintenant)\b/i,
};

/** JS `\b` breaks on accented French (é is non-word) — always match on folded text. */
function normalizeMgText(text: string): string {
  return (text || "")
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’']/g, "'")
    .replace(/\s+/g, " ");
}

const INTERESTED =
  /\b(interesse|interessé|ca m'interesse|cela m'interesse|dis[- ]moi|explique|je veux|j'aimerais|aimerais|en savoir plus|interested|tell me more|inscri)\b/i;
const POSITIVE =
  /\b(oui|ouais|ok|okay|okey|d'accord|daccord|dac|bien|super|parfait|merci|yes|yeah|yep|sure|continue|vas[- ]y)\b/i;
const READY =
  /\b(je suis pret|je suis prete|pret|prete|ready|on commence|allons[- ]y|je suis partant|c'est bon|j'aimerais inscri)\b/i;
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
  /\b(?:envoie|envoyer|envoyez|donne|donner|besoin|veux|veut|ou|recu|reçu|pas).{0,40}\b(?:lien|link)\b|\b(?:lien|link)\b.{0,28}\b(?:svp|s'il|sil|please|inscription|register|plateforme|pas|encore)\b|\blien\s+d['']inscription\b|\bpas (encore )?(recu|reçu|eu|avoir).{0,20}\b(lien|link)\b/i;
const REGISTRATION_HELP =
  /\b(code promo|quel code|quel promo|creer (le )?compte|comment (m')?inscri|comment s'inscri|prochaine etape|quoi faire)\b/i;

export function classifyMgIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): MgIntent {
  const raw = (text || "").trim();
  const t = normalizeMgText(raw);
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
  // Ordinal / amount pick from the offer table counts as a positive funnel turn.
  if (isMgOfferTableChoice(raw)) {
    return "positive";
  }
  return "unknown";
}

export function isFunnelPositiveReaction(text: string, _effectiveStep: number): boolean {
  const raw = (text || "").trim();
  const t = normalizeMgText(raw);
  return POSITIVE.test(t) || READY.test(t) || POSITIVE_EMOJI.test(raw) || INTERESTED.test(t);
}

export function isReadyForRegistration(text: string): boolean {
  const t = normalizeMgText(text);
  return (
    READY.test(t) ||
    customerAgreedAfterOfferTable(text) ||
    isMgDepositAmountChoice(text) ||
    /\b(pret|prete|ready|commencer|on y va|c'est parti)\b/i.test(t)
  );
}

export function isRegistrationConfirmed(text: string): boolean {
  const t = normalizeMgText(text);
  return (
    JOINED.test(t) ||
    /\b(deja inscrit|j'ai (fini|fait|inscrit|enregistr)|c'est (fait|bon)|je suis inscrit|termine)\b/i.test(t)
  );
}

export function isRegistrationHelpRequest(text: string): boolean {
  const t = normalizeMgText(text);
  return REGISTRATION_HELP.test(t) || customerRequestsRegistrationMaterials(text);
}

export function isMgRegistrationAccountQuestion(text: string): boolean {
  const raw = (text || "").trim();
  const t = normalizeMgText(raw);
  return (
    /\b(compte|account|inscription|register|email|e-mail|chrome|navigateur|code promo|mad778)\b/i.test(t) &&
    (/\?/.test(raw) || /\b(comment|aide|help|probleme)\b/i.test(t))
  );
}

export function isBarePostLinkAcknowledgment(text: string, intent: MgIntent): boolean {
  const t = normalizeMgText(text);
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
  const t = normalizeMgText(text);
  return (
    INTERESTED.test(t) ||
    POSITIVE.test(t) ||
    READY.test(t) ||
    /\b(detail|explique|comment|plus|suite|continue)\b/i.test(t)
  );
}

export function wantsRegistrationLink(text: string): boolean {
  const t = normalizeMgText(text);
  return FR_LINK_ASK.test(t) || customerRequestsRegistrationMaterials(text);
}

/** Pick from 03_mga_table: «Le premier», «2», «8000 MGA», «5000ar», etc. */
export function isMgOfferTableChoice(text: string): boolean {
  const raw = (text || "").trim();
  if (!raw) {
    return false;
  }
  // Same French ordinals as CM («Le premier», «le 2», …).
  if (isDepositTierChoice(raw)) {
    return true;
  }
  const t = normalizeMgText(raw);
  if (
    /^(le\s+)?(1|2|3|4|1er|1ere|2e|2eme|3e|3eme|4e|4eme|premier|premiere|deuxieme|second|troisieme|quatrieme)\.?$/i.test(
      t,
    )
  ) {
    return true;
  }
  if (
    /\b(le|la)\s+(1er|1ere|2e|2eme|3e|3eme|4e|4eme|premier|premiere|deuxieme|second|troisieme|quatrieme)\b/i.test(
      t,
    )
  ) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|je prefere|prefere|choisis|prends|celui|celle)\b/i.test(t) &&
    /(?:^|[^\d])(5000|4000|8000|15000|30000|1|2|3|4)(?:[^\d]|$)/i.test(t)
  ) {
    return true;
  }
  return isMgDepositAmountChoice(raw);
}

/** Table amounts: «5000 MGA», «5000ar», «8 000» — glued currency OK (JS `\b` breaks on 5000ar). */
export function isMgDepositAmountChoice(text: string): boolean {
  const folded = normalizeMgText(normalizeDepositText(text));
  if (!folded) {
    return false;
  }
  // Optional space before mga/ar/ariary; no word-boundary required after digits.
  const hasTableAmount =
    /(?:^|[^\d])(5\s*000|4\s*000|8\s*000|15\s*000|30\s*000|5000|4000|8000|15000|30000)(?:\s*(?:mga|ariary|ar))?(?![0-9])/i.test(
      folded,
    );
  if (hasTableAmount) {
    if (
      /(?:mga|ariary|(?:^|[^a-z])ar(?:[^a-z]|$))/i.test(folded) ||
      /(?:5000|4000|8000|15000|30000|5\s*000|4\s*000|8\s*000|15\s*000|30\s*000)\s*(?:mga|ariary|ar)/i.test(
        folded,
      ) ||
      /\b(deposit|depot|choisir|prefere|celui|celle|maintenant|veux|prends|prend|mets)\b/i.test(folded) ||
      folded.length < 56
    ) {
      return true;
    }
  }
  return isCustomMarketDepositAmount(text, MG_CUSTOM_DEPOSIT_RULES);
}

export { isCustomerSaysNotRegisteredYet };
