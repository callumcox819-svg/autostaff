import {
  type BotConfig,
  type ChannelConfig,
  type PlaybookConfig,
  type ProofKind,
  type Stage,
  type TemplateRole,
  getPlaybook,
  getTemplateBank,
} from "./config.js";
import {
  classifySpecialCustomerIntent,
  matchesPlaybookKeywords,
  normalizeCustomerText,
  specialIntentTemplateRole,
} from "./customer-intent.js";
import { isDisabledOutboundTemplateRole } from "./disabled-outbound-scripts.js";

export type ConversationEvent = {
  channelId: string;
  currentStage: Stage;
  latestCustomerText?: string;
  proofKind?: ProofKind;
};

export type DecisionResult = {
  nextStage: Stage;
  templateRole?: TemplateRole;
  templateToSend?: string;
  reason: string;
};

export function decideNextAction(
  config: BotConfig,
  channel: ChannelConfig,
  event: ConversationEvent,
): DecisionResult | undefined {
  if (!channel.enabled) {
    return undefined;
  }

  const playbook = getPlaybook(config, channel.country);
  const templateBank = getTemplateBank(config, channel.templateBank);

  if (event.proofKind) {
    const proofRule = playbook.proofRules.find((rule) => rule.kind === event.proofKind);
    if (proofRule) {
      return sanitizeDecision({
        nextStage: proofRule.nextStage,
        templateRole: proofRule.nextTemplateRole,
        templateToSend: proofRule.nextTemplateRole
          ? templateBank.roles[proofRule.nextTemplateRole]
          : undefined,
        reason: `Matched proof rule ${proofRule.kind}`,
      });
    }
    if (event.proofKind === "unclear_screenshot") {
      return sanitizeDecision({
        nextStage: "waiting_id",
        templateRole: "ask_clear_screenshot",
        templateToSend: templateBank.roles.ask_clear_screenshot,
        reason: "Unclear screenshot",
      });
    }
  }

  const text = event.latestCustomerText ?? "";
  // First touch (new_lead): never divert to no_money/deferral — intro script must go first.
  if (event.currentStage !== "new_lead") {
    const special = classifySpecialCustomerIntent(playbook, text);
    const specialRole = specialIntentTemplateRole(special);
    if (specialRole) {
      return sanitizeDecision({
        nextStage: special === "deferral" ? "not_ready" : "no_money",
        templateRole: specialRole,
        templateToSend: templateBank.roles[specialRole],
        reason: `Special intent ${special}`,
      });
    }
  }

  const normalizedText = normalizeCustomerText(text);
  if (!normalizedText) {
    return undefined;
  }

  for (const rule of playbook.textRules) {
    const matched = rule.matchAny.some((keyword) =>
      matchesPlaybookKeywords([keyword], normalizedText),
    );
    if (matched) {
      return sanitizeDecision({
        nextStage: rule.nextStage,
        templateRole: rule.nextTemplateRole,
        templateToSend: rule.nextTemplateRole
          ? templateBank.roles[rule.nextTemplateRole]
          : undefined,
        reason: `Matched text rule ${rule.name}`,
      });
    }
  }

  if (event.currentStage === "registered") {
    return sanitizeDecision({
      nextStage: "deposit_pending",
      templateRole: "deposit",
      templateToSend: templateBank.roles.deposit,
      reason: "Registered stage defaulted to deposit instructions",
    });
  }

  if (event.currentStage === "new_lead") {
    return sanitizeDecision({
      nextStage: "engaged",
      templateRole: "intro",
      templateToSend: templateBank.roles.intro,
      reason: "New lead — send intro preset",
    });
  }

  return undefined;
}

function sanitizeDecision(decision: DecisionResult): DecisionResult {
  if (!decision.templateRole || !isDisabledOutboundTemplateRole(decision.templateRole)) {
    return decision;
  }
  return {
    nextStage: decision.nextStage,
    reason: `${decision.reason} (telegram template blocked)`,
  };
}

export function inferProofKindFromCaption(
  playbook: PlaybookConfig,
  captionOrMessage?: string,
): ProofKind | undefined {
  const normalizedText = normalizeCustomerText(captionOrMessage);
  if (!normalizedText) {
    return undefined;
  }

  if (matchesPlaybookKeywords(playbook.depositKeywords, normalizedText)) {
    return "deposit_balance_screenshot";
  }

  if (matchesPlaybookKeywords(playbook.registrationKeywords, normalizedText)) {
    return "registration_screenshot";
  }

  return undefined;
}
