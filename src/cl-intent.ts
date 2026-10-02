import { isPositiveMessageReaction } from "./message-attachments.js";
import { isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";
import {
  CL_CUSTOM_DEPOSIT_RULES,
  isCustomMarketDepositAmount,
  normalizeDepositText,
} from "./market-deposit-choice.js";

export type ClIntent =
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

const FR_POSITIVE =
  /\b(oui|ok|okay|d'accord|dac|dacc|bien|super|parfait|merci|yes|yeah|yep)\b/i;
const FR_GREETING =
  /^(bonjour|bonsoir|salut|saluu+t|bjr|slt|hello|hi)([\s,!.]|$)/i;
const ES_INTERESTED =
  /\b(hola|me interesa|estoy interesad|interesado|interesada|te hablo|quiero saber|como funciona|necesito ayuda|trabajo|publicacion)\b/i;
const EN_INTERESTED =
  /\b(i'm interested|i am interested|good (morning|afternoon|evening)|need help|how does|tell me|this work|interested in)\b/i;
const FR_INTERESTED =
  /\b(je veux|interesse|interesse|interessee|interessee|m'interesse|ca m'interesse|comment|explique|details|details|investir|gagner|j[' ]?ai vu votre publication|jai vu votre publication|j[' ]?ai vu votre pub|jai vu votre pub|publication|je suis interesse|suis interesse|commen[cç]ons|vous voulez m'aide|veux m'aide|m'aider|aidez[- ]?moi|besoin d'aide)\b/i;
const FR_DECLINED =
  /\b(pas intéressé|pas interesse|je ne suis pas intéressé|non merci|stop|arrête|arnaque|escroc|nigerian)\b|^non[.!]?$/i;
const FR_REG_DONE =
  /(déjà|deja).{0,32}(connect|inscription|inscrit|enregistr|1xbet)|je me suis deja connecte|je me suis inscrit|compte.{0,16}(ouvert|créé|cree)|j[' ]?ai (fini|créé|cree).{0,16}(inscription|compte)|c[' ]?est bon j[' ]?ai (créé|cree)|j[' ]?ai (créé|cree)\b/i;
const FR_REG_PENDING =
  /\b(pas encore|pas fini|je m'inscris|j['']?inscris|en cours)\b/i;
const POSITIVE_EMOJI = /[👍👌✅🔥❤️🙏😊🙂]/;
const FR_LINK_BROKEN =
  /\b(sa marche pas|ca marche pas|ne marche pas|marche pas|ne fonctionne pas|fonctionne pas|pas pu telecharger|pas pui telecharger|probleme de lien|lien.*pas|telecharg\w*.*pas)\b/i;
const FR_HAS_ACCOUNT_OR_APP =
  /\b(j'ai l'application|jai l'application|j'ai un compte|jai un compte|avec un compte|application deja|deja un compte|compte deja cree)\b/i;

export function classifyClIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): ClIntent {
  const t = (text || "").trim();
  const normalized = normalizeFrText(text);
  const step = options?.funnelStep ?? 0;

  if (isCustomerSaysNotRegisteredYet(t) || isCustomerSaysNotRegisteredYet(normalized)) {
    return "question";
  }
  if (FR_DECLINED.test(t) || /nigerian|scam|arnaque|escroc/i.test(t)) {
    return "declined";
  }
  if (isClientReadyPhrase(t)) {
    return "ready";
  }
  if (isAgeAnswer(t) && step >= 1 && step < 5) {
    return "positive";
  }
  if (isDepositTierChoice(t)) {
    return "ready";
  }
  if (FR_REG_DONE.test(t) || FR_REG_DONE.test(normalized)) {
    return "positive";
  }
  if (FR_REG_PENDING.test(t) || FR_REG_PENDING.test(normalized)) {
    return "ready";
  }
  if (wantsRegistrationLink(t)) {
    return "ready";
  }
  if (isRegistrationAccountQuestion(t) || isClRegistrationHelpRequest(t)) {
    return "ready";
  }
  if (!t && isPositiveMessageReaction(options?.messageReaction)) {
    return "positive";
  }
  if (!t && options?.hasImage) {
    return step < 5 ? "positive" : "image_only";
  }
  if (POSITIVE_EMOJI.test(t) && t.length <= 4) {
    return "positive";
  }
  if (FR_INTERESTED.test(t) || FR_INTERESTED.test(normalized)) {
    return "interested";
  }
  if (ES_INTERESTED.test(t) || ES_INTERESTED.test(normalized)) {
    return "interested";
  }
  if (EN_INTERESTED.test(t) || EN_INTERESTED.test(normalized)) {
    return "interested";
  }
  if (FR_GREETING.test(t) || FR_GREETING.test(normalized)) {
    return step < 2 ? "interested" : "positive";
  }
  if (
    /\b(je suis a l'ecoute|je suis a l ecoute|a l'ecoute|je vous ecoute|je t'ecoute)\b/i.test(
      normalized,
    )
  ) {
    return "positive";
  }
  if (/\bje suis (au|du) cameroun\b|\b(au|du) cameroun\b/i.test(normalized)) {
    return "positive";
  }
  if (isProfitFigure(normalized)) {
    return step >= 3 ? "positive" : "interested";
  }
  if (/\boui\b/i.test(t) && step < 4) {
    return "positive";
  }
  if (/^(si|sí|claro|por supuesto|lista|listo|dale|bueno|genial|perfecto)\.?$/i.test(t)) {
    return "positive";
  }
  if (
    /\b(si|claro|por supuesto|listo|lista|dale|bueno|genial|perfecto|de acuerdo)\b/i.test(t) &&
    t.split(/\s+/).length <= 12
  ) {
    return "positive";
  }
  if (/\b(soy chileno|soy de chile|yo soy chileno)\b/i.test(t)) {
    return step < 2 ? "interested" : "positive";
  }
  if (/\b(no entiendo|explicame|explícame|explicame mas)\b/i.test(t)) {
    return "question";
  }
  if (FR_POSITIVE.test(t) && t.split(/\s+/).length <= 8) {
    return "positive";
  }
  if (/\b(ok|okay|vale|listo|de acuerdo|entendido)\b/i.test(t) && t.split(/\s+/).length <= 16) {
    return "positive";
  }
  if (/\?/.test(t) || /\b(comment|pourquoi|combien|quoi|what|how)\b/i.test(t)) {
    return "question";
  }
  if (options?.hasImage && !t) {
    return step < 5 ? "positive" : "image_only";
  }
  if (t) {
    return "unknown";
  }
  return "unknown";
}

export function isDepositTierChoice(text: string): boolean {
  const t = normalizeFrText(text);
  if (!t) {
    return false;
  }
  const glued = t.replace(/\s+/g, "");
  if (/^(1|2|3|4)\.?$/.test(t)) {
    return true;
  }
  // "Le 1", "le 2", "numero 1", "n°1" — common tier picks after 04_tier.
  if (/^(?:le\s+)?1\.?$/.test(t) || /^numero\s+1$/.test(t) || /^n[o°]?\s*1$/.test(t)) {
    return true;
  }
  if (/^(?:le\s+)?2\.?$/.test(t) || /^numero\s+2$/.test(t) || /^n[o°]?\s*2$/.test(t)) {
    return true;
  }
  if (/^(?:le\s+)?3\.?$/.test(t) || /^numero\s+3$/.test(t) || /^n[o°]?\s*3$/.test(t)) {
    return true;
  }
  if (/^(?:le\s+)?4\.?$/.test(t) || /^numero\s+4$/.test(t) || /^n[o°]?\s*4$/.test(t)) {
    return true;
  }
  if (t.length <= 16 && /\ble\s+1\b/.test(t)) {
    return true;
  }
  if (t.length <= 16 && /\ble\s+2\b/.test(t)) {
    return true;
  }
  if (t.length <= 16 && /\ble\s+3\b/.test(t)) {
    return true;
  }
  if (t.length <= 16 && /\ble\s+4\b/.test(t)) {
    return true;
  }
  if (
    /^(500|800|1000|1500|825|1320|1650|2500|1\s?650|2\s?500|1\s?000|1\s?500)\s*(?:clp|cfa|frs?|f|fc|pesos?)?\.?$/i.test(
      t,
    )
  ) {
    return true;
  }
  // Glued typo: "1500Fque", "1000f je", "ce1500fque"
  if (/(?:^|[^0-9])(500|800|1000|1500|825|1320|1650|2500)f(?=[a-z]|$)/i.test(glued)) {
    return true;
  }
  if (/\b(ce|c'est|cest)\s+(500|800|1000|1500|825|1320|1650|2500|1\s?000|1\s?500)\s*f/i.test(t)) {
    return true;
  }
  if (
    /\bchois/i.test(t) &&
    /(?:^|[^0-9])(500|800|1000|1500|825|1320|1650|2500|1\s?650|2\s?500|1\s?000|1\s?500)/i.test(
      t.replace(/\s/g, ""),
    )
  ) {
    return true;
  }
  if (
    t.split(/\s+/).length <= 14 &&
    /\b(500|800|1000|1500|825|1320|1650|2500|1\s?650|2\s?500|1\s?000|1\s?500)\s*(?:clp|cfa|frs?|f|fc|pesos?)?\b/i.test(t)
  ) {
    return true;
  }
  if (
    /\b(500|800|1000|1500)\s*f(?:rs?|c)?\b/i.test(t) ||
    /\b(500f|800f|1000f|1500f)(?:rs?|c)?\b/i.test(t)
  ) {
    return true;
  }
  if (/\bpour un d[eé]but\b/i.test(t) && /\b(100|1\s?000|140|200|250|clp|cfa)\b/i.test(t)) {
    return true;
  }
  if (
    /\b(je choisis|je choisi|je prends|je veux|choisis|prends|prend|elijo|escojo|i choose|i pick)\b/i.test(
      t,
    ) &&
    /\b(500|800|1000|1500|825|1320|1650|2500|1\s?000|1\s?500|1\s?650|2\s?500)\b/i.test(t)
  ) {
    return true;
  }
  return (
    isCmTier1000Choice(t) ||
    isCmTier1500Choice(t) ||
    isClTier1000LineChoice(t) ||
    isClTierFourthChoice(t) ||
    isClCustomDepositAmountChoice(text)
  );
}

/** Custom CLP deposit not in tier table (e.g. «1200», «2000 CLP»). */
export function isClCustomDepositAmountChoice(text: string): boolean {
  const t = normalizeDepositText(text);
  if (!t) {
    return false;
  }
  if (isClProfitFigure(text)) {
    return false;
  }
  return isCustomMarketDepositAmount(text, CL_CUSTOM_DEPOSIT_RULES);
}

export function isClientReadyPhrase(text: string): boolean {
  const t = normalizeFrText(text);
  if (!t) {
    return false;
  }
  return (
    /^\s*suis\s+pret[e]?\b/i.test(t) ||
    /\b(je suis pret|j'?suis pret|jsuis pret|je suis prete|j'?suis prete|jsuis prete)\b/i.test(
      t,
    ) ||
    /\b(je suis pres|j'?suis pres|jsuis pres)\b/i.test(t) ||
    /\b(pres a ecouter|pret a ecouter|pres a commencer|pret a commencer|pret a continuer)\b/i.test(
      t,
    ) ||
    /\b(je suis partant|je suis partante)\b/i.test(t) ||
    /\b(d'accord compris|d accord compris|compris|bien compris|ok compris|de acuerdo|entendido|me la juego)\b/i.test(t) ||
    /\bje veux commencer|je veux continuer\b/i.test(t) ||
    /^(pret|prete|ok|oui|d'accord|d accord|vale|listo|si|claro|por supuesto|lista)\.?$/i.test(t)
  );
}

function normalizeFrText(text: string): string {
  return (text || "")
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’]/g, "'");
}

function isProfitFigure(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    /^\d{1,3}(?:[\s.,]\d{3})+(?:\s*(?:clp|cfa|frs?|f))?\.?$/i.test(t) ||
    /^(?:8250|13200|16500|22400|70000|112000|140000|190000|10000|15000|20000|25000|30000)\s*(?:clp|cfa|frs?|f)?\.?$/i.test(
      t,
    )
  );
}

export function isClProfitFigure(text: string): boolean {
  return isProfitFigure(normalizeFrText(text)) || isProfitFigure(text);
}

function isCmTier1000Choice(t: string): boolean {
  if (/^(1er|1ere|premier|premiere)\.?$/i.test(t)) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|je prend|choisis|prends|prenez|je prendrai)\s+(le\s+)?(1er|premier|premiere|1ere)\b/i.test(
      t,
    )
  ) {
    return true;
  }
  if (/\b(le|la)\s+(1er|premier|premiere|1ere)\b/i.test(t)) {
    return true;
  }
  if (/\b(1er|premier|premiere)\s+(option|choix|montant|variante)\b/i.test(t)) {
    return true;
  }
  if (/\boption\s+1\b/i.test(t)) {
    return true;
  }
  if (/\b(premier|1er)\s+montant\b/i.test(t)) {
    return true;
  }
  if (/\bfirst(\s+one|\s+option)?\b/i.test(t)) {
    return true;
  }
  return false;
}

function isCmTier1500Choice(t: string): boolean {
  if (/^(2eme|2e|deuxieme|second)\.?$/i.test(t)) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|choisis|prends)\s+(le\s+)?(2eme|deuxieme|second)\b/i.test(
      t,
    )
  ) {
    return true;
  }
  if (/\b(je choisi|je choisis)\b/i.test(t) && /\b(1500|1\s?500)\b/i.test(t)) {
    return true;
  }
  if (/\b(le|la)\s+(2eme|deuxieme|second)\b/i.test(t)) {
    return true;
  }
  if (/\b(2eme|deuxieme|second)\s+(option|choix|montant)\b/i.test(t)) {
    return true;
  }
  if (/\boption\s+2\b/i.test(t)) {
    return true;
  }
  return false;
}

function isClTier1000LineChoice(t: string): boolean {
  if (/^(3eme|3e|troisieme|third)\.?$/i.test(t)) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|choisis|prends|elijo|escojo|i choose|i pick)\s+(le\s+)?(3eme|troisieme|third)\b/i.test(
      t,
    )
  ) {
    return true;
  }
  if (/\b(je choisi|je choisis|elijo|escojo)\b/i.test(t) && /\b(1000|1\s?000|1650|1\s?650)\b/i.test(t)) {
    return true;
  }
  if (/\b(le|la)\s+(3eme|troisieme|third)\b/i.test(t)) {
    return true;
  }
  if (/\boption\s+3\b/i.test(t)) {
    return true;
  }
  return false;
}

function isClTierFourthChoice(t: string): boolean {
  if (/^(4eme|4e|quatrieme|fourth)\.?$/i.test(t)) {
    return true;
  }
  if (
    /\b(je choisis|je prends|je veux|choisis|prends|elijo|escojo|i choose|i pick)\s+(le\s+)?(4eme|quatrieme|fourth)\b/i.test(
      t,
    )
  ) {
    return true;
  }
  if (/\b(je choisi|je choisis|elijo|escojo)\b/i.test(t) && /\b(1500|1\s?500|2500|2\s?500)\b/i.test(t)) {
    return true;
  }
  if (/\b(le|la)\s+(4eme|quatrieme|fourth)\b/i.test(t)) {
    return true;
  }
  if (/\boption\s+4\b/i.test(t)) {
    return true;
  }
  return false;
}

export function isAgeAnswer(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  const ageFromMatch = (match: RegExpMatchArray | null, group = 1): number | undefined => {
    if (!match?.[group]) {
      return undefined;
    }
    const age = Number(match[group]);
    return Number.isFinite(age) ? age : undefined;
  };
  const isValidAge = (age?: number): boolean => age !== undefined && age >= 15 && age <= 99;

  if (/^\d{1,2}$/.test(t)) {
    return isValidAge(Number(t));
  }
  if (/\b(j'ai|jai|j'?ai|ai)\s*(\d{1,2})\s*an[s]?\b/i.test(t)) {
    return isValidAge(ageFromMatch(t.match(/\b(?:j'ai|jai|j'?ai|ai)\s*(\d{1,2})\s*an[s]?\b/i), 1));
  }
  if (/\b(j'ai|jai|j'?ai|ai)\s*(\d{1,2})\b/i.test(t)) {
    return isValidAge(ageFromMatch(t.match(/\b(?:j'ai|jai|j'?ai|ai)\s*(\d{1,2})\b/i), 1));
  }
  if (/\b(\d{1,2})\s*an[s]?\b/i.test(t)) {
    return isValidAge(ageFromMatch(t.match(/\b(\d{1,2})\s*an[s]?\b/i), 1));
  }
  if (/(\d{1,2})an[s]?\b/i.test(t)) {
    return isValidAge(ageFromMatch(t.match(/(\d{1,2})an[s]?\b/i), 1));
  }
  // Written-out French ages: "j'ai vingt trois ans", "vingt-deux ans"
  const FR_AGE_WORDS: Record<string, number> = {
    quinze: 15,
    seize: 16,
    dixsept: 17,
    "dix-sept": 17,
    dixhuit: 18,
    "dix-huit": 18,
    dixneuf: 19,
    "dix-neuf": 19,
    vingt: 20,
    "vingt et un": 21,
    "vingt-et-un": 21,
    "vingtetun": 21,
    "vingt deux": 22,
    "vingt-deux": 22,
    vingtdeux: 22,
    "vingt trois": 23,
    "vingt-trois": 23,
    vingttrois: 23,
    "vingt quatre": 24,
    "vingt-quatre": 24,
    "vingt cinq": 25,
    "vingt-cinq": 25,
    "vingt six": 26,
    "vingt-six": 26,
    "vingt sept": 27,
    "vingt-sept": 27,
    "vingt huit": 28,
    "vingt-huit": 28,
    "vingt neuf": 29,
    "vingt-neuf": 29,
    trente: 30,
    "trente cinq": 35,
    "trente-cinq": 35,
    quarante: 40,
  };
  const normalizedAge = t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[’']/g, " ")
    .replace(/[^a-z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  for (const [phrase, age] of Object.entries(FR_AGE_WORDS)) {
    if (normalizedAge.includes(phrase) && (/\ban/.test(normalizedAge) || /j ?ai/.test(normalizedAge))) {
      return isValidAge(age);
    }
  }
  return false;
}

export function isClRegistrationHelpRequest(text: string): boolean {
  const t = normalizeFrText(text);
  if (!t) {
    return false;
  }
  if (/\b(vous voulez m'aide|veux m'aide|m'aider|aidez[- ]?moi|besoin d'aide)\b/i.test(t)) {
    return false;
  }
  return (
    /\b(je ne sais pas|je sais pas|sais pas faire|pas faire|comment faire)\b/i.test(t) ||
    /\b(aide|help).{0,24}(inscri|enregistr|compte|plateforme|lien|telecharg)\b/i.test(t) ||
    /\b(inscri|enregistr|compte|plateforme|lien|telecharg).{0,24}(aide|help)\b/i.test(t) ||
    /\b(je connais pas|connais pas)\b/i.test(t) ||
    /\b(je ne vois pas|je vois pas|pas de plate ?forme|plateforme|telecharg|m[' ]inscrit|je fais comment)\b/i.test(
      t,
    ) ||
    /\b(code promo|promo code|ton number|ton lien|l'application|l application|lapplication|application c'est|c'est quoi|cest quoi|comment ca marche)\b/i.test(
      t,
    )
  );
}

export function isRegistrationAccountQuestion(text: string): boolean {
  const t = normalizeFrText(text);
  if (!t) {
    return false;
  }
  return (
    /\b(je cree|je creer|je veux creer|je veux ouvrir|j'ouvre|j ouvre)\b.{0,24}\b(compte|account)\b/i.test(
      t,
    ) ||
    /\b(quel|quelle|which)\s+(compte|account)\b/i.test(t) ||
    /\b(compte|account).{0,20}(creer|cree|ouvrir|faire|inscri)\b/i.test(t) ||
    /\bcomment\s+(creer|cree|ouvrir|inscri).{0,16}(compte|account)\b/i.test(t) ||
    /\bje crée quel compte\b/i.test(t)
  );
}

export function wantsRegistrationLink(text: string): boolean {
  const t = (text || "").trim();
  const normalized = normalizeFrText(text);
  if (!t) {
    return false;
  }
  if (isRegistrationConfirmed(t)) {
    return false;
  }
  if (/^(?:le\s+)?(?:lien|link)(?:\s+please)?\s*[.!?]*$/i.test(t)) {
    return true;
  }
  if (/\b(dacor|daccor|daccord|dacor)\b.*\b(lien|link)\b/i.test(normalized)) {
    return true;
  }
  if (/\benvoy\w*.*\blien\b|\blien\b.*\benvoy\w*\b/i.test(t)) {
    return true;
  }
  if (/\b(envoi|envoyer|envoyez|donne|donner|donnez).{0,24}\b(lien|link|numero|numéro)\b/i.test(normalized)) {
    return true;
  }
  if (
    /\b(j'?attends?|en attente|attente|waiting for|wait for).{0,35}\b(lien|link|inscri)\b/i.test(
      normalized,
    )
  ) {
    return true;
  }
  if (/\b(lien|link)\b.{0,35}\b(j'?attends?|attente|waiting)\b/i.test(normalized)) {
    return true;
  }
  return (
    /\b(lien|link|inscri|register|compte|account)\b/i.test(t) &&
    /\b(envoi|envoy|donn|send|veux|besoin|where|faut|donne|donner|attends?|attente)\b/i.test(t)
  );
}

export function isRegistrationConfirmed(text: string): boolean {
  const t = normalizeFrText(text);
  return FR_REG_DONE.test(t) || FR_HAS_ACCOUNT_OR_APP.test(t);
}

export function isRegistrationPending(text: string): boolean {
  return FR_REG_PENDING.test(normalizeFrText(text));
}

export function isRegistrationBlocked(text: string): boolean {
  return FR_LINK_BROKEN.test(normalizeFrText(text));
}

export function isFunnelPositiveReaction(text: string, funnelStep: number): boolean {
  if (funnelStep >= 5) {
    return false;
  }
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (POSITIVE_EMOJI.test(t)) {
    return true;
  }
  if (/^(oui|ok|yes|d'accord|vale|listo|si|claro|por supuesto|lista)\.?$/i.test(t)) {
    return true;
  }
  if (
    /\b(oui|ok|yes|vale|listo|si|claro|por supuesto|de acuerdo|lista)\b/i.test(t) &&
    t.split(/\s+/).length <= 16
  ) {
    return true;
  }
  return false;
}

export function wantsDetailsAfterIntro(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return /\b(detail|détail|explique|explica|explícame|explicame|etape|étapes|comment ça|comment ca|how|cómo|como funciona|cuanto|cuánto)\b/i.test(
    t,
  );
}

export function isReadyForRegistration(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (isDepositTierChoice(t)) {
    return true;
  }
  if (isProfitFigure(t)) {
    return true;
  }
  if (/^(oui|ok|yes|d'accord)\.?$/i.test(t)) {
    return true;
  }
  if (FR_POSITIVE.test(t) && t.split(/\s+/).length <= 4) {
    return true;
  }
  return false;
}
