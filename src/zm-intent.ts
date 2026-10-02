import { isPositiveMessageReaction } from "./message-attachments.js";
import { isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";
import {
  customerAgreedAfterOfferTable,
  customerRequestsRegistrationMaterials,
} from "./funnel-common.js";
import {
  isCustomMarketDepositAmount,
  normalizeDepositText,
  ZM_CUSTOM_DEPOSIT_RULES,
} from "./market-deposit-choice.js";

export type ZmIntent =
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

const INTERESTED =
  /\b(interested|i'?m interested|i am interested|tell me more|teach me|need help|go ahead|very interested|want to learn|i want to invest|would like to join|count me in|assist me|kindly help|financial help|i want to know|tell me)\b/i;
const POSITIVE =
  /\b(yes|yess?|ok|okay|sure|alright|got it|i am|how can i start|how do i start|continue|proceed|yh|yeah|yea|yep|yez|yaah|cool|next|please)\b/i;
const READY =
  /\b(i'?m ready|am ready|let'?s start|start today|ready to start|i'?m in|i am ready|lets start|let us start|much ready|me i'?m always ready|yes i am ready)\b/i;
const GREETING = /^(hi|hello|hey|heyy|good morning|good evening|morning|yo)([\s,!.]|$)/i;
const JOINED = /\b(have joined|joined|i joined|registered already|done registering|account created)\b/i;
const DECLINED = /\b(not interested|no thanks|stop|scam|leave me alone)\b/i;
const BARE_DECLINED = /^(no|nah|nope|never|nothing|no thanks|no thank you|no dear|not interested)\.?!*$/i;
const DEPOSIT_DONE =
  /\b(made my dep(?:o)?sit|i deposited|deposit done|done deposit|deposited|after i deposited|i made a deposit)\b/i;
const GAME_ID = /\b(17\d{6,}|16\d{6,}|account\s*\d+)\b/i;
const POSITIVE_EMOJI = /^[\s👍👌✅🔥❤️🙏😊🙂]+$/u;
const EN_LINK_ASK =
  /\b(?:send|give|share|want|need|get|where|gimme).{0,28}\b(?:link|url)\b|\b(?:link|url)\b.{0,28}\b(?:please|pls|send|registration|register)\b|\bregistration\s+link\b|\bregister\s+link\b|\bneed\s+(?:the\s+)?link\b/i;
const REGISTRATION_HELP =
  /\b(your code|promo code|which code|what code|use that one|used that one|use this one|create the account|creat the account|create account|creat account|register with|how to register|what next|next step)\b/i;

export function classifyZmIntent(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): ZmIntent {
  const t = (text || "").trim();
  const step = options?.funnelStep ?? 0;

  if (DECLINED.test(t) || BARE_DECLINED.test(t)) {
    return "declined";
  }
  if (isCustomerSaysNotRegisteredYet(t)) {
    return "question";
  }
  if (DEPOSIT_DONE.test(t)) {
    return "deposit_done";
  }
  if (/\b(no i am not|not yet|no not yet)\b/i.test(t)) {
    return "unknown";
  }
  if (GAME_ID.test(t)) {
    return "game_id_text";
  }
  if (isRegistrationConfirmed(t)) {
    return "joined";
  }
  if (isReadyForRegistration(t)) {
    return "ready";
  }
  if (isZmDepositAmountChoice(t)) {
    return "ready";
  }
  if (wantsRegistrationLink(t) || isRegistrationHelpRequest(t) || customerAgreedAfterOfferTable(t)) {
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
  if (INTERESTED.test(t)) {
    return "interested";
  }
  if (GREETING.test(t)) {
    return step < 2 ? "interested" : "positive";
  }
  if (READY.test(t)) {
    return "ready";
  }
  if (POSITIVE.test(t) && t.split(/\s+/).length <= 8) {
    return "positive";
  }
  if (/^(ok|okay|yes|sure|alright)\.?$/i.test(t)) {
    return step >= 4 ? "ready" : "positive";
  }
  if (/\?/.test(t) || /\b(what|how|why|when|where|explain)\b/i.test(t)) {
    return "question";
  }
  if (options?.hasImage && !t) {
    return step < 5 ? "positive" : "image_only";
  }
  if (JOINED.test(t)) {
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
  if (funnelStep < 4 && /^(yes|ok|okay|sure|alright)\.?$/i.test(t)) {
    return true;
  }
  if (funnelStep >= 4 && /^(yes|ok|okay|sure|alright|i'?m ready|ready)\.?$/i.test(t)) {
    return true;
  }
  if (funnelStep < 4 && POSITIVE.test(t) && t.split(/\s+/).length <= 4) {
    return true;
  }
  return false;
}

export function wantsDetailsAfterIntro(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    /^explain\??$/i.test(t) ||
    /^how\??$/i.test(t) ||
    /\b(how it works|how does it work|tell me more|more details|explain)\b/i.test(t)
  );
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
  if (customerRequestsRegistrationMaterials(t)) {
    return true;
  }
  if (/^(?:the\s+)?(?:link|url)(?:\s+please)?\s*[.!?]*$/i.test(t)) {
    return true;
  }
  if (EN_LINK_ASK.test(t)) {
    return true;
  }
  return (
    /\b(send|give|share|want|need|where).{0,28}\b(link|url)\b/i.test(t) ||
    /\bregistration\s+link\b/i.test(t) ||
    /\bregister\s+link\b/i.test(t)
  );
}

export function isReadyForRegistration(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (/\bno i am not\b/i.test(t)) {
    return false;
  }
  if (isZmDepositAmountChoice(t)) {
    return true;
  }
  if (/^yes\.?$/i.test(t)) {
    return true;
  }
  if (READY.test(t)) {
    return true;
  }
  if (POSITIVE.test(t) && t.split(/\s+/).length <= 4) {
    return true;
  }
  if (/\b(let'?s go|let'?s do it|i'?m in|count me in)\b/i.test(t)) {
    return true;
  }
  return false;
}

/** Short ack after reg link (Okay/Yes) — not proof of registration. */
export function isBarePostLinkAcknowledgment(text: string, intent: ZmIntent): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (
    isRegistrationConfirmed(t) ||
    isRegistrationHelpRequest(t) ||
    isZmRegistrationAccountQuestion(t) ||
    wantsRegistrationLink(t) ||
    isCustomerSaysNotRegisteredYet(t)
  ) {
    return false;
  }
  if (/^(ok|okay|yes|sure|alright|k|got it|thanks|thank you)\.?$/i.test(t)) {
    return true;
  }
  if ((intent === "positive" || intent === "ready") && t.split(/\s+/).length <= 4) {
    return /^[\p{L}\s'.!?]+$/u.test(t) && !/\b(registered|account|deposit|id|17\d)\b/i.test(t);
  }
  return false;
}

export function isRegistrationConfirmed(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return (
    /\b(registered|registration done|account created|i registered|done registering)\b/i.test(t) ||
    /\b(waiting for the next step|next step)\b/i.test(t)
  );
}

export function isRegistrationPending(text: string): boolean {
  const t = (text || "").trim();
  return /\b(not yet|still registering|in progress|trying to register|its not registering|it'?s not registering|failing to register|couldn'?t manage|it refusing)\b/i.test(t);
}

export function isZmRegistrationAccountQuestion(text: string): boolean {
  const t = (text || "").trim().toLowerCase();
  if (!t) {
    return false;
  }
  return (
    /\b(which|what)\s+account\b/i.test(t) ||
    /\b(create|open|make|register)\s+(an?\s+)?account\b/i.test(t) ||
    /\baccount\b.{0,20}\b(create|open|register)\b/i.test(t) ||
    /\bhow\s+(do\s+i|to)\s+(create|open|register)\b/i.test(t)
  );
}

export function isRegistrationHelpRequest(text: string): boolean {
  const t = (text || "").trim();
  return (
    customerRequestsRegistrationMaterials(t) ||
    /\b(problem|issue|error|help).{0,40}(registration|register|account|instruction|instructions|link|steps)\b/i.test(
      t,
    ) ||
    /\b(registration|register|account|instruction|instructions|link|steps).{0,40}(problem|issue|error|help)\b/i.test(
      t,
    ) ||
    /\bscreenshot.{0,20}problem\b/i.test(t) ||
    REGISTRATION_HELP.test(t) ||
    /\b(it'?s taking me to 1xbet|i already have a 1xbet account|already have a 1xbet account|it refusing|failing to register|couldn'?t manage|with registration)\b/i.test(
      t,
    )
  );
}

export function classifyZmMessage(
  text: string,
  options?: {
    hasImage?: boolean;
    funnelStep?: number;
    messageReaction?: string;
  },
): ZmIntent {
  return classifyZmIntent(text, options);
}

/** Tier table pick: 30 / 50 / 100 / 200 ZMW or option 1–4. */
export function isZmTableDepositChoice(text: string): boolean {
  const t = normalizeDepositText(text);
  if (!t) {
    return false;
  }
  if (/^[1-4]\.?$/.test(t)) {
    return true;
  }
  if (/^(?:option|number|numero|n[o°]?)\s*[1-4]\.?$/i.test(t)) {
    return true;
  }
  const compact = t.replace(/\s+/g, "");
  if (/^(30|50|100|200)(?:zmw|kwacha|k)?\.?$/i.test(compact)) {
    return true;
  }
  if (t.split(/\s+/).length <= 14 && /\b(30|50|100|200)\s*(?:zmw|kwacha|k)\b/i.test(t)) {
    return true;
  }
  return false;
}

/** Custom deposit (e.g. «15 kwacha», «75») — not necessarily in the tier table. */
export function isZmCustomDepositAmountChoice(text: string): boolean {
  if (isZmTableDepositChoice(text)) {
    return false;
  }
  return isCustomMarketDepositAmount(text, ZM_CUSTOM_DEPOSIT_RULES);
}

export function isZmDepositAmountChoice(text: string): boolean {
  return isZmTableDepositChoice(text) || isZmCustomDepositAmountChoice(text);
}
