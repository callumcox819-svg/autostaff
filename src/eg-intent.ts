import { isPositiveMessageReaction } from "./message-attachments.js";
import { isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";

export type EgIntent =
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

const AR_POSITIVE =
  /(تمام|اوك|أوك|حاضر|ماشي|نعم|اه|آه|طيب|موافق|على الله|علي الله|ان شاء الله|إن شاء الله|انشاء الله|ماشاء الله|ما شاء الله|ok|okay|yes)/i;
const AR_GREETING = /^(اهلا|أهلا|اهلاً|أهلاً|مرحبا|مرحباً|السلام|سلام|هاي|هلو|hello|hi)([\s,!.]|$)/i;
const AR_INTERESTED =
  /(أنا مهتم|انا مهتم|مهتم|مهتمة|عايز|عاوز|عايزه|عاوزه|عايزه اعرف|عايز اعرف|أريد|اريد|اشرح|اشرحلي|ازاي|كيف|تفاصيل|ممكن تفاصيل|ممكن|هل ذلك|هل ده|نعم|ايوه|أيوه|مهتمين|حابب|حابة|محتاج|محتاجة|مساعدة|مساعده|تساعد|بتساعد|ابا|أبا|ابي|أبي|ابغى|ابغي|كلمني|اتكلم|نتكلم|أنا بحاجة|انا بحاجة|بحاجة الى|بحاجة إلى|كيف اربح|كيف أربح|معاك|معك|مثير لاهتمامي|اهتمامي|مثير|هذا مثير)/i;
const AR_DECLINED = /(مش مهتم|مش مهتمة|مش عايز|مش عاوز|لا شكرا|لا شكراً|^لا[.!]?$|سيبني|بطل|stop|scam)/i;
const AR_READY = /(جاهز|جاهزة|يلا|يلّا|ابدأ|ابدأوا|مستعد|مستعدة|خلاص|هنبدأ)/i;
const AR_JOINED =
  /(سجلت|سجلت حساب|عملت حساب|خلصت التسجيل|تم التسجيل|سجلت بالفعل|عملت التسجيل|هسجل|هسجل وأبعتلك|هسجل وابعتلك|أسجل|اسجل|registered|account created)/i;
const AR_REG_PENDING = /(لسه|لسا|مش خلصت|بحاول|جاري التسجيل|not yet|still registering|هسجل|أسجل|اسجل)/i;
const AR_DEPOSIT_DONE =
  /(عملت إيداع|عملت ايداع|عملت الإيداع|منتظر التأكيد|ايداع|إيداع|deposit|funded)/i;
const GAME_ID = /\b(17\d{6,}|16\d{6,})\b/;
const POSITIVE_EMOJI = /^[\s👍👌✅🔥❤️🙏😊🙂]+$/u;
const AR_LINK_ASK =
  /(اللينك|الرابط|ابعت.*لينك|ابعت.*رابط|وين اللينك|فين اللينك|محتاج اللينك|عايز اللينك|عاوز اللينك|link|url)/i;
const AR_REG_HELP =
  /(مش عارف|مش فاهم|مش شغال|مش راضي|مش راضية|sms|الرسالة|الكود|مش واصل|مش واصلة|مشكلة|problem)/i;

export function classifyEgIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): EgIntent {
  const t = (text || "").trim();
  const step = options?.funnelStep ?? 0;

  if (isCustomerSaysNotRegisteredYet(t)) {
    return "question";
  }
  if (AR_DECLINED.test(t)) {
    return "declined";
  }
  if (GAME_ID.test(t)) {
    return "game_id_text";
  }
  if (isDepositConfirmed(t)) {
    return "deposit_done";
  }
  if (isRegistrationConfirmed(t)) {
    return "joined";
  }
  if (isReadyForRegistration(t)) {
    return "ready";
  }
  if (wantsRegistrationLink(t)) {
    return "ready";
  }
  if (isEgJoinOrRegistrationQuestion(t) || isRegistrationHelpRequest(t)) {
    return "ready";
  }
  if (!t && isPositiveMessageReaction(options?.messageReaction)) {
    return "positive";
  }
  if (!t && options?.hasImage) {
    return step < 6 ? "positive" : "image_only";
  }
  if (POSITIVE_EMOJI.test(t) && t.length <= 4) {
    return "positive";
  }
  if (AR_INTERESTED.test(t)) {
    return "interested";
  }
  if (AR_GREETING.test(t)) {
    return step < 2 ? "interested" : "positive";
  }
  if (AR_READY.test(t)) {
    return "ready";
  }
  if (AR_POSITIVE.test(t) && t.split(/\s+/).length <= 8) {
    return "positive";
  }
  if (/^(ok|okay|yes|نعم|اه|آه)\.?$/i.test(t)) {
    return step >= 4 ? "ready" : "positive";
  }
  if (/\?/.test(t) || AR_INTERESTED.test(t)) {
    return "question";
  }
  if (options?.hasImage && !t) {
    return step < 6 ? "positive" : "image_only";
  }
  if (AR_JOINED.test(t)) {
    return "joined";
  }
  return t ? "unknown" : "unknown";
}

export function isFunnelPositiveReaction(text: string, funnelStep = 0): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (POSITIVE_EMOJI.test(t)) {
    return true;
  }
  if (funnelStep < 4 && /^(yes|ok|okay|نعم|اه|آه|تمام|طيب)\.?$/i.test(t)) {
    return true;
  }
  if (funnelStep >= 4 && /^(yes|ok|okay|نعم|اه|آه|تمام|جاهز|ready)\.?$/i.test(t)) {
    return true;
  }
  if (funnelStep < 4 && AR_POSITIVE.test(t) && t.split(/\s+/).length <= 4) {
    return true;
  }
  return false;
}

export function wantsDetailsAfterIntro(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return /(تفاصيل|تفاصيل أكثر|تفاصيل اكثر|ممكن تفاصيل|قولي تفاصيل|اشرح|اشرحلي|ازاي|كيف|تداول|يعني|أكثر|اكثر|ممكن|how|explain|details|more)/i.test(
    t,
  );
}

export function isAppOrBrowserQuestion(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (/(تطبيق|متصفح|انزل|البرنامج|الابليكيشن|كروم|chrome|download|app)/i.test(t)) {
    return true;
  }
  return /\b(app|browser|download|install|play store|apk)\b/i.test(t);
}

export function isDepositConfirmed(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return AR_DEPOSIT_DONE.test(t);
}

export function wantsRegistrationLink(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (isRegistrationConfirmed(t)) {
    return false;
  }
  if (isRegistrationHelpRequest(t)) {
    return true;
  }
  return AR_LINK_ASK.test(t);
}

export function isReadyForRegistration(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (AR_READY.test(t)) {
    return true;
  }
  if (AR_POSITIVE.test(t) && t.split(/\s+/).length <= 4) {
    return true;
  }
  return /^(yes|ok|okay|نعم|اه|آه|تمام)\.?$/i.test(t);
}

export function isRegistrationConfirmed(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    AR_JOINED.test(t) ||
    /\b(registered|registration done|account created|waiting for the next step|next step)\b/i.test(t)
  );
}

export function isRegistrationPending(text: string): boolean {
  const t = (text || "").trim();
  return AR_REG_PENDING.test(t);
}

export function isRegistrationHelpRequest(text: string): boolean {
  const t = (text || "").trim();
  if (AR_INTERESTED.test(t) && !/(تسجيل|حساب|لينك|رابط|كود|sms|انضمام|انضم|اشتراك)/i.test(t)) {
    return false;
  }
  return (
    AR_REG_HELP.test(t) ||
    isEgJoinOrRegistrationQuestion(t) ||
    /\b(problem|issue|error|help).{0,30}(registration|register|account)\b/i.test(t) ||
    /(السكرين|سكرين|لقطة|صورة).{0,24}(مش واضح|واضح)/i.test(t) ||
    /مساعد(ة|ه).{0,24}(تسجيل|حساب|لينك|رابط|كود)/i.test(t) ||
    /(تسجيل|حساب|لينك|رابط|كود).{0,24}مساعد(ة|ه)/i.test(t)
  );
}

export function isEgJoinOrRegistrationQuestion(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    /(كيف|ازاي|ازاى).{0,24}(انضمام|انضم|التسجيل|اسجل|سجل|اشترك|اشتراك|انضم|الانضمام)/i.test(t) ||
    /(انضمام|التسجيل|اشتراك).{0,24}(كيف|ازاي|ازاى)/i.test(t) ||
    /(أنشئ|انشئ|اعمل|افتح|انشاء).{0,24}(حساب|اكونت|account)/i.test(t) ||
    /(ايه|اي|أي|which).{0,16}(حساب|اكونت|account)/i.test(t) ||
    /(حساب|اكونت).{0,20}(انشئ|انشاء|اعمل|افتح|انشاء)/i.test(t) ||
    /(رقم|رقمى|رقمي).{0,16}(حساب|اكونت|عميل|لاعب)/i.test(t) ||
    /(حساب|اكونت).{0,16}(رقم|ايه|اي|أي)/i.test(t) ||
    /تمام.{0,24}(انضمام|انضم|التسجيل|كيف)/i.test(t)
  );
}

export function isEgDepositTierChoice(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (/^(1|2)\.?$/.test(t)) {
    return true;
  }
  if (/\b(55|110)\s*(?:egp|جنيه|جنية)?\b/i.test(t)) {
    return true;
  }
  if (/\b(الأول|الاول|الأولى|الاولى|التاني|الثاني|الثانية)\b/i.test(t)) {
    return true;
  }
  return false;
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
