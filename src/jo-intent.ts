import { isPositiveMessageReaction } from "./message-attachments.js";
import { isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";
import {
  customerAgreedAfterOfferTable,
  customerRequestsRegistrationMaterials,
} from "./funnel-common.js";
import {
  isCustomMarketDepositAmount,
  normalizeDepositText,
  type CustomDepositRules,
} from "./market-deposit-choice.js";

export type JoIntent =
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

export const JO_CUSTOM_DEPOSIT_RULES: CustomDepositRules = {
  min: 2,
  max: 50_000,
  bareMin: 2,
  currencyPattern: /(?:\b(?:jod|jd)\b)|دينار|أردني|اردني/i,
  depositIntentPattern:
    /\b(deposit|depot|start|ready|choose|ok|yes)\b|إيداع|ايداع|أختار|اختار|جاهز|نعم|تمام|موافق/i,
};

const AR_POSITIVE =
  /(تمام|اوك|أوك|حاضر|ماشي|نعم|اه|آه|طيب|موافق|على الله|علي الله|ان شاء الله|إن شاء الله|انشاء الله|ok|okay|yes)/i;
const AR_GREETING = /^(اهلا|أهلا|اهلاً|أهلاً|مرحبا|مرحباً|السلام|سلام|هاي|هلو|hello|hi|مرحبا)([\s,!.]|$)/i;
const AR_INTERESTED =
  /(أنا مهتم|انا مهتم|مهتم|مهتمة|عايز|عاوز|أريد|اريد|اشرح|ازاي|كيف|تفاصيل|ممكن|نعم|ايوه|أيوه|حابب|حابة|محتاج|تساعد|مثير|اهتمام)/i;
const AR_DECLINED = /(مش مهتم|مش مهتمة|مش عايز|لا شكرا|لا شكراً|^لا[.!]?$|سيبني|بطل|stop|scam)/i;
const AR_READY = /(جاهز|جاهزة|يلا|يلّا|ابدأ|مستعد|مستعدة|خلاص|هنبدأ|ابدأ)/i;
const AR_JOINED =
  /(سجلت|سجلت حساب|عملت حساب|خلصت التسجيل|تم التسجيل|registered|account created)/i;
const AR_DEPOSIT_DONE = /(عملت إيداع|عملت ايداع|ايداع|إيداع|deposit|funded)/i;
const GAME_ID = /\b(17\d{6,}|16\d{6,})\b/;
const POSITIVE_EMOJI = /^[\s👍👌✅🔥❤️🙏😊🙂]+$/u;
const AR_LINK_ASK =
  /(اللينك|الرابط|ابعت.*لينك|ابعت.*رابط|وين اللينك|فين اللينك|محتاج اللينك|link|url)/i;
const AR_REG_HELP =
  /(مش عارف|مش فاهم|مش شغال|sms|الكود|مش واصل|مشكلة|problem|jor778|الرمز الترويجي)/i;

export function classifyJoIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): JoIntent {
  const t = (text || "").trim();
  const step = options?.funnelStep ?? 0;

  if (!t && options?.hasImage) {
    return "image_only";
  }
  if (!t) {
    if (isPositiveMessageReaction(options?.messageReaction)) {
      return "positive";
    }
    return "unknown";
  }
  if (AR_DECLINED.test(t)) {
    return "declined";
  }
  if (GAME_ID.test(t)) {
    return "game_id_text";
  }
  if (AR_DEPOSIT_DONE.test(t)) {
    return "deposit_done";
  }
  if (AR_JOINED.test(t)) {
    return "joined";
  }
  if (AR_READY.test(t) || wantsRegistrationLink(t) || isRegistrationHelpRequest(t)) {
    return "ready";
  }
  if (AR_INTERESTED.test(t)) {
    return "interested";
  }
  if (POSITIVE_EMOJI.test(t) || isPositiveMessageReaction(options?.messageReaction)) {
    return "positive";
  }
  if (AR_POSITIVE.test(t) && t.split(/\s+/).length <= 10) {
    return "positive";
  }
  if (AR_GREETING.test(t)) {
    return step < 2 ? "interested" : "positive";
  }
  if (/\?/.test(t)) {
    return "question";
  }
  if (isJoOfferTableChoice(t)) {
    return "positive";
  }
  return "unknown";
}

export function isFunnelPositiveReaction(text: string, _effectiveStep: number): boolean {
  const t = (text || "").trim();
  return (
    AR_POSITIVE.test(t) ||
    AR_READY.test(t) ||
    AR_INTERESTED.test(t) ||
    POSITIVE_EMOJI.test(t)
  );
}

export function isReadyForRegistration(text: string): boolean {
  const t = (text || "").trim();
  return (
    AR_READY.test(t) ||
    customerAgreedAfterOfferTable(t) ||
    isJoDepositAmountChoice(t) ||
    /(جاهز|يلا|ابدأ|مستعد|تمام|موافق)/i.test(t)
  );
}

export function isRegistrationConfirmed(text: string): boolean {
  return AR_JOINED.test((text || "").trim());
}

export function isRegistrationHelpRequest(text: string): boolean {
  const t = (text || "").trim();
  return AR_REG_HELP.test(t) || customerRequestsRegistrationMaterials(t);
}

export function isJoRegistrationAccountQuestion(text: string): boolean {
  const t = (text || "").trim();
  return (
    /(حساب|تسجيل|إيميل|ايميل|chrome|كود|jor778|vpn)/i.test(t) &&
    (/\?/.test(t) || /(ازاي|كيف|مساعدة|مشكلة|help)/i.test(t))
  );
}

export function isBarePostLinkAcknowledgment(text: string, intent: JoIntent): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (intent === "declined" || intent === "joined" || intent === "deposit_done" || intent === "game_id_text") {
    return false;
  }
  return /^(ok|okay|نعم|اه|آه|تمام|حاضر|ماشي|شكرا|شكرًا)[.!\s]*$/i.test(t);
}

export function wantsDetailsAfterIntro(text: string): boolean {
  const t = (text || "").trim();
  return AR_INTERESTED.test(t) || AR_POSITIVE.test(t) || AR_READY.test(t) || /(اشرح|تفاصيل|كيف|ازاي)/i.test(t);
}

export function wantsRegistrationLink(text: string): boolean {
  const t = (text || "").trim();
  return AR_LINK_ASK.test(t) || customerRequestsRegistrationMaterials(t);
}

/** Table picks: «2», «5», «15», «2 دينار», الأول / الثاني / الثالث. */
export function isJoOfferTableChoice(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (/^(الأول|الاول|الثاني|التاني|الثالث|التالت|1|2|3|٢|٥|١٥)\.?$/i.test(t)) {
    return true;
  }
  if (
    /(أختار|اختار|عايز|عاوز|هذا|ده|الأول|الاول|الثاني|الثالث)/i.test(t) &&
    /(?:^|[^\d٠-٩])(2|5|15|٢|٥|١٥)(?:[^\d٠-٩]|$)/i.test(t)
  ) {
    return true;
  }
  return isJoDepositAmountChoice(t);
}

export function isJoDepositAmountChoice(text: string): boolean {
  const folded = normalizeDepositText(text);
  if (!folded) {
    return false;
  }
  const hasAmount =
    /(?:^|[^\d])(2|5|15)(?:\s*(?:jod|jd|دينار))?(?![0-9])/i.test(folded) ||
    /(?:^|[^\d٠-٩])(٢|٥|١٥)(?:\s*دينار)?/i.test(folded);
  if (hasAmount) {
    if (
      /دينار|jod|\bjd\b|أردني|اردني/i.test(folded) ||
      /(أختار|اختار|عايز|عاوز|هذا|ده|إيداع|ايداع|موافق|تمام)/i.test(folded) ||
      folded.length < 40
    ) {
      return true;
    }
  }
  return isCustomMarketDepositAmount(text, JO_CUSTOM_DEPOSIT_RULES);
}

export { isCustomerSaysNotRegisteredYet };
