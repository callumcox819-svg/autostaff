import { isCustomerClarificationMessage, isLinkAccessProblemMessage } from "./customer-clarity.js";
import {
  clAgeQuestionSentInHistory,
  clScriptSentInHistory,
  depositSentInHistory,
  regLinkSentInHistory,
  stepsSentInHistory,
  tierSentInHistory,
} from "./cl-script-engine.js";
import {
  isAgeAnswer,
  isClientReadyPhrase,
  isDepositTierChoice,
  isReadyForRegistration,
  isRegistrationConfirmed,
  isClRegistrationHelpRequest,
  isRegistrationAccountQuestion,
  wantsRegistrationLink as clWantsRegistrationLink,
} from "./cl-intent.js";

/** Re-open mid-funnel CL chats when the customer gave a clear next-step signal (same rules as CM). */
export function clFunnelNeedsContinuation(
  customerText: string,
  outgoingTexts: string[],
  options?: { hasImage?: boolean },
): boolean {
  const text = (customerText || "").trim();
  if (options?.hasImage && regLinkSentInHistory(outgoingTexts)) {
    return true;
  }
  if (!text && !options?.hasImage) {
    return false;
  }
  if (isCustomerClarificationMessage(text)) {
    return true;
  }
  if (isLinkAccessProblemMessage(text)) {
    return true;
  }
  if (!text) {
    return false;
  }
  const introSent = clScriptSentInHistory(outgoingTexts, "01_intro");
  const ageSent = clAgeQuestionSentInHistory(outgoingTexts);
  const stepsSent = stepsSentInHistory(outgoingTexts);
  const tierSent = tierSentInHistory(outgoingTexts);
  const linkSent = regLinkSentInHistory(outgoingTexts);
  const depositSent = depositSentInHistory(outgoingTexts);
  const ready =
    isClientReadyPhrase(text) ||
    isReadyForRegistration(text) ||
    /^(oui|ok|okay|yes|si|sí|d'accord)\b/i.test(text) ||
    /intéresse|interes|interesa|investir|je veux|i'm interested/i.test(text);

  if (!introSent) {
    return true;
  }
  if (!ageSent) {
    return ready || /explique|comment|gagner|how|como|cómo/i.test(text);
  }
  if (!stepsSent) {
    return isAgeAnswer(text) || ready || /\d{1,2}\s*ans?\b/i.test(text);
  }
  if (!tierSent) {
    return ready || /applique|lien|link|aide|explique|comment|pr[eê]t|ready/i.test(text);
  }
  if (!linkSent) {
    return (
      isDepositTierChoice(text) ||
      isClRegistrationHelpRequest(text) ||
      isRegistrationAccountQuestion(text) ||
      clWantsRegistrationLink(text)
    );
  }
  if (!depositSent) {
    return (
      isRegistrationConfirmed(text) ||
      ready ||
      /inscrit|cr[eé][eé]|compte|d[eé]p[oô]t|deposit|application|voici|inscription|r[eé]ussie|registr/i.test(
        text,
      )
    );
  }
  return (
    isRegistrationConfirmed(text) ||
    /d[eé]p[oô]t|deposit|screenshot|preuve|image|inscrit|cr[eé][eé]/i.test(text)
  );
}
