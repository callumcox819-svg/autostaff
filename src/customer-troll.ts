import type { CountryCode } from "./config.js";
import { normalizeCustomerText } from "./customer-intent.js";
import {
  isDepositTierChoice,
  isCmRegistrationHelpRequest,
  wantsRegistrationLink,
  isRegistrationAccountQuestion,
  isReadyForRegistration,
  isFunnelPositiveReaction,
} from "./cm-intent.js";
import { isCustomerClarificationMessage, isLinkAccessProblemMessage } from "./customer-clarity.js";
import { extractCmClientLoginId17 } from "./cm-proof.js";

/** Markets where off-topic troll detection is enabled (French funnels). */
export type TrollDetectionCountry = "CM" | "CL";

export function isTrollDetectionCountry(country: string): country is TrollDetectionCountry {
  return country === "CM" || country === "CL";
}

const FUNNEL_TOPIC =
  /\b(casino|inscri|enregistr|compte|d[eé]p[oô]t|cfa|franc|lien|link|gagn|invest|promo|cash056|cmr056|cle333|1xbet|plateforme|strat[eé]g|tactique|montant|profit|age|âge)\b/i;

const OFF_TOPIC_STRONG =
  /\b(nike|blazer|adidas|puma|iphone|samsung|huawei|windows\s*(10|11)?|hotel|h[oô]tel|sticker|musique|musiques|chanson|spotify|youtube|tiktok|film|cin[eé]ma|netflix|football|basket|maillot|sneaker|good deal|black friday|promo nike)\b/i;

const JOURNEE_SPAM = /(de la journ[eé]e[\s,.]*){3,}/i;
const GIBBERISH_LETTER = /\b([a-zàâäéèêëïîôùûüç])\1{5,}/i;
const RAMBLING_SPAM =
  /\b(groupe scolaire|petite famille|excellente fin de semaine|bonne vacances).{0,120}(musique|musiques|bonne id[eé]e de toi)\b/i;

const INTERESTED =
  /\b(cela m'int[eé]resse|ça m'int[eé]resse|interess[eé]|comment ça marche|comment ça fonctionne|explique|détails|details|je veux|je suis partant)\b/i;

export type TrollGateOptions = {
  /** Tier table / reg link / deposit scripts already sent in thread. */
  hasFunnelProgress: boolean;
  latestHasImage: boolean;
};

function isLegitimateCustomerMessage(text: string, funnelStep = 0): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (isDepositTierChoice(t) || isCmRegistrationHelpRequest(t) || wantsRegistrationLink(t)) {
    return true;
  }
  if (isRegistrationAccountQuestion(t) || isReadyForRegistration(t)) {
    return true;
  }
  if (isCustomerClarificationMessage(t) || isLinkAccessProblemMessage(t)) {
    return true;
  }
  if (extractCmClientLoginId17(t)) {
    return true;
  }
  if (INTERESTED.test(normalizeCustomerText(t))) {
    return true;
  }
  if (isFunnelPositiveReaction(t, funnelStep)) {
    return true;
  }
  if (FUNNEL_TOPIC.test(normalizeCustomerText(t))) {
    return true;
  }
  if (/^\d{2,4}$/.test(t.replace(/\s/g, ""))) {
    return true;
  }
  return false;
}

/** 0 = ok, 1 = suspicious, 2+ = clear off-topic / trolling. */
export function scoreOffTopicTrollMessage(text: string): number {
  const raw = (text || "").trim();
  if (!raw || raw.length < 2) {
    return 0;
  }
  const t = normalizeCustomerText(raw);
  if (isLegitimateCustomerMessage(raw)) {
    return 0;
  }

  let score = 0;

  if (OFF_TOPIC_STRONG.test(t)) {
    score += 2;
  }
  if (JOURNEE_SPAM.test(t)) {
    score += 2;
  }
  if (GIBBERISH_LETTER.test(t)) {
    score += 1;
  }
  if (RAMBLING_SPAM.test(t)) {
    score += 2;
  }
  if (/^(windows|nike|hyy+|lol+|mdr+|haha+)[.!\s]*$/i.test(t)) {
    score += 2;
  }
  if (t.length > 80 && !FUNNEL_TOPIC.test(t) && /\b(je vous souhaite|tu veux que je|musique|vacances|famille)\b/i.test(t)) {
    score += 1;
  }
  if (raw.length > 120 && !FUNNEL_TOPIC.test(t) && (raw.match(/\?/g)?.length ?? 0) === 0) {
    score += 1;
  }

  return score;
}

/**
 * Conservative: ignore only when clearly off-topic / mocking — never mid-funnel or interested leads.
 */
export function shouldIgnoreTrollCustomer(
  latestText: string,
  recentCustomerTexts: string[],
  options: TrollGateOptions,
  funnelStep = 0,
): boolean {
  if (options.latestHasImage) {
    return false;
  }
  if (isLegitimateCustomerMessage(latestText, funnelStep)) {
    return false;
  }

  const latestScore = scoreOffTopicTrollMessage(latestText);
  if (latestScore >= 2) {
    return true;
  }

  const recent = [latestText, ...recentCustomerTexts.filter((line) => line !== latestText)].slice(0, 5);
  let offTopicHits = 0;
  for (const line of recent) {
    if (isLegitimateCustomerMessage(line, funnelStep)) {
      continue;
    }
    if (scoreOffTopicTrollMessage(line) >= 1) {
      offTopicHits += 1;
    }
  }

  if (offTopicHits >= 2 && latestScore >= 1) {
    return true;
  }
  if (offTopicHits >= 3) {
    return true;
  }

  // Mid-funnel: need stronger proof so we never drop real deposit/reg threads.
  if (options.hasFunnelProgress) {
    return latestScore >= 2 && offTopicHits >= 2;
  }

  return false;
}
