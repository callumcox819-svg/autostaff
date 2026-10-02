import type { CountryCode } from "./config.js";
import type { AppEnv } from "./env.js";
import {
  getSupportFunnelConfig,
  hasPreSupportFunnelScripts,
  type SupportSnapshot,
} from "./ai-support-phase.js";
import { isCustomerClarificationMessage, isLinkAccessProblemMessage, isScamOrTrustQuestion, isCustomerSaysNotRegisteredYet } from "./customer-clarity.js";
import { isDepositTierChoice, isCmRegistrationHelpRequest, wantsRegistrationLink as cmWantsRegistrationLink } from "./cm-intent.js";
import { tierSentInHistory as cmTierSentInHistory, regLinkSentInHistory as cmRegLinkSentInHistory, depositSentInHistory as cmDepositSentInHistory } from "./cm-script-engine.js";
import {
  tierSentInHistory as clTierSentInHistory,
  regLinkSentInHistory as clRegLinkSentInHistory,
  depositSentInHistory as clDepositSentInHistory,
} from "./cl-script-engine.js";
import { isTrollDetectionCountry, shouldIgnoreTrollCustomer } from "./customer-troll.js";
import { explainScriptsSentInHistory as zmExplainScriptsSentInHistory } from "./zm-script-engine.js";
import { isZmDepositAmountChoice } from "./zm-intent.js";
import { explainScriptsSentInHistory as mgExplainScriptsSentInHistory } from "./mg-script-engine.js";
import { isMgOfferTableChoice } from "./mg-intent.js";
import { offerScriptsSentInHistory as djOfferScriptsSentInHistory } from "./dj-script-engine.js";
import { isDjOfferTableChoice } from "./dj-intent.js";
import {
  customerAgreedAfterOfferTable,
  customerRequestsRegistrationMaterials,
} from "./funnel-common.js";
import { isRegistrationHelpRequest, wantsRegistrationLink } from "./zm-intent.js";
import { looksLikeOwnScriptEcho } from "./funnel-outbound.js";
import {
  type AiAssistContext,
  type AiVisionContext,
  detectImageMimeType,
  maybeAiAssistReply,
  maybeAiAssistVision,
} from "./ai-assist.js";

export type AiAgentContext = AiAssistContext;

export { detectImageMimeType, maybeAiAssistVision, type AiVisionContext };

function funnelProgressForTrollGate(country: string, outgoing: string[]): boolean {
  if (country === "CL") {
    return (
      clTierSentInHistory(outgoing) ||
      clRegLinkSentInHistory(outgoing) ||
      clDepositSentInHistory(outgoing)
    );
  }
  if (country === "CM") {
    return (
      cmTierSentInHistory(outgoing) ||
      cmRegLinkSentInHistory(outgoing) ||
      cmDepositSentInHistory(outgoing)
    );
  }
  return false;
}

/** Pre-support: customer asked for link/instructions — funnel scripts must run, not AI. */
function customerWantsPreSupportRegistration(country: CountryCode, text: string): boolean {
  const t = text.trim();
  if (!t) {
    return false;
  }
  if (customerRequestsRegistrationMaterials(t) || customerAgreedAfterOfferTable(t)) {
    return true;
  }
  if (country === "CM") {
    return cmWantsRegistrationLink(t) || isCmRegistrationHelpRequest(t);
  }
  return wantsRegistrationLink(t) || isRegistrationHelpRequest(t);
}

/** Short «continue funnel» replies — scripts handle these, not the agent (pre-support only). */
const FUNNEL_ACK =
  /^(ok|okay|okey|yes|oui|d'accord|نعم|اه|آه|تمام|طيب|حاضر|mashi|mashy|👍|👌|✅|🔥)[.!\s]*$/iu;

/** Complex thread: agent helps; mechanical steps stay on scripts. */
export function isComplexCustomerMessage(text: string): boolean {
  const t = (text || "").trim();
  if (t.length >= 100) {
    return true;
  }
  if ((t.match(/\?/g)?.length ?? 0) >= 2) {
    return true;
  }
  if (
    t.length > 25 &&
    /(why|how come|pourquoi|comment ça|لماذا|ليه|ازاي|إزاي|but |لكن |mais |pero |не пон|не ясн)/i.test(t)
  ) {
    return true;
  }
  return false;
}

export function isSimpleFunnelAcknowledgment(text: string): boolean {
  const t = (text || "").trim();
  if (!t || t.length > 40) {
    return false;
  }
  return FUNNEL_ACK.test(t) || /^[\s👍👌✅🔥🙏😊🙂]+$/u.test(t);
}

/** Post-«в процессе» — reply only when the customer asked something, not «Ok» / «yes» spam. */
export function customerWantsSupportAgentReply(text: string, intent: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (isCustomerSaysNotRegisteredYet(t)) {
    return false;
  }
  if (intent === "declined") {
    return false;
  }
  if (isLinkAccessProblemMessage(t) || isScamOrTrustQuestion(t) || isCustomerClarificationMessage(t)) {
    return true;
  }
  if (isSimpleFunnelAcknowledgment(t)) {
    return false;
  }
  if (isComplexCustomerMessage(t)) {
    return true;
  }
  if (/\?/.test(t)) {
    return true;
  }
  if (intent === "question") {
    return true;
  }
  if (
    t.length <= 24 &&
    /^(ok|okay|yes|oui|d'accord|right now|hum|humm|we|n+|nn|merci|thanks|thank you|bye|salut|bonsoir|bonjour)\b/i.test(
      t,
    )
  ) {
    return false;
  }
  return t.length >= 20;
}

/**
 * AI Agent vs Scripts routing.
 * - Scripts: preset funnel (reg, link, deposit, ID, intro, steps).
 * - Support agent (post «в процессе»): handles coaching and complex messages for all countries.
 */
export function shouldUseAiAgent(ctx: AiAgentContext): boolean {
  if (ctx.agentTrigger) {
    return false;
  }
  if (isTrollDetectionCountry(ctx.country)) {
    const text = ctx.customerText.trim();
    if (
      text &&
      shouldIgnoreTrollCustomer(
        text,
        ctx.recentCustomerTexts ?? [],
        {
          hasFunnelProgress: funnelProgressForTrollGate(ctx.country, ctx.recentOutgoingTexts ?? []),
          latestHasImage: false,
        },
        ctx.funnelStep ?? 0,
      )
    ) {
      return false;
    }
  }
  if (ctx.forceSupportAgent) {
    return customerWantsSupportAgentReply(ctx.customerText.trim(), ctx.intent);
  }

  const text = ctx.customerText.trim();
  if (ctx.support?.active) {
    if (isCustomerSaysNotRegisteredYet(text)) {
      return false;
    }
    return customerWantsSupportAgentReply(text, ctx.intent);
  }

  if (!text) {
    return false;
  }
  if (ctx.intent === "declined") {
    return false;
  }
  if (!ctx.support?.active && customerWantsPreSupportRegistration(ctx.country, text)) {
    return false;
  }
  if (
    !ctx.support?.active &&
    hasPreSupportFunnelScripts(ctx.country, ctx.scriptKeys ?? [])
  ) {
    return false;
  }
  if (
    ctx.country === "CM" &&
    !ctx.support?.active &&
    isDepositTierChoice(ctx.customerText.trim()) &&
    cmTierSentInHistory(ctx.recentOutgoingTexts ?? [])
  ) {
    return false;
  }
  if (
    ctx.country === "ZM" &&
    !ctx.support?.active &&
    isZmDepositAmountChoice(ctx.customerText.trim()) &&
    zmExplainScriptsSentInHistory(ctx.recentOutgoingTexts ?? [])
  ) {
    return false;
  }
  // MG/DJ use CM language routing; block AI on table picks after the offer.
  if (
    ctx.country === "CM" &&
    !ctx.support?.active &&
    (isMgOfferTableChoice(ctx.customerText.trim()) ||
      isDjOfferTableChoice(ctx.customerText.trim()) ||
      isDepositTierChoice(ctx.customerText.trim())) &&
    (mgExplainScriptsSentInHistory(ctx.recentOutgoingTexts ?? []) ||
      djOfferScriptsSentInHistory(ctx.recentOutgoingTexts ?? []))
  ) {
    return false;
  }
  // Pre-support: positive / interested funnel replies are scripts, not the agent.
  if (
    !ctx.support?.active &&
    ["interested", "positive", "ready"].includes(ctx.intent) &&
    !isComplexCustomerMessage(text) &&
    !isScamOrTrustQuestion(text) &&
    !isLinkAccessProblemMessage(text) &&
    !isCustomerClarificationMessage(text)
  ) {
    return false;
  }
  if (isSimpleFunnelAcknowledgment(text)) {
    return false;
  }
  if (isScamOrTrustQuestion(text)) {
    return true;
  }
  if (isLinkAccessProblemMessage(text)) {
    return true;
  }
  if (isCustomerClarificationMessage(text)) {
    return true;
  }
  if (isComplexCustomerMessage(text)) {
    return true;
  }
  if (
    (ctx.intent === "question" || ctx.intent === "unknown") &&
    !isSimpleFunnelAcknowledgment(text)
  ) {
    return true;
  }
  if (!ctx.scriptKeys?.length && text.length >= 4) {
    return true;
  }
  return false;
}

export async function runAiAgentTextTurn(
  env: AppEnv,
  ctx: AiAgentContext,
): Promise<string | undefined> {
  if (!env.AI_ENABLED || !env.AI_API_KEY?.trim()) {
    return undefined;
  }
  if (!shouldUseAiAgent(ctx)) {
    return undefined;
  }
  return maybeAiAssistReply(env, ctx);
}

export function shouldUseAiAgentForImage(options: {
  proofKind: string;
  caption: string;
  support?: SupportSnapshot;
  country?: CountryCode;
  outgoingTexts?: string[];
  ocrCombinedText?: string;
}): boolean {
  const echoText = [options.ocrCombinedText, options.caption].filter(Boolean).join("\n");
  if (
    options.country &&
    looksLikeOwnScriptEcho(echoText, options.country, options.outgoingTexts)
  ) {
    return false;
  }
  if (options.support?.active) {
    if (
      options.proofKind === "registration_screenshot" ||
      options.proofKind === "id_screenshot" ||
      options.proofKind === "deposit_balance_screenshot" ||
      options.proofKind === "unclear_screenshot"
    ) {
      return true;
    }
    if (!options.caption.trim()) {
      return true;
    }
    if (isCustomerClarificationMessage(options.caption)) {
      return true;
    }
    return false;
  }
  if (options.proofKind === "unclear_screenshot") {
    return true;
  }
  if (options.proofKind === "registration_screenshot") {
    return true;
  }
  if (!options.caption.trim()) {
    return true;
  }
  if (isCustomerClarificationMessage(options.caption)) {
    return true;
  }
  return false;
}

export async function runAiAgentVisionTurn(
  env: AppEnv,
  ctx: AiVisionContext,
): Promise<string | undefined> {
  if (!env.AI_ENABLED || !env.AI_API_KEY?.trim()) {
    return undefined;
  }
  if (!shouldUseAiAgentForImage({
    proofKind: ctx.proofKind,
    caption: ctx.caption,
    support: ctx.support,
    country: ctx.country,
    outgoingTexts: ctx.outgoingTexts,
    ocrCombinedText: ctx.ocrCombinedText,
  })) {
    return undefined;
  }
  return maybeAiAssistVision(env, ctx);
}

export function supportSignalsFromOutgoing(
  country: CountryCode,
  outgoingTexts: string[],
): { regLinkSent: boolean; depositScriptSent: boolean } {
  const cfg = getSupportFunnelConfig(country);
  return {
    regLinkSent: cfg.regLinkSent(outgoingTexts),
    depositScriptSent: cfg.depositSent(outgoingTexts),
  };
}
