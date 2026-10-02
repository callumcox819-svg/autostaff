import type { CountryCode, PlaybookConfig, TemplateRole } from "./config.js";

export type SpecialCustomerIntent =
  | "no_money"
  | "deferral"
  | "declined"
  | "money_request"
  | "phone_request"
  | "scam_accusation"
  | "none";

const FR_NO_MONEY =
  /\b(pas d['']?argent|pas de argent|pas d argent|pas l['']?argent|ne pas l['']?argent|je ne pas l['']?argent|j['']?ai pas d['']?argent|je n['']?ai pas d['']?argent|je n ai pas d argent|sans argent|manque d['']?argent|pas les moyens|pas de sous|pas de fric|no money)\b/i;
const FR_DEFERRAL =
  /\b(plus tard|pas maintenant|pas maintenant|demain|une autre fois|quand j['']?aurai|quand j aurai|je suis occupe|je suis occupé|trop occupe|trop occupé|pas le temps|je reviens)\b/i;
const FR_DECLINED =
  /\b(pas intéressé|pas interesse|je ne suis pas intéressé|non merci|laisse moi|arrête|arrete|stop)\b/i;
const FR_SCAM = /\b(arnaque|escroc|scam|voleur|nigerian|nigérian)\b/i;

const EN_NO_MONEY =
  /\b(no money|don't have money|do not have money|not enough money|broke|can't afford|cannot afford|no funds|no cash)\b/i;
const EN_DEFERRAL =
  /\b(later|not now|tomorrow|another time|when i have|too busy|no time|come back|not ready yet)\b/i;
const EN_DECLINED = /\b(not interested|no thanks|leave me|stop texting|go away)\b/i;

const AR_NO_MONEY =
  /(مش معايه فلوس|مش معاي فلوس|معنديش فلوس|مفيش فلوس|لا فلوس|بدون فلوس|مصاري|مش معايا فلوس|ما عندي فلوس)/i;
const AR_DEFERRAL = /(بعدين|مش دلوقتي|مش الآن|لاحقا|لاحقاً|مشغول|مش فاضي|ارجع|ارجعلك)/i;
const AR_DECLINED = /(مش مهتم|مش مهتمة|مش عايز|مش عاوز|سيبني|بطل|لا شكرا)/i;
const AR_SCAM = /(نصب|نصاب|احتيال|سكام|حرامي)/i;

const FR_MONEY_REQUEST =
  /\b(prête[- ]moi|pret[- ]moi|donne[- ](moi )?(de l')?argent|envoy\w*[- ](moi )?(de l')?argent|besoin d['']?argent|besoin d argent)\b/i;
const EN_MONEY_REQUEST =
  /\b(send(ing)?\s+me\s+(money|cash|funds)|give\s+me\s+(money|cash|funds)|lend\s+me|loan\s+me|need\s+money|want\s+money)\b/i;
const AR_MONEY_REQUEST =
  /(فلوس|محتاج\s*فلوس|عايز\s*فلوس|عاوز\s*فلوس|ابعت(لي|ولي)\s*فلوس|ارسل(لي|ني)\s*فلوس|اديني\s*فلوس)/i;
const EN_PHONE_REQUEST =
  /\b(your|ur)\s+(phone\s*)?number\b|\b(send|give|share|drop)\s+(me\s+)?(your\s+)?(phone\s*)?number\b|\b(phone|mobile|cell)\s*number\b|\bcall\s+me\b|\bwhatsapp\s*(number|no\.?|line)?\b|\bnumber\s+please\b|\bmode of communication\b/i;
const FR_PHONE_REQUEST =
  /\b(envoy\w*|donn\w*|pass\w*|mets?)\b.{0,30}\b(ton|votre|ta)\s*(numéro|numero)\b|\b(numéro|numero)\s+(de\s+)?(téléphone|telephone|tel)\b|\b(ton|votre|ta)\s+(numéro|numero|tel)\b|\bappelle[- ]moi\b|\bwhatsapp\b/i;
const AR_PHONE_REQUEST =
  /(رقمك|رقم الهاتف|رقم التليفون|رقم الواتس|واتس|واتساب|اتصل(ي)?\s*بي|اتصل\s*معي|ابعت(لي)?\s*رقم|ارسل(لي)?\s*رقم)/i;

/** Casino game IDs (16/17…) must not be treated as phone numbers. */
export function isLikelyGameId(text: string): boolean {
  const digits = (text || "").replace(/\s+/g, "");
  return /^(16|17)\d{6,}$/.test(digits);
}

export function normalizeCustomerText(value?: string): string {
  return (value || "")
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’]/g, "'")
    .replace(/\s+/g, " ");
}

export function classifySpecialCustomerIntent(
  playbook: PlaybookConfig,
  text: string,
): SpecialCustomerIntent {
  const t = normalizeCustomerText(text);
  if (!t) {
    return "none";
  }

  if (matchesPlaybookKeywords(playbook.noMoneyKeywords, t)) {
    return "no_money";
  }
  if (matchesPlaybookKeywords(playbook.notReadyKeywords ?? [], t)) {
    return "deferral";
  }

  if (FR_SCAM.test(t) || EN_DECLINED.test(t) && /scam|fraud/i.test(t) || AR_SCAM.test(t)) {
    return "scam_accusation";
  }
  if (FR_DECLINED.test(t) || EN_DECLINED.test(t) || AR_DECLINED.test(t)) {
    return "declined";
  }
  if (FR_MONEY_REQUEST.test(t) || EN_MONEY_REQUEST.test(t) || AR_MONEY_REQUEST.test(t)) {
    return "money_request";
  }
  if (FR_PHONE_REQUEST.test(t) || EN_PHONE_REQUEST.test(t) || AR_PHONE_REQUEST.test(t)) {
    return "phone_request";
  }
  const digitsOnly = t.replace(/\s+/g, "");
  if (/^\d{9,12}$/.test(digitsOnly) && !isLikelyGameId(t)) {
    return "phone_request";
  }
  if (FR_NO_MONEY.test(t) || EN_NO_MONEY.test(t) || AR_NO_MONEY.test(t)) {
    return "no_money";
  }
  if (FR_DEFERRAL.test(t) || EN_DEFERRAL.test(t) || AR_DEFERRAL.test(t)) {
    return "deferral";
  }

  return "none";
}

export function specialIntentTemplateRole(intent: SpecialCustomerIntent): TemplateRole | undefined {
  switch (intent) {
    case "no_money":
    case "deferral":
      return "no_money";
    default:
      return undefined;
  }
}

/** Localized "we don't give money" — only after funnel script 1 already went out. */
export function moneyRefusalText(country: CountryCode | string): string {
  switch (country) {
    case "CM":
    case "MG":
    case "DJ":
      return "Nous ne donnons pas d'argent — nous vous aidons seulement à gagner avec nos tactiques. Quand vous serez prêt à investir, écrivez-moi.";
    case "EG":
    case "JO":
      return "نحن لا نُعطي أموالاً، بل نساعدك فقط على الكسب بالتكتيكات. عندما تكون جاهزاً للاستثمار، راسلني.";
    case "CL":
      return "No damos dinero — solo te ayudamos a ganar con nuestras tácticas. Cuando estés listo para invertir, escríbeme.";
    default:
      // ZM, RW, and other English markets
      return "We don't give money — we only help you earn with our tactics. Message me when you're ready to invest.";
  }
}

export function phoneChatOnlyText(country: CountryCode | string): string {
  switch (country) {
    case "CM":
    case "MG":
    case "DJ":
      return "Nous communiquons uniquement en ligne dans ce chat. Si vous êtes intéressé, écrivez-moi ici et on continue.";
    case "EG":
    case "JO":
      return "نتواصل فقط أونلاين داخل هذه المحادثة. إذا كنت مهتماً، اكتب لي هنا ونكمل.";
    case "CL":
      return "Nos comunicamos solo en línea en este chat. Si te interesa, escríbeme aquí y seguimos.";
    default:
      return "We only communicate online in this chat. If you're interested, text me here and we'll continue.";
  }
}

export function matchesPlaybookKeywords(keywords: string[], text: string): boolean {
  const normalized = normalizeCustomerText(text);
  if (!normalized) {
    return false;
  }
  return keywords.some((keyword) => normalized.includes(normalizeCustomerText(keyword)));
}
