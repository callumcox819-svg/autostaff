import { readFileSync } from "node:fs";
import {
  type BotConfig,
  type ChannelConfig,
  type CountryCode,
  type Stage,
  getChannelConfig,
  getConfigEnabledChannelIds,
  isChannelConfigured,
  getPlaybook,
  resolveYamlTemplateBankName,
  statusMapForCountry,
} from "./config.js";
import { decideNextAction } from "./decision-engine.js";
import {
  customerWantsSupportAgentReply,
  isComplexCustomerMessage,
  runAiAgentTextTurn,
  runAiAgentVisionTurn,
  detectImageMimeType,
} from "./ai-agent.js";
import { RW_AI_COUNTRY } from "./ai-country-language.js";
import {
  cmVisionExtractToCombinedText,
  maybeAiVisionExtractCmProof,
} from "./ai-assist.js";
import { extractCmClientLoginId17 } from "./cm-proof.js";
import { looksLikeOwnScriptEcho } from "./funnel-outbound.js";
import { isLinkAccessProblemMessage, isCustomerClarificationMessage, isScamOrTrustQuestion } from "./customer-clarity.js";
import {
  coerceMelbetCountry,
  folderMarketLanguage,
  isFolderMarket,
  isFolderOnlyCountry,
  folderRegistrationLinkWasSent,
  planFolderPresetAdvance,
  planMissingRegistrationLink,
  type PresetBubble,
} from "./folder-presets.js";
import {
  defaultCountryForChannelName,
  isClChannelName,
  isDjChannelName,
  isJoChannelName,
  isMgChannelName,
  resolveWorkerCountryForChannel,
  type WorkerCountry,
} from "./rw-learn.js";
import {
  isInProgressStatusConversation,
  isIgnoreStatusConversation,
  findIgnoreStatusId,
  isConversationInOperatorEnabledFolders,
  isConversationInAiEnabledFolders,
} from "./status-folders.js";
import {
  isTrollDetectionCountry,
  shouldIgnoreTrollCustomer,
} from "./customer-troll.js";
import {
  buildInProgressFollowUpStatePatch,
  classifyInProgressRegistrationReply,
  hasCustomerIncomingAfter,
  hasManualOperatorReplyAfterInProgress,
  resolveRecentInProgressEnteredAtMs,
  inProgressFollowUpAlreadySent,
  inProgressFollowUpMessage,
  isInProgressFollowUpAttemptCoolingDown,
  isInProgressFollowUpExpired,
  inProgressPlanAskAlreadySent,
  inProgressPlanAskMessage,
  isInProgressBotMuted,
  isInProgressFollowUpCountry,
  latestIncomingCustomerText,
  shouldHandleInProgressFollowUpCustomerReply,
  shouldQueueInProgressFollowUp,
  shouldSendInProgressFollowUp,
} from "./in-progress-followup.js";
import {
  buildSupportSnapshot,
  filterScriptKeysForSupportAgent,
  inProgressFollowUpEligible,
  supportAgentSkipsEarlyAi,
} from "./ai-support-phase.js";
import {
  assessReplyEligibility,
  conversationPriorityScore,
  findLatestIncomingMessage,
  hasBotReplyAfterCustomerMessage,
  hasUnreadMarkers,
  isFreshCustomerMessage,
  isNewLeadConversation,
  recentCustomerMessageTexts,
  shouldProcessConversation,
  shouldQueueEgConversation,
  cmFunnelNeedsContinuation,
  zmFunnelNeedsContinuation,
  isActionableCustomerMessage,
  shouldQueueCmConversation,
  shouldQueueClConversation,
  shouldQueueZmConversation,
  shouldQueueMgConversation,
  shouldQueueDjConversation,
  shouldQueueJoConversation,
  shouldSkipConversationBotSpokeLast,
  isCatchUpReadActive,
  shouldQueueCatchUpConversation,
} from "./conversation-reply.js";
import {
  classifySpecialCustomerIntent,
  moneyRefusalText,
  phoneChatOnlyText,
  specialIntentTemplateRole,
} from "./customer-intent.js";
import { ocrLangForCountry } from "./ocr-lang.js";
import {
  classifyCmMessage,
  cmScriptSentInHistory,
  collectOutgoingTexts as collectCmOutgoingTexts,
  funnelStepFromScriptGaps as cmFunnelStepFromScriptGaps,
  inferStepFromThread as cmInferStepFromThread,
  regLinkSentInHistory as cmRegLinkSentInHistory,
  cmStatusMoveAfterSend,
  resolveCmFunnelScripts,
  limitCmScriptsForCustomerTurn,
  cmAllowsMultiSend,
  CM_REG_SEND_KEYS,
  tierSentInHistory,
  depositSentInHistory as cmDepositSentInHistory,
} from "./cm-script-engine.js";
import {
  classifyEgMessage,
  collectOutgoingTexts as collectEgOutgoingTexts,
  egFunnelNeedsContinuation,
  egFullRegistrationInstructionsSentInHistory,
  egIntroSentInHistory,
  egScriptSentInHistory,
  isEgScriptTextAcceptable,
  explainScriptsSentInHistory,
  funnelStepFromScriptGaps as egFunnelStepFromScriptGaps,
  inferStepFromThread as egInferStepFromThread,
  regLinkSentInHistory as egRegLinkSentInHistory,
  regSendTriggersInProgress as egRegSendTriggersInProgress,
  resolveEgFunnelScripts,
  resolveEgBacklogFallback,
  limitEgScriptsForCustomerTurn,
  egAllowsMultiSend,
  depositSentInHistory as egDepositSentInHistory,
} from "./eg-script-engine.js";
import {
  classifyRwMessage,
  collectRwOutgoingTexts,
  hasMinimumRwScriptDrafts,
  limitRwScriptsForCustomerTurn,
  resolveRwFunnelScripts,
  rwActiveScriptDrafts,
  rwAllowsMultiSend,
  rwFunnelStepFromScriptGaps,
  rwRegLinkSentInHistory,
  rwScriptSentInHistory,
  rwScriptText,
  rwStatusMoveAfterSend,
  RW_SCRIPT_KEYS,
  type RwScriptKey,
} from "./rw-script-engine.js";
import {
  classifyZmMessage,
  collectOutgoingTexts as collectZmOutgoingTexts,
  explainScriptsSentInHistory as zmExplainScriptsSentInHistory,
  funnelStepFromScriptGaps as zmFunnelStepFromScriptGaps,
  inferStepFromThread as zmInferStepFromThread,
  regLinkSentInHistory as zmRegLinkSentInHistory,
  resolveZmFunnelScripts,
  zmScriptSentInHistory,
  limitZmScriptsForCustomerTurn,
  zmAllowsMultiSend,
  zmStatusMoveTarget,
  type ZmStatusMoveTarget,
  ZM_EXPLAIN_SEND_KEYS,
  ZM_REG_SEND_KEYS,
  depositSentInHistory as zmDepositSentInHistory,
  gameIdSentInHistory,
} from "./zm-script-engine.js";
import {
  classifyMgMessage,
  collectOutgoingTexts as collectMgOutgoingTexts,
  explainScriptsSentInHistory as mgExplainScriptsSentInHistory,
  funnelStepFromScriptGaps as mgFunnelStepFromScriptGaps,
  inferStepFromThread as mgInferStepFromThread,
  limitMgScriptsForCustomerTurn,
  mgAllowsMultiSend,
  MG_FOLDER_NAME_HINTS,
  mgScriptSentInHistory,
  mgStatusMoveTarget,
  regLinkSentInHistory as mgRegLinkSentInHistory,
  depositSentInHistory as mgDepositSentInHistory,
  resolveMgFunnelScripts,
} from "./mg-script-engine.js";
import {
  isRegistrationHelpRequest as mgIsRegistrationHelpRequest,
  wantsRegistrationLink as mgWantsRegistrationLink,
  isMgDepositAmountChoice,
  isMgOfferTableChoice,
} from "./mg-intent.js";
import {
  classifyDjMessage,
  collectDjOutgoingTexts,
  DJ_FOLDER_NAME_HINTS,
  djAllowsMultiSend,
  djFunnelStepFromScriptGaps,
  djInferStepFromThread,
  djRegistrationInstructionsSentInHistory,
  djScriptSentInHistory,
  djStatusMoveTarget,
  limitDjScriptsForCustomerTurn,
  offerScriptsSentInHistory as djOfferScriptsSentInHistory,
  regLinkSentInHistory as djRegLinkSentInHistory,
  resolveDjFunnelScripts,
  nextDjRegScripts,
} from "./dj-script-engine.js";
import {
  isRegistrationHelpRequest as djIsRegistrationHelpRequest,
  wantsRegistrationLink as djWantsRegistrationLink,
  isDjDepositAmountChoice,
  isDjOfferTableChoice,
} from "./dj-intent.js";
import {
  classifyJoMessage,
  collectJoOutgoingTexts,
  explainScriptsSentInHistory as joExplainScriptsSentInHistory,
  JO_FOLDER_NAME_HINTS,
  joAllowsMultiSend,
  joFunnelStepFromScriptGaps,
  joInferStepFromThread,
  joScriptSentInHistory,
  joStatusMoveTarget,
  limitJoScriptsForCustomerTurn,
  nextJoRegScripts,
  regLinkSentInHistory as joRegLinkSentInHistory,
  resolveJoFunnelScripts,
} from "./jo-script-engine.js";
import {
  isRegistrationHelpRequest as joIsRegistrationHelpRequest,
  wantsRegistrationLink as joWantsRegistrationLink,
  isJoDepositAmountChoice,
  isJoOfferTableChoice,
} from "./jo-intent.js";
import { resolveScriptAttachment } from "./zm-script-assets.js";
import {
  looksLikeZmDepositBalanceScreenshot,
  resolveZmProofScriptAfterDeposit,
} from "./zm-proof.js";
import { extractProofImageUrl, resolveMessageReaction } from "./message-attachments.js";
import {
  isDepositTierChoice,
  isCmRegistrationHelpRequest,
  isRegistrationAccountQuestion,
  isRegistrationConfirmed,
  wantsRegistrationLink as cmWantsRegistrationLink,
} from "./cm-intent.js";
import { isEgDepositTierChoice, isEgJoinOrRegistrationQuestion } from "./eg-intent.js";
import { isZmRegistrationAccountQuestion, isReadyForRegistration as zmIsReadyForRegistration, isRegistrationHelpRequest as zmIsRegistrationHelpRequest, wantsRegistrationLink as zmWantsRegistrationLink, isZmDepositAmountChoice } from "./zm-intent.js";
import type { AppEnv } from "./env.js";
import {
  isIncomingDirection,
  isOutgoingDirection,
  isPagerSessionError,
  PagerApiError,
  PagerClient,
  type PagerConversation,
  type PagerMessage,
  resolveLastMessageAt,
} from "./pager-client.js";
import { buildPagerAccountPatch, ensurePagerSession, refreshPagerSessionWithCredentials } from "./pager-session.js";
import {
  classifyProofFromImage,
  classifyProofFromText,
  resolveCmProofScriptFromCombinedText,
} from "./proof-classifier.js";
import type {
  ChannelRuntimeState,
  ChatState,
  ConversationRuntimeState,
  StateStore,
} from "./state-store.js";
import { loadLocalCmScript } from "./cm-local-scripts.js";
import { loadLocalClScript } from "./cl-local-scripts.js";
import { resolveClReplyLanguage } from "./cl-language.js";
import { clFunnelNeedsContinuation } from "./cl-funnel-continuation.js";
import {
  classifyClMessage,
  clScriptSentInHistory,
  collectOutgoingTexts as collectClOutgoingTexts,
  funnelStepFromScriptGaps as clFunnelStepFromScriptGaps,
  inferStepFromThread as clInferStepFromThread,
  regLinkSentInHistory as clRegLinkSentInHistory,
  clStatusMoveAfterSend,
  resolveClFunnelScripts,
  limitClScriptsForCustomerTurn,
  clAllowsMultiSend,
  CL_REG_SEND_KEYS,
  tierSentInHistory as clTierSentInHistory,
  depositSentInHistory as clDepositSentInHistory,
} from "./cl-script-engine.js";
import {
  isDepositTierChoice as isClDepositTierChoice,
  isClRegistrationHelpRequest,
  isRegistrationAccountQuestion as isClRegistrationAccountQuestion,
} from "./cl-intent.js";
import { buildEgLinkOnlyMessage, buildEgRegistrationOnlyMessage, loadLocalEgScript, shouldBlockEgBareLinkSend } from "./eg-local-scripts.js";
import { getDeployLabel } from "./telegram-api.js";
import { loadLocalZmScript } from "./zm-local-scripts.js";
import { loadLocalMgScript, mgDefaultRegistrationLink } from "./mg-local-scripts.js";
import { loadLocalDjScript, djDefaultRegistrationLink } from "./dj-local-scripts.js";
import { loadLocalJoScript, joDefaultRegistrationLink } from "./jo-local-scripts.js";
import { resolveCmTemplateFolderId, resolveEgTemplateFolderId, resolveRwTemplateFolderId, resolveScriptTextByKey, resolveTemplateText, resolveZmTemplateFolderId } from "./template-resolver.js";
import { filterDisabledScriptKeys } from "./disabled-outbound-scripts.js";
import { customerAgreedAfterOfferTable } from "./funnel-common.js";
import {
  buildStatusFoldersFromPager,
  countApiStatusFolders,
  isClosedRegistrationStatusConversation,
  isFunnelFollowUpFolderName,
  isInProgressFollowUpFolderEnabled,
  ALL_INBOX_FOLDER_ID,
  NO_STATUS_FOLDER_ID,
  conversationAllowedInFolders,
  getEnabledFolderIds,
  hasEnabledStatusFolders,
  isNoStatusConversation,
  isZmInProgressRegistrationStatusName,
  isZmRegistrationCompleteStatusName,
  type StatusFolderState,
} from "./status-folders.js";
import type { TemplateRole } from "./config.js";
import type { TelegramApi } from "./telegram-api.js";

type WorkerDeps = {
  env: AppEnv;
  config: BotConfig;
  stateStore: StateStore;
  telegram: TelegramApi;
};

const MAX_SEND_FAILURES = 5;
const MAX_CONVERSATIONS_PER_ACCOUNT = 500;
const INBOX_TOP = 40;

function resolveConversationFolderGates(
  conv: PagerConversation,
  state: ChatState,
): { botFolderEnabled: boolean; aiFolderEnabled: boolean } {
  return {
    botFolderEnabled: isConversationInOperatorEnabledFolders(conv, state),
    aiFolderEnabled: isConversationInAiEnabledFolders(conv, state),
  };
}
/** Soft fill after unread sweep — read/in-progress follow-ups. */
const INBOX_TOP_CM_FOLLOWUP = 40;
/** Hard cap for unread/incoming so large backlogs still enter the queue. */
const INBOX_TOP_UNREAD = 400;
const INBOX_TOP_EG = 250;
const INBOX_PAGES_EG = 25;
/** Deep enough for large inboxes (2500+ chats) — do not stop until unread cap or end. */
const INBOX_PAGES_DEEP = 25;
/** Max no-status / read threads queued per cycle during «догнать чаты». */
const CATCH_UP_INBOX_CAP = 200;
/** Pages of the «Без статусу» filter to walk on catch-up (100 chats each). */
const CATCH_UP_NO_STATUS_PAGES = 20;

const operatorCyclesInFlight = new Set<number>();
const conversationsInFlight = new Set<string>();

export async function runPagerWorkerOnceForChat(deps: WorkerDeps, chatId: number): Promise<void> {
  const state = await deps.stateStore.get(chatId);
  if (!state) {
    return;
  }
  if (!state.pagerAccount?.cookies?.trim() && !(state.pagerAccount?.email && state.pagerAccount?.password)) {
    return;
  }
  await processOperatorAccount(deps, state);
}

export async function runPagerWorker(deps: WorkerDeps): Promise<never> {
  const pollMs = deps.config.bot.pollIntervalSeconds * 1000;
  console.log(`Pager worker started (every ${deps.config.bot.pollIntervalSeconds}s)`);
  if (deps.env.AI_ENABLED) {
    const key = deps.env.AI_API_KEY?.trim();
    const openRouterKey = key?.startsWith("sk-or-");
    const base = deps.env.AI_BASE_URL;
    console.log(
      `AI agent: enabled model=${deps.env.AI_MODEL} vision=${deps.env.AI_VISION_MODEL} base=${base}`,
    );
    if (openRouterKey && base.includes("api.openai.com")) {
      console.warn(
        "AI agent: OpenRouter key (sk-or-v1) but AI_BASE_URL points to OpenAI — set AI_BASE_URL=https://openrouter.ai/api/v1/chat/completions",
      );
    }
  }

  while (true) {
    const started = Date.now();
    try {
      await processPagerAccounts(deps);
    } catch (error) {
      console.error("Pager worker cycle failed:", error);
    }
    const elapsed = Date.now() - started;
    await sleep(Math.max(1000, pollMs - elapsed));
  }
}

async function processPagerAccounts(deps: WorkerDeps): Promise<void> {
  const states = await deps.stateStore.listAll();
  const connected = states.filter(
    (state) =>
      state.pagerAccount?.cookies?.trim() ||
      (state.pagerAccount?.email && state.pagerAccount?.password),
  );

  if (!connected.length) {
    console.log("Pager worker: no connected Pager accounts in state store");
    return;
  }

  const ordered = [...connected].sort((left, right) => {
    const leftEgCm = accountHasEgOrCm(left, deps.config);
    const rightEgCm = accountHasEgOrCm(right, deps.config);
    if (leftEgCm !== rightEgCm) {
      return leftEgCm ? -1 : 1;
    }
    return 0;
  });

  for (const state of ordered) {
    await processOperatorAccount(deps, state);
  }
}

function accountHasEgOrCm(state: ChatState, config: BotConfig): boolean {
  for (const channelId of collectEnabledChannelIdsFromState(state)) {
    const country =
      state.channels?.[channelId]?.country ??
      getChannelConfig(config, channelId)?.country ??
      inferCountryFromChannelName(
        state.pagerAccount?.liveChannels?.find((channel) => channel.id === channelId)?.name ?? "",
      );
    if (country === "EG" || country === "CM") {
      return true;
    }
  }
  return false;
}

function resolveEnabledFolderIds(
  state: ChatState,
  _enabledChannels: Array<{ runtime: { country: string } }>,
): Set<string> | null {
  return getEnabledFolderIds(state);
}

async function processOperatorAccount(deps: WorkerDeps, state: ChatState): Promise<void> {
  if (operatorCyclesInFlight.has(state.chatId)) {
    console.log(`Pager worker: chat ${state.chatId} — cycle already in flight, skip`);
    return;
  }
  operatorCyclesInFlight.add(state.chatId);
  try {
  let freshState = hydrateOperatorState((await deps.stateStore.get(state.chatId)) ?? state);

  if (freshState.paused) {
    console.log(`Pager worker: chat ${freshState.chatId} — paused (/reset_pause to resume)`);
    return;
  }

  const sessionResult = await ensurePagerSession(
    { env: deps.env, stateStore: deps.stateStore },
    freshState,
  );
  if (!sessionResult) {
    console.warn(
      `Pager worker: chat ${freshState.chatId} — no valid Pager session. Re-login via «Email + пароль» in the bot.`,
    );
    return;
  }

  freshState = hydrateOperatorState(sessionResult.state);
  let client = sessionResult.client;

  freshState = (await refreshLiveChannelsFromApi(deps, freshState, client)) ?? freshState;
  freshState = hydrateOperatorState(freshState);

  freshState = (await normalizeEnabledChannelsToConfig(deps, freshState)) ?? freshState;
  freshState = hydrateOperatorState(freshState);

  if (countApiStatusFolders(freshState.statusFolders) === 0) {
    freshState = (await ensureStatusFolders(deps, freshState, client)) ?? freshState;
    freshState = hydrateOperatorState(freshState);
  }

  freshState = hydrateOperatorState((await deps.stateStore.get(freshState.chatId)) ?? freshState);

  if (!collectEnabledChannelIdsFromState(freshState).length) {
    freshState = (await seedEnabledChannelsFromYaml(deps, freshState)) ?? freshState;
    freshState = hydrateOperatorState(freshState);
    console.log(
      `Pager worker: chat ${freshState.chatId} — enabled ${freshState.enabledChannelIds?.length ?? 0} channel(s) from config`,
    );
  }

  const enabledChannels = getEnabledChannels(deps.config, freshState);
  const liveCoverage = getLiveChannelCoverage(deps.config, freshState);
  const enabledEgChannels = enabledChannels.filter((item) => item.runtime.country === "EG");
  const enabledEgInState = collectEnabledChannelIdsFromState(freshState).filter((channelId) => {
    const country =
      freshState.channels?.[channelId]?.country ??
      getChannelConfig(deps.config, channelId)?.country ??
      inferCountryFromChannelName(
        freshState.pagerAccount?.liveChannels?.find((channel) => channel.id === channelId)?.name ?? "",
      );
    return country === "EG";
  });

  if (!enabledChannels.length) {
    const liveCount = freshState.pagerAccount?.liveChannels?.length ?? 0;
    console.log(
      `Pager worker: chat ${freshState.chatId} — no enabled channels (live=${liveCount}). Enable a folder in «Папки» or channels in «Каналы».`,
    );
    return;
  }

  await retryPendingInProgressMoves(deps, freshState, client, enabledChannels);
  freshState = hydrateOperatorState((await deps.stateStore.get(freshState.chatId)) ?? freshState);

  if (enabledEgInState.length && !enabledEgChannels.length) {
    console.error(
      `Pager worker: chat ${freshState.chatId} — Egypt channel enabled in settings but missing from poll list (${enabledEgInState.join(", ")}). Re-open «Каналы» and toggle Mahmoud Fathy.`,
    );
  }

  const enabledFolderIds = resolveEnabledFolderIds(freshState, enabledChannels);
  const hasCmChannel = enabledChannels.some((item) => item.runtime.country === "CM");
  const hasEgChannel = enabledChannels.some((item) => item.runtime.country === "EG");
  if (!enabledFolderIds || enabledFolderIds.size === 0) {
    console.warn(
      `Pager worker: chat ${freshState.chatId} — no personal status folders enabled; skip poll (enable folders in «Папки»)`,
    );
    return;
  }

  if (enabledFolderIds) {
    const folderNames = (
      freshState.operatorSettings?.statusFolders ??
      freshState.statusFolders ??
      []
    )
      .filter((folder) => folder.enabled)
      .map((folder) => folder.name)
      .join(", ");
    console.log(
      `Pager worker: chat ${freshState.chatId} — personal folders=[${folderNames}]`,
    );
  }

  const channelIds = enabledChannels.map((item) => item.channelId);
  const channelSummary = enabledChannels
    .map((item) => `${item.channelName}:${item.runtime.country}`)
    .join(", ");
  if (liveCoverage.missingFromLive.length) {
    console.warn(
      `Pager worker: chat ${freshState.chatId} — enabled channels missing from live session: ${liveCoverage.missingFromLive.join(", ")}`,
    );
  }

  let conversations: PagerConversation[] = [];
  try {
    const pollResult = await pollConversations(deps, freshState, client, channelIds);
    client = pollResult.client;
    conversations = pollResult.conversations;
  } catch (error) {
    console.error(
      `Pager poll failed for chat ${freshState.chatId} (orgId=${client.getOrganizationId().slice(0, 12) || "?"}):`,
      formatError(error),
    );
    return;
  }

  console.log(
    [
      `Pager worker: chat ${freshState.chatId}`,
      `channels=[${channelSummary}]`,
      `fetched=${conversations.length} conversations`,
      `egPoll=${enabledEgChannels.map((item) => item.channelName).join(",") || "none"}`,
    ].join(" | "),
  );

  logConversationCountsByChannel(enabledChannels, conversations, freshState.chatId);

  if (!conversations.length) {
    return;
  }

  const folderScopedConversations = conversations.filter((conv) => {
    const channelId = conv.channelId || conv.channel?.id || "";
    const runtime = enabledChannels.find((item) => item.channelId === channelId);
    const country = runtime?.runtime.country;
    const folderIds = resolveChannelEnabledFolderIds(
      enabledFolderIds,
      country,
      hasCmChannel,
      hasEgChannel,
    );
    if (!folderIds || folderIds.size === 0) {
      return false;
    }
    // «В процесі» — only if THIS operator enabled that folder (not via «Всі»).
    if (isInProgressStatusConversation(conv)) {
      const statusFolders =
        freshState.operatorSettings?.statusFolders ?? freshState.statusFolders;
      return isInProgressFollowUpFolderEnabled(conv, statusFolders);
    }
    return conversationAllowedInFolders(conv, folderIds);
  });
  const workQueueResult = await buildWorkQueue(
    client,
    folderScopedConversations,
    enabledChannels,
    channelIds,
    !enabledFolderIds || enabledFolderIds.size === 0 ? null : enabledFolderIds,
    hasCmChannel,
    hasEgChannel,
    freshState,
  );
  const workQueue = workQueueResult.conversations;
  const catchUpConversationIds = workQueueResult.catchUpConversationIds;
  const catchUpActive = isCatchUpReadActive(freshState.catchUpRead);
  const accountLimit = enabledChannels.some(
    (item) =>
      item.runtime.country === "EG" ||
      item.runtime.country === "CM" ||
      item.runtime.country === "ZM" ||
      item.runtime.country === "RW" ||
      item.runtime.country === "CL" ||
      item.runtime.country === "MG" ||
      item.runtime.country === "DJ" ||
      item.runtime.country === "JO" ||
      isFolderOnlyCountry(item.runtime.country),
  )
    ? Math.max(MAX_CONVERSATIONS_PER_ACCOUNT, INBOX_TOP_UNREAD + INBOX_TOP_CM_FOLLOWUP)
    : 150;
  const egChannelIds = new Set(enabledEgChannels.map((item) => item.channelId));
  const cmChannelIds = new Set(
    enabledChannels
      .filter((item) => item.runtime.country === "CM")
      .map((item) => item.channelId),
  );
  const prioritizedConversations = prioritizeWorkQueue(
    workQueue,
    channelIds,
    catchUpActive
      ? Math.max(accountLimit, catchUpConversationIds.size + 40)
      : accountLimit,
    egChannelIds,
    catchUpConversationIds,
  ).sort((left, right) => {
    // Interleave countries by priority — do not let EG starve a CM unread backlog.
    return conversationPriorityScore(right) - conversationPriorityScore(left);
  });
  const egInWork = workQueue.filter((conv) =>
    egChannelIds.has(conv.channelId || conv.channel?.id || ""),
  ).length;
  const cmUnreadInWork = workQueue.filter((conv) => {
    const channelId = conv.channelId || conv.channel?.id || "";
    if (!cmChannelIds.has(channelId)) {
      return false;
    }
    return (
      hasUnreadMarkers(conv) ||
      isIncomingDirection(conv.lastMessageDirection) ||
      isNewLeadConversation(conv)
    );
  }).length;
  const egUnreadInWork = workQueue.filter((conv) => {
    const channelId = conv.channelId || conv.channel?.id || "";
    if (!egChannelIds.has(channelId)) {
      return false;
    }
    return shouldQueueEgConversation(conv);
  }).length;
  console.log(
    `Pager worker: chat ${freshState.chatId} — workQueue=${workQueue.length}/${folderScopedConversations.length}/${conversations.length} egWork=${egInWork} egUnread=${egUnreadInWork} cmUnread=${cmUnreadInWork} prioritized=${prioritizedConversations.length}`,
  );

  let checked = 0;
  let replied = 0;
  let skipped = 0;
  let egChecked = 0;
  let egReplied = 0;

  let catchUpChecked = 0;
  let catchUpReplied = 0;

  for (const conv of prioritizedConversations) {
    const channelId = conv.channelId || conv.channel?.id;
    if (!channelId) {
      skipped += 1;
      continue;
    }

    const runtime = enabledChannels.find((item) => item.channelId === channelId);
    if (!runtime) {
      skipped += 1;
      continue;
    }

    checked += 1;
    if (catchUpConversationIds.has(conv.id)) {
      catchUpChecked += 1;
    }
    const isEg = runtime.runtime.country === "EG";
    if (isEg) {
      egChecked += 1;
    }
    try {
      const didReply = await processConversation(
        deps,
        freshState,
        client,
        conv,
        runtime,
        enabledFolderIds,
        hasCmChannel,
        hasEgChannel,
      );
      if (didReply) {
        replied += 1;
        if (catchUpConversationIds.has(conv.id)) {
          catchUpReplied += 1;
        }
        if (isEg) {
          egReplied += 1;
        }
      } else {
        skipped += 1;
      }
    } catch (error) {
      if (isRecoverablePagerError(error)) {
        console.warn(
          `Conversation ${conv.id.slice(0, 8)} hit recoverable Pager error for chat ${freshState.chatId}; refreshing session and retrying once`,
        );
        const refreshed = await refreshPagerSessionWithCredentials(deps, freshState);
        if (refreshed) {
          freshState = hydrateOperatorState(refreshed.state);
          client = refreshed.client;
          try {
            const didReply = await processConversation(
              deps,
              freshState,
              client,
              conv,
              runtime,
              enabledFolderIds,
              hasCmChannel,
              hasEgChannel,
            );
            if (didReply) {
              replied += 1;
              if (isEg) {
                egReplied += 1;
              }
            } else {
              skipped += 1;
            }
            continue;
          } catch (retryError) {
            console.error(
              `Conversation ${conv.id.slice(0, 8)} retry failed for chat ${freshState.chatId}:`,
              formatError(retryError),
            );
          }
        }
      }
      console.error(
        `Conversation ${conv.id.slice(0, 8)} failed for chat ${freshState.chatId}:`,
        formatError(error),
      );
    }
  }

  console.log(
    `Pager worker: chat ${freshState.chatId} — checked=${checked} replied=${replied} skipped=${skipped} egChecked=${egChecked} egReplied=${egReplied} catchUp=${catchUpChecked}/${catchUpReplied}`,
  );

  if (catchUpActive && !freshState.catchUpRead?.notifiedAt) {
    try {
      const report =
        catchUpChecked > 0
          ? [
              "Догон чатов (24 ч + «Без статусу» unread):",
              `в очереди ${catchUpChecked}, отправлено ответов ${catchUpReplied}.`,
              catchUpReplied < catchUpChecked
                ? "Остальные — без скрипта или уже отвечены в треде."
                : "",
            ]
              .filter(Boolean)
              .join("\n")
          : [
              "Догон: в poll/inbox не найдено чатов для очереди.",
              "Проверь: включена папка «Без статусу», каналы CM/EG/ZM/RW, unread на клиенте.",
            ].join("\n");
      await deps.telegram.sendMessage(freshState.chatId, report);
      await deps.stateStore.patch(freshState.chatId, {
        catchUpRead: {
          ...freshState.catchUpRead,
          activeUntil: freshState.catchUpRead?.activeUntil ?? new Date().toISOString(),
          notifiedAt: new Date().toISOString(),
        },
      });
    } catch (error) {
      console.warn(`Catch-up notify failed chat ${freshState.chatId}:`, formatError(error));
    }
  }
  } finally {
    operatorCyclesInFlight.delete(state.chatId);
  }
}

function prioritizeWorkQueue(
  conversations: PagerConversation[],
  channelIds: string[],
  limit: number,
  egChannelIds?: Set<string>,
  catchUpConversationIds?: Set<string>,
): PagerConversation[] {
  const scored = [...conversations].sort(
    (left, right) => conversationPriorityScore(right) - conversationPriorityScore(left),
  );
  const selected = new Map<string, PagerConversation>();

  if (catchUpConversationIds?.size) {
    for (const conv of scored) {
      if (!catchUpConversationIds.has(conv.id)) {
        continue;
      }
      selected.set(conv.id, conv);
    }
  }

  const minPerChannel = Math.min(
    50,
    Math.max(20, Math.floor(limit / Math.max(channelIds.length, 1))),
  );

  for (const channelId of channelIds) {
    let picked = 0;
    for (const conv of scored) {
      const convChannelId = conv.channelId || conv.channel?.id;
      if (convChannelId !== channelId || selected.has(conv.id)) {
        continue;
      }
      selected.set(conv.id, conv);
      picked += 1;
      if (picked >= minPerChannel) {
        break;
      }
    }
  }

  if (egChannelIds?.size) {
    let egPicked = 0;
    const egMin = Math.min(35, Math.max(15, Math.floor(limit / 4)));
    for (const conv of scored) {
      const convChannelId = conv.channelId || conv.channel?.id || "";
      if (!egChannelIds.has(convChannelId) || selected.has(conv.id)) {
        continue;
      }
      selected.set(conv.id, conv);
      egPicked += 1;
      if (egPicked >= egMin) {
        break;
      }
    }
  }

  for (const conv of scored) {
    if (selected.size >= limit) {
      break;
    }
    selected.set(conv.id, conv);
  }

  return [...selected.values()].sort(
    (left, right) => conversationPriorityScore(right) - conversationPriorityScore(left),
  );
}

function findLatestIncomingFromThread(
  messages: PagerMessage[],
  conv?: PagerConversation,
  country?: "ZM" | "CM" | "EG",
): PagerMessage | undefined {
  return findLatestIncomingMessage(messages, conv, undefined, country);
}

function inboxConversationEligible(
  conv: PagerConversation,
  enabledFolderIds: Set<string> | null,
): boolean {
  // Strict personal folder gate — never fall back to "any unread in org".
  if (!enabledFolderIds || enabledFolderIds.size === 0) {
    return false;
  }
  return conversationAllowedInFolders(conv, enabledFolderIds);
}

function resolveChannelEnabledFolderIds(
  enabledFolderIds: Set<string> | null,
  _country: WorkerCountry | undefined,
  _hasCmChannel: boolean,
  _hasEgChannel: boolean,
): Set<string> | null {
  // Personal settings only — do not auto-widen EG to «Всі».
  if (!enabledFolderIds || enabledFolderIds.size === 0) {
    return null;
  }
  return enabledFolderIds;
}

function noStatusFolderEnabled(enabledFolderIds: Set<string> | null): boolean {
  if (!enabledFolderIds?.size) {
    return false;
  }
  if (enabledFolderIds.has(NO_STATUS_FOLDER_ID)) {
    return true;
  }
  return enabledFolderIds.size === 1 && enabledFolderIds.has(ALL_INBOX_FOLDER_ID);
}

function isCatchUpChannelCountry(country: string | undefined): boolean {
  return (
    country === "CM" ||
    country === "EG" ||
    country === "ZM" ||
    country === "RW" ||
    country === "CL" ||
    country === "MG" ||
    country === "DJ" ||
    country === "JO" ||
    isFolderOnlyCountry(country ?? "")
  );
}

/** Page the «Без статусу» folder itself so old unread leads are not buried in the mixed inbox. */
async function collectNoStatusCatchUp(
  client: PagerClient,
  channelId: string,
  cap: number,
): Promise<PagerConversation[]> {
  const found: PagerConversation[] = [];
  for (const statusId of ["", "null"]) {
    let matchedFilter = false;
    for (let page = 1; page <= CATCH_UP_NO_STATUS_PAGES && found.length < cap; page += 1) {
      let batch: PagerConversation[];
      try {
        batch = await client.listConversations({
          channelId,
          page,
          pageSize: 100,
          statusId,
        });
      } catch (error) {
        console.warn(
          `Pager worker: no-status catch-up list failed channel ${channelId.slice(0, 8)} status=${statusId || "(empty)"}:`,
          error instanceof Error ? error.message : error,
        );
        break;
      }
      if (!batch.length) {
        break;
      }
      const noStatus = batch.filter((conv) => isNoStatusConversation(conv));
      if (noStatus.length < batch.length) {
        break;
      }
      matchedFilter = true;
      for (const conv of noStatus) {
        if (!shouldQueueCatchUpConversation(conv) || found.some((item) => item.id === conv.id)) {
          continue;
        }
        found.push(conv);
        if (found.length >= cap) {
          break;
        }
      }
      if (batch.length < 100) {
        break;
      }
    }
    if (matchedFilter) {
      return found;
    }
  }
  return found;
}

async function buildWorkQueue(
  client: PagerClient,
  folderScopedConversations: PagerConversation[],
  enabledChannels: EnabledChannel[],
  channelIds: string[],
  enabledFolderIds: Set<string> | null,
  hasCmChannel: boolean,
  hasEgChannel: boolean,
  chatState: ChatState,
): Promise<{ conversations: PagerConversation[]; catchUpConversationIds: Set<string> }> {
  const selected = new Map<string, PagerConversation>();
  const catchUpConversationIds = new Set<string>();
  const catchUpActive = isCatchUpReadActive(chatState.catchUpRead);
  let catchUpAdded = 0;

  if (catchUpActive && noStatusFolderEnabled(enabledFolderIds)) {
    for (const channel of enabledChannels) {
      if (catchUpAdded >= CATCH_UP_INBOX_CAP) {
        break;
      }
      if (!isFolderMarket(channel.runtime.country)) {
        continue;
      }
      const backlog = await collectNoStatusCatchUp(
        client,
        channel.channelId,
        CATCH_UP_INBOX_CAP - catchUpAdded,
      );
      for (const conv of backlog) {
        if (selected.has(conv.id)) {
          continue;
        }
        selected.set(conv.id, conv);
        catchUpConversationIds.add(conv.id);
        catchUpAdded += 1;
      }
    }
    if (catchUpAdded) {
      console.log(`Pager worker: catch-up no-status folder added=${catchUpAdded}`);
    }
  }

  if (catchUpActive) {
    for (const conv of folderScopedConversations) {
      if (catchUpAdded >= CATCH_UP_INBOX_CAP) {
        break;
      }
      const channelId = conv.channelId || conv.channel?.id || "";
      if (!channelIds.includes(channelId)) {
        continue;
      }
      const runtime = enabledChannels.find((item) => item.channelId === channelId);
      if (!runtime || !isCatchUpChannelCountry(runtime.runtime.country)) {
        continue;
      }
      const folderIds = resolveChannelEnabledFolderIds(
        enabledFolderIds,
        runtime.runtime.country,
        hasCmChannel,
        hasEgChannel,
      );
      if (folderIds && folderIds.size > 0 && !conversationAllowedInFolders(conv, folderIds)) {
        continue;
      }
      if (!shouldQueueCatchUpConversation(conv)) {
        continue;
      }
      if (!selected.has(conv.id)) {
        selected.set(conv.id, conv);
        catchUpConversationIds.add(conv.id);
        catchUpAdded += 1;
      }
    }
    if (catchUpAdded) {
      console.log(`Pager worker: catch-up pre-scan from poll added=${catchUpAdded}`);
    }
  }

  for (const channel of enabledChannels) {
    if (
      channel.runtime.country !== "CM" &&
      channel.runtime.country !== "EG" &&
      channel.runtime.country !== "ZM" &&
      channel.runtime.country !== "RW" &&
      channel.runtime.country !== "CL" &&
      channel.runtime.country !== "MG" &&
      channel.runtime.country !== "DJ" &&
      channel.runtime.country !== "JO" &&
      !isFolderOnlyCountry(channel.runtime.country)
    ) {
      continue;
    }
    const isEg = channel.runtime.country === "EG";
    const isCm = channel.runtime.country === "CM";
    const isCl = channel.runtime.country === "CL";
    const isZm = channel.runtime.country === "ZM";
    const isMg = channel.runtime.country === "MG";
    const isDj = channel.runtime.country === "DJ" || isFolderOnlyCountry(channel.runtime.country);
    const isJo = channel.runtime.country === "JO";
    const isRw = channel.runtime.country === "RW";
    const channelFolderIds = resolveChannelEnabledFolderIds(
      enabledFolderIds,
      channel.runtime.country,
      hasCmChannel,
      hasEgChannel,
    );
    const maxPages = isEg
      ? INBOX_PAGES_EG
      : catchUpActive && noStatusFolderEnabled(enabledFolderIds)
        ? Math.max(INBOX_PAGES_DEEP, 40)
        : INBOX_PAGES_DEEP;
    const pageSize = isEg ? 100 : 100;
    const unreadCap = isEg ? INBOX_TOP_EG : INBOX_TOP_UNREAD;
    const followUpCap = INBOX_TOP_CM_FOLLOWUP;
    let unreadAdded = 0;
    let followUpAdded = 0;
    let catchUpAddedChannel = 0;
    let scanned = 0;
    for (let page = 1; page <= maxPages; page += 1) {
      const inboxPage = await client.listConversations({
        channelId: channel.channelId,
        page,
        pageSize,
      });
      if (!inboxPage.length) {
        break;
      }
      scanned += inboxPage.length;
      let addedThisPage = 0;

      // Unread / customer-last first — never starve a deep backlog behind read noise.
      const ordered = [...inboxPage].sort(
        (left, right) => conversationPriorityScore(right) - conversationPriorityScore(left),
      );

      for (const conv of ordered) {
        if (!inboxConversationEligible(conv, channelFolderIds)) {
          continue;
        }

        if (
          (isCm || isCl || isZm || isMg || isDj || isJo || isRw || isEg) &&
          isInProgressStatusConversation(conv)
        ) {
          const statusFolders = chatState.operatorSettings?.statusFolders ?? chatState.statusFolders;
          if (!isInProgressFollowUpFolderEnabled(conv, statusFolders)) {
            continue;
          }
          // Only when «в процессе» itself is enabled — never piggy-back on «Без статусу».
          if (!inboxConversationEligible(conv, channelFolderIds)) {
            continue;
          }
          const followUpState = chatState.conversations?.[conv.id];
          if (followUpState && isInProgressBotMuted(followUpState)) {
            continue;
          }
          const dueFollowUp = shouldQueueInProgressFollowUp(followUpState);
          const needsCustomerReply =
            followUpState &&
            shouldHandleInProgressFollowUpCustomerReply(followUpState) &&
            (hasUnreadMarkers(conv) || isIncomingDirection(conv.lastMessageDirection));
          if (dueFollowUp || needsCustomerReply) {
            if (!selected.has(conv.id)) {
              selected.set(conv.id, conv);
              addedThisPage += 1;
            }
          }
          // Never fall through to early-funnel processing for in-progress via inbox scan.
          continue;
        }

        if (
          catchUpActive &&
          catchUpAdded < CATCH_UP_INBOX_CAP &&
          (isCm || isCl || isZm || isMg || isDj || isJo || isRw || isEg) &&
          shouldQueueCatchUpConversation(conv)
        ) {
          if (!selected.has(conv.id)) {
            selected.set(conv.id, conv);
            catchUpConversationIds.add(conv.id);
            catchUpAdded += 1;
            catchUpAddedChannel += 1;
            addedThisPage += 1;
          }
          continue;
        }

        if (isEg && !shouldQueueEgConversation(conv)) {
          continue;
        }
        if (isCl && !shouldQueueClConversation(conv)) {
          continue;
        }
        if (isCm && !shouldQueueCmConversation(conv)) {
          continue;
        }
        if (isZm && !shouldQueueZmConversation(conv)) {
          continue;
        }
        if (isMg && !shouldQueueMgConversation(conv)) {
          continue;
        }
        if (isDj && !shouldQueueDjConversation(conv)) {
          continue;
        }
        if (isJo && !shouldQueueJoConversation(conv)) {
          continue;
        }
        if (isRw && !shouldQueueZmConversation(conv)) {
          continue;
        }
        if (
          (isCm || isCl || isZm || isMg || isDj || isJo || isEg || isRw) &&
          isOutgoingDirection(conv.lastMessageDirection) &&
          !hasUnreadMarkers(conv)
        ) {
          // Never wake silent bot-last threads without an unread badge.
          continue;
        }
        if (selected.has(conv.id)) {
          continue;
        }

        const needsReply = isEg
          ? shouldQueueEgConversation(conv)
          : isCl
            ? shouldQueueClConversation(conv)
          : isCm
            ? shouldQueueCmConversation(conv)
            : isZm
              ? shouldQueueZmConversation(conv)
              : isMg
                ? shouldQueueMgConversation(conv)
                : isDj
                  ? shouldQueueDjConversation(conv)
                  : isJo
                    ? shouldQueueJoConversation(conv)
                : isRw
                ? shouldQueueZmConversation(conv)
                : hasUnreadMarkers(conv) ||
                isIncomingDirection(conv.lastMessageDirection) ||
                isNewLeadConversation(conv);

        if (needsReply) {
          if (unreadAdded >= unreadCap) {
            continue;
          }
          selected.set(conv.id, conv);
          unreadAdded += 1;
          addedThisPage += 1;
          continue;
        }

        if ((isCm || isCl || isZm || isMg || isDj || isJo || isRw) && followUpAdded < followUpCap) {
          const lastAt = resolveLastMessageAt(conv);
          if (
            !isInProgressStatusConversation(conv) ||
            !isFreshCustomerMessage(lastAt)
          ) {
            continue;
          }
          selected.set(conv.id, conv);
          followUpAdded += 1;
          addedThisPage += 1;
        }
      }

      const unreadFull = unreadAdded >= unreadCap;
      const followUpFull = followUpAdded >= followUpCap;
      const catchUpStillOpen =
        catchUpActive &&
        noStatusFolderEnabled(channelFolderIds) &&
        catchUpAdded < CATCH_UP_INBOX_CAP;
      if (unreadFull && followUpFull && !catchUpStillOpen) {
        break;
      }
      if (inboxPage.length < pageSize) {
        break;
      }
    }

    console.log(
      `Pager worker: channel ${channel.channelName}/${channel.runtime.country} inbox scanned=${scanned} unread=${unreadAdded} followUp=${followUpAdded} catchUp=${catchUpAddedChannel}`,
    );
  }

  for (const conv of folderScopedConversations) {
    const channelId = conv.channelId || conv.channel?.id || "";
    const runtime = enabledChannels.find((item) => item.channelId === channelId);
    const catchUpEligible =
      catchUpActive &&
      catchUpAdded < CATCH_UP_INBOX_CAP &&
      shouldQueueCatchUpConversation(conv);
    if (runtime?.runtime.country === "EG") {
      if (!shouldQueueEgConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "CL") {
      if (!shouldQueueClConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "CM") {
      if (!shouldQueueCmConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "ZM") {
      if (!shouldQueueZmConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "MG") {
      if (!shouldQueueMgConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "DJ" || isFolderOnlyCountry(runtime?.runtime.country ?? "")) {
      if (!shouldQueueDjConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "JO") {
      if (!shouldQueueJoConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (runtime?.runtime.country === "RW") {
      if (!shouldQueueZmConversation(conv) && !catchUpEligible) {
        continue;
      }
    } else if (!shouldProcessConversation(conv) && !catchUpEligible) {
      continue;
    }
    if (catchUpEligible && !selected.has(conv.id)) {
      selected.set(conv.id, conv);
      catchUpConversationIds.add(conv.id);
      catchUpAdded += 1;
      continue;
    }
    selected.set(conv.id, conv);
  }

  const channelsNeedingScan = enabledChannels.filter((channel) => {
    if (
      channel.runtime.country === "CM" ||
      channel.runtime.country === "EG" ||
      channel.runtime.country === "ZM"
    ) {
      return false;
    }
    const queued = [...selected.values()].filter(
      (conv) => (conv.channelId || conv.channel?.id) === channel.channelId,
    ).length;
    return queued === 0;
  });

  for (const channel of channelsNeedingScan) {
    if (channel.runtime.country === "ZM") {
      const inboxTop = (
        await client.listConversations({
          channelId: channel.channelId,
          page: 1,
          pageSize: 50,
        })
      ).sort(
        (left, right) => conversationPriorityScore(right) - conversationPriorityScore(left),
      );
      let addedForChannel = 0;
      for (const conv of inboxTop) {
        if (!enabledFolderIds || enabledFolderIds.size === 0) {
          continue;
        }
        if (isInProgressStatusConversation(conv)) {
          const statusFolders =
            chatState.operatorSettings?.statusFolders ?? chatState.statusFolders;
          if (!isInProgressFollowUpFolderEnabled(conv, statusFolders)) {
            continue;
          }
        } else if (!conversationAllowedInFolders(conv, enabledFolderIds)) {
          continue;
        }
        if (selected.has(conv.id)) {
          continue;
        }
        if (shouldProcessConversation(conv)) {
          selected.set(conv.id, conv);
          addedForChannel += 1;
        }
        if (addedForChannel >= INBOX_TOP) {
          break;
        }
      }
      if (addedForChannel) {
        console.log(
          `Pager worker: channel ${channel.channelName}/${channel.runtime.country} inbox top added=${addedForChannel}`,
        );
      }
      continue;
    }

    const recentHead = folderScopedConversations
      .filter((conv) => (conv.channelId || conv.channel?.id) === channel.channelId)
      .sort(
        (left, right) =>
          Date.parse(resolveLastMessageAt(right) ?? "") - Date.parse(resolveLastMessageAt(left) ?? ""),
      )
      .slice(0, 30);

    let addedForChannel = 0;
    for (const conv of recentHead) {
      if (selected.has(conv.id)) {
        continue;
      }
      if (shouldProcessConversation(conv)) {
        selected.set(conv.id, conv);
        addedForChannel += 1;
      }
    }
    if (addedForChannel) {
      console.log(
        `Pager worker: channel ${channel.channelName}/${channel.runtime.country} cached head added=${addedForChannel}`,
      );
    }
  }

  if (!selected.size && channelIds.length) {
    console.warn(
      `Pager worker: no actionable conversations after inbox scan (channels=${channelIds.length})`,
    );
  }

  return { conversations: [...selected.values()], catchUpConversationIds };
}

async function onMovedToInProgressRegistration(
  deps: WorkerDeps,
  chatId: number,
  convId: string,
  channelId: string,
  enteredAtMs?: number,
): Promise<void> {
  await patchConversationState(deps.stateStore, chatId, convId, {
    conversationId: convId,
    channelId,
    ...buildInProgressFollowUpStatePatch(convId, enteredAtMs ?? Date.now()),
    pendingInProgressMoveAt: undefined,
  });
}

async function onMovedToIgnore(
  deps: WorkerDeps,
  chatId: number,
  convId: string,
  channelId: string,
): Promise<void> {
  await patchConversationState(deps.stateStore, chatId, convId, {
    conversationId: convId,
    channelId,
    ignoredAt: new Date().toISOString(),
    inProgressFollowUpDueAt: undefined,
    inProgressMutedAt: new Date().toISOString(),
  });
}

async function trySendInProgressRegistrationFollowUp(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
): Promise<boolean> {
  const country = runtime.runtime.country;
  if (!isInProgressFollowUpCountry(country)) {
    return false;
  }
  if (!isInProgressStatusConversation(conv)) {
    return false;
  }
  if (isClosedRegistrationStatusConversation(conv)) {
    return false;
  }

  const statusFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  if (!isInProgressFollowUpFolderEnabled(conv, statusFolders)) {
    return false;
  }

  const convId = conv.id;
  let convState = getConversationState(state, convId, runtime.channelId);
  if (isInProgressBotMuted(convState)) {
    return false;
  }
  if (isInProgressFollowUpAttemptCoolingDown(convState)) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  const operatorId = await client.probeOperatorUserId();

  if (!convState.inProgressEnteredAt?.trim()) {
    const enteredMs = resolveRecentInProgressEnteredAtMs(convState, messages);
    if (enteredMs === null) {
      return false;
    }
    const schedulePatch = buildInProgressFollowUpStatePatch(convId, enteredMs);
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      ...schedulePatch,
    });
    convState = { ...convState, ...schedulePatch };
  }

  if (isInProgressFollowUpExpired(convState)) {
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      inProgressMutedAt: new Date().toISOString(),
    });
    return false;
  }

  const enteredAt = convState.inProgressEnteredAt?.trim();
  const enteredMs = enteredAt ? Date.parse(enteredAt) : Number.NaN;
  if (Number.isFinite(enteredMs) && hasCustomerIncomingAfter(messages, enteredMs, country)) {
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      inProgressMutedAt: new Date().toISOString(),
    });
    console.log(
      `Pager worker: ${country} ${convId.slice(0, 8)} in-progress follow-up skipped — customer already replied`,
    );
    return false;
  }

  if (
    enteredAt &&
    hasManualOperatorReplyAfterInProgress(messages, enteredAt, country, conv, operatorId || undefined)
  ) {
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      inProgressMutedAt: new Date().toISOString(),
      inProgressFollowUpSentAt: convState.inProgressFollowUpSentAt ?? new Date().toISOString(),
    });
    console.log(
      `Pager worker: ${country} ${convId.slice(0, 8)} in-progress muted — operator already replied`,
    );
    return false;
  }

  const outgoingTexts =
    country === "CM"
      ? collectCmOutgoingTexts(messages)
      : country === "CL"
        ? collectClOutgoingTexts(messages)
        : country === "ZM"
          ? collectZmOutgoingTexts(messages)
          : country === "MG"
            ? collectMgOutgoingTexts(messages)
          : country === "DJ"
            ? collectDjOutgoingTexts(messages)
          : country === "JO"
            ? collectJoOutgoingTexts(messages)
          : country === "EG"
            ? collectEgOutgoingTexts(messages)
            : collectRwOutgoingTexts(messages);

  if (inProgressPlanAskAlreadySent(country, outgoingTexts)) {
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      inProgressPlanAskSentAt: convState.inProgressPlanAskSentAt ?? new Date().toISOString(),
      inProgressMutedAt: new Date().toISOString(),
    });
    return false;
  }

  if (shouldHandleInProgressFollowUpCustomerReply(convState)) {
    return tryHandleInProgressFollowUpCustomerReply(
      deps,
      state,
      client,
      conv,
      runtime,
      messages,
      outgoingTexts,
    );
  }

  if (!shouldSendInProgressFollowUp(convState)) {
    return false;
  }

  if (inProgressFollowUpAlreadySent(country, outgoingTexts)) {
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      inProgressFollowUpSentAt: new Date().toISOString(),
    });
    return false;
  }

  const variant = convState.inProgressFollowUpVariant ?? 0;
  const text = inProgressFollowUpMessage(country, variant);
  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    inProgressFollowUpLastAttemptAt: new Date().toISOString(),
  });
  await tryTakeConversationForProcessing(client, convId, country);
  const sent = await client.sendMessageReliable(convId, text, {
    channelId: runtime.channelId,
    conv,
  });
  if (!sent) {
    return false;
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    inProgressFollowUpSentAt: new Date().toISOString(),
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: "in_progress_followup",
    sendFailures: 0,
  });
  console.log(
    `Pager worker: ${country} ${convId.slice(0, 8)} in-progress follow-up sent (variant=${variant})`,
  );
  return true;
}

async function tryHandleInProgressFollowUpCustomerReply(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  messages: PagerMessage[],
  outgoingTexts: string[],
): Promise<boolean> {
  const country = runtime.runtime.country;
  if (!isInProgressFollowUpCountry(country)) {
    return false;
  }
  const convId = conv.id;
  const customerText = latestIncomingCustomerText(messages);
  if (!customerText) {
    return false;
  }

  // Only react when the latest message is from the customer (they answered the ping).
  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const newest = sorted[0];
  if (!newest || !isIncomingDirection(newest.messageDirection)) {
    return false;
  }

  const kind = classifyInProgressRegistrationReply(country, customerText);
  if (kind === "not_yet") {
    if (inProgressPlanAskAlreadySent(country, outgoingTexts)) {
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        conversationId: convId,
        channelId: runtime.channelId,
        inProgressPlanAskSentAt: new Date().toISOString(),
        inProgressMutedAt: new Date().toISOString(),
      });
      return false;
    }
    const text = inProgressPlanAskMessage(country);
    await tryTakeConversationForProcessing(client, convId, country);
    const sent = await client.sendMessageReliable(convId, text, {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      return false;
    }
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      inProgressPlanAskSentAt: new Date().toISOString(),
      inProgressMutedAt: new Date().toISOString(),
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: "in_progress_plan_ask",
      sendFailures: 0,
    });
    console.log(`Pager worker: ${country} ${convId.slice(0, 8)} in-progress plan-ask sent`);
    return true;
  }

  // YES or other → mute, no more bot messages.
  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    inProgressMutedAt: new Date().toISOString(),
  });
  console.log(
    `Pager worker: ${country} ${convId.slice(0, 8)} in-progress muted after reply kind=${kind}`,
  );
  return false;
}

async function processConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  enabledFolderIds: Set<string> | null,
  hasCmChannel: boolean,
  hasEgChannel: boolean,
): Promise<boolean> {
  if (conversationsInFlight.has(conv.id)) {
    console.log(`Pager worker: skip ${conv.id.slice(0, 8)} — already processing`);
    return false;
  }
  conversationsInFlight.add(conv.id);
  try {
  const channelFolderIds = resolveChannelEnabledFolderIds(
    enabledFolderIds,
    runtime.runtime.country,
    hasCmChannel,
    hasEgChannel,
  );

  // List payloads often omit status — refresh before the folder gate.
  let workingConv = conv;
  try {
    const opened = await client.openConversation(conv.id);
    if (opened) {
      workingConv = opened;
    }
  } catch {
    // keep list snapshot
  }

  if (
    !channelFolderIds ||
    channelFolderIds.size === 0 ||
    !conversationAllowedInFolders(workingConv, channelFolderIds)
  ) {
    // «В процесі» may still be allowed when that folder is explicitly enabled even if
    // «Всі» is off — conversationAllowedInFolders already checks status id.
    if (
      !(
        isInProgressStatusConversation(workingConv) &&
        isInProgressFollowUpFolderEnabled(
          workingConv,
          state.operatorSettings?.statusFolders ?? state.statusFolders,
        )
      )
    ) {
      console.log(
        `Pager worker: skip ${conv.id.slice(0, 8)} chat=${state.chatId} — outside YOUR folders (status=${workingConv.status?.name || "none"})`,
      );
      return false;
    }
  }

  if (isIgnoreStatusConversation(workingConv)) {
    console.log(
      `Pager worker: skip ${conv.id.slice(0, 8)} — ignore folder (status=${workingConv.status?.name || "none"})`,
    );
    return false;
  }

  const convStateEarly = getConversationState(state, workingConv.id, runtime.channelId);
  if (convStateEarly.ignoredAt) {
    console.log(`Pager worker: skip ${conv.id.slice(0, 8)} — troll ignored`);
    return false;
  }

  // Strict: in-progress follow-up only when THAT operator enabled the folder (not «Всі»).
  const statusFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  if (
    isInProgressStatusConversation(workingConv) &&
    !isInProgressFollowUpFolderEnabled(workingConv, statusFolders)
  ) {
    console.log(
      `Pager worker: skip ${conv.id.slice(0, 8)} chat=${state.chatId} — «в процесі» not enabled for this operator`,
    );
    return false;
  }

  if (await trySendInProgressRegistrationFollowUp(deps, state, client, workingConv, runtime)) {
    return true;
  }

  // In-progress muted / operator-owned — never run scripts or AI.
  const mutedState = getConversationState(state, workingConv.id, runtime.channelId);
  if (isInProgressStatusConversation(workingConv) && isInProgressBotMuted(mutedState)) {
    return false;
  }
  if (isInProgressStatusConversation(workingConv)) {
    // Stay in follow-up lane only — no early funnel / AI while folder is «в процессе».
    return false;
  }

  const channel = buildRuntimeChannelConfig(deps.config, state, runtime);
  const workerCountry = runtime.runtime.country;
  if (!isFolderMarket(workerCountry)) {
    console.log(
      `Pager worker: skip ${workingConv.id.slice(0, 8)} country=${workerCountry} — Melbet only (pick MR/DJ/BF/CM/BJ/CR/SN)`,
    );
    return false;
  }
  if (workerCountry === "DJ") {
    return processDjConversation(deps, state, client, workingConv, runtime, channel);
  }
  if (workerCountry === "CM") {
    return processCmConversation(deps, state, client, workingConv, runtime, channel);
  }
  return processFolderMarketConversation(deps, state, client, workingConv, runtime, channel);
  } finally {
    conversationsInFlight.delete(conv.id);
  }
}

/** RW: авто-воронка (встроенные скрипты, как ZM). */
async function processRwConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  if (!deps.env.RW_FUNNEL_ENABLED || !hasMinimumRwScriptDrafts()) {
    return false;
  }
  if (!isNoStatusConversation(conv) && !isInProgressStatusConversation(conv)) {
    return false;
  }
  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const drafts = rwActiveScriptDrafts(currentState.rwLearning?.scriptDrafts);
  return processRwFunnelConversation(deps, currentState, client, conv, runtime, channel, drafts);
}

async function processRwFunnelConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
  drafts: ReturnType<typeof rwActiveScriptDrafts>,
): Promise<boolean> {
  const convId = conv.id;
  const convState = getConversationState(state, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingMessage(sorted, conv, undefined, RW_AI_COUNTRY);
  if (!lastIncoming) {
    return false;
  }

  const operatorUserId = await client.probeOperatorUserId();
  const outgoingTexts = collectRwOutgoingTexts(messages);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const rwNewLeadBypass =
    isNoStatusConversation(conv) &&
    !rwScriptSentInHistory(outgoingTexts, "01_intro", drafts) &&
    Boolean(latestCustomerText);

  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(conv, state);
  const support = buildSupportSnapshot(RW_AI_COUNTRY, isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const rwInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, false) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId,
      country: RW_AI_COUNTRY,
      catchUpRead: isCatchUpReadActive(state.catchUpRead),
    })
  ) {
    console.log(`Pager worker: skip ${convId.slice(0, 8)} RW — bot_spoke_last (awaiting_customer)`);
    return false;
  }

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: rwNewLeadBypass || rwInProgressBypass,
        operatorUserId,
        countryLabel: "RW",
        catchUpRead: isCatchUpReadActive(state.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const playbook = getPlaybook(deps.config, channel.country);

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  const gapStep = rwFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0, drafts);
  const effectiveStep = Math.max(gapStep, convState.funnelStep ?? 0);
  const intent = classifyRwMessage(latestCustomerText, effectiveStep, outgoingTexts, drafts);
  let scriptKeys = resolveRwFunnelScripts(
    effectiveStep,
    latestCustomerText,
    intent,
    outgoingTexts,
    drafts,
    { recentCustomerTexts },
  );
  scriptKeys = limitRwScriptsForCustomerTurn(scriptKeys, outgoingTexts, drafts);
  scriptKeys = filterScriptKeysForSupportAgent(RW_AI_COUNTRY, scriptKeys, latestCustomerText, support).filter(
    (key): key is RwScriptKey => RW_SCRIPT_KEYS.includes(key as RwScriptKey),
  );
  const skipEarlySupportAi = supportAgentSkipsEarlyAi(RW_AI_COUNTRY, scriptKeys, support);

  if (scriptKeys.length) {
    scriptKeys = (await dropScriptKeysAlreadyInThread(client, convId, "RW", scriptKeys, drafts)).filter(
      (key): key is RwScriptKey => RW_SCRIPT_KEYS.includes(key as RwScriptKey),
    );
    if (!scriptKeys.length) {
      console.log(`Pager worker: RW ${convId.slice(0, 8)} — scripts already in thread`);
      return false;
    }
    await tryTakeConversationForProcessing(client, convId, "RW");

    console.log(
      `Pager worker: RW ${convId.slice(0, 8)} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}]`,
    );

    const folderId = await resolveRwTemplateFolderId(
      client,
      runtime.runtime.templateBankId,
      state.pagerAccount?.liveTemplateBanks,
    );

    const allowMultiSend = rwAllowsMultiSend(scriptKeys);
    let sentAny = false;
    const sentScriptKeys: string[] = [];

    for (const scriptKey of scriptKeys) {
      const replyText =
        (await resolveScriptTextByKey(client, {
          folderId,
          liveBanks: state.pagerAccount?.liveTemplateBanks,
          scriptKey,
          country: "RW",
          refreshSavedReplies: true,
        })) ?? rwScriptText(scriptKey, drafts);
      if (!replyText?.trim()) {
        console.warn(
          `Pager worker: RW script missing folder=${folderId?.slice(0, 8) ?? "?"} key=${scriptKey} liveBanks=${state.pagerAccount?.liveTemplateBanks?.map((bank) => bank.name).join(",") ?? "none"}`,
        );
        continue;
      }

      const sent = await client.sendMessageReliable(convId, replyText.trim(), {
        channelId: runtime.channelId,
        conv,
      });
      if (!sent) {
        const failures = (convState.sendFailures ?? 0) + 1;
        await patchConversationState(deps.stateStore, state.chatId, convId, {
          sendFailures: failures,
        });
        console.error(`Pager worker: RW send failed ${convId.slice(0, 8)} key=${scriptKey}`);
        return sentAny;
      }
      sentAny = true;
      sentScriptKeys.push(scriptKey);
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        conversationId: convId,
        channelId: runtime.channelId,
        lastCustomerMessageId: lastIncoming.id,
        lastCustomerMessageAt: lastIncoming.createdAt,
        lastReplyAt: new Date().toISOString(),
        lastReplyRole: scriptKey,
        sendFailures: 0,
      });
      await sleep(500);
      if (!allowMultiSend) {
        break;
      }
    }

    if (!sentAny) {
      return false;
    }

    if (rwStatusMoveAfterSend(sentScriptKeys)) {
      const statusId = findZmStatusId(state, "in_progress_registration");
      const operatorId = await client.probeOperatorUserId();
      const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
      if (statusId && operatorId && currentStatusId !== statusId) {
        try {
          await client.patchConversationStatus(convId, statusId, operatorId);
          console.log(`Pager worker: RW ${convId.slice(0, 8)} status -> in progress`);
          await onMovedToInProgressRegistration(deps, state.chatId, convId, runtime.channelId);
        } catch (error) {
          console.warn(`Pager worker: status patch failed ${convId.slice(0, 8)}:`, formatError(error));
        }
      }
    }

    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      currentStage: rwRegLinkSentInHistory(
        [...outgoingTexts, ...sentScriptKeys.map((k) => drafts?.[k as RwScriptKey]?.text ?? "")],
        drafts,
      )
        ? "engaged"
        : "new_lead",
      funnelStep: Math.max(effectiveStep, sentScriptKeys.includes("05_link") ? 4 : effectiveStep),
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: sentScriptKeys[sentScriptKeys.length - 1],
      sendFailures: 0,
    });

    return true;
  }

  if (!skipEarlySupportAi && deps.env.AI_ENABLED) {
    const aiHandledEarly = await tryRunAiAgentTurn(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: RW_AI_COUNTRY,
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
        aiFolderEnabled,
      },
    );
    if (aiHandledEarly) {
      return true;
    }
  }

  if (
    deps.env.AI_ENABLED &&
    (await trySupportAgentWhenNoScripts(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: RW_AI_COUNTRY,
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
      },
    ))
  ) {
    return true;
  }
  console.log(
    `Pager worker: skip ${convId.slice(0, 8)} RW — no script (step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
  );
  return false;
}

async function processCmConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const outgoingTexts = collectCmOutgoingTexts(messages);
  await maybeEnsureInProgressAfterRegLink(
    deps,
    currentState,
    client,
    conv,
    convId,
    runtime.channelId,
    "CM",
    outgoingTexts,
    cmRegLinkSentInHistory,
  );

  // Operator enabled «Без статусу» only → never script/AI chats already in «в процессе».
  if (
    !isNoStatusConversation(conv) &&
    !isConversationInOperatorEnabledFolders(conv, currentState)
  ) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} CM — folder not enabled (status=${conv.status?.name || "none"})`,
    );
    return false;
  }

  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "CM");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "CM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    if (
      await trySendMissingRegistrationLink(
        deps,
        state,
        client,
        conv,
        runtime,
        convId,
        convState,
        outgoingTexts,
      )
    ) {
      return true;
    }
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} CM — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }

  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);

  if (
    await tryHandleTrollCustomerToIgnore(
      deps,
      currentState,
      client,
      conv,
      runtime,
      convState,
      convId,
      "CM",
      latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      convState.funnelStep ?? 0,
      Boolean(extractProofImageUrl(lastIncoming)),
    )
  ) {
    return true;
  }

  const tierChosenRecently = recentCustomerTexts.some((line) => isDepositTierChoice(line));
  const awaitingRegAfterTierChoice =
    tierSentInHistory(outgoingTexts) &&
    !cmRegLinkSentInHistory(outgoingTexts) &&
    (isDepositTierChoice(latestCustomerText) ||
      tierChosenRecently ||
      isRegistrationAccountQuestion(latestCustomerText) ||
      isCmRegistrationHelpRequest(latestCustomerText));
  const cmNewLeadBypass =
    isNoStatusConversation(conv) &&
    !cmScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const operatorUserId = operatorUserIdEarly;

  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("CM", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const cmInProgressFollowUp =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: awaitingRegAfterTierChoice || cmNewLeadBypass || cmInProgressFollowUp,
        operatorUserId,
        countryLabel: "CM",
        country: "CM",
        catchUpRead: isCatchUpReadActive(state.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  if (
    await trySendFolderPreset(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      outgoingTexts,
      latestCustomerText,
    )
  ) {
    return true;
  }
  console.log(
    `Pager worker: CM ${convId.slice(0, 8)} — no saved-reply step, 1xbet scripts are not sent`,
  );
  return true;
}

async function processClConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;
  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const outgoingTexts = collectClOutgoingTexts(messages);
  await maybeEnsureInProgressAfterRegLink(
    deps,
    currentState,
    client,
    conv,
    convId,
    runtime.channelId,
    "CL",
    outgoingTexts,
    clRegLinkSentInHistory,
  );

  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "CM");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "CM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    console.log(`Pager worker: skip ${convId.slice(0, 8)} CL — bot_spoke_last`);
    return false;
  }

  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);

  if (
    await tryHandleTrollCustomerToIgnore(
      deps,
      currentState,
      client,
      conv,
      runtime,
      convState,
      convId,
      "CL",
      latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      convState.funnelStep ?? 0,
      Boolean(extractProofImageUrl(lastIncoming)),
    )
  ) {
    return true;
  }

  const tierChosenRecently = recentCustomerTexts.some((line) => isClDepositTierChoice(line));
  const awaitingRegAfterTierChoice =
    clTierSentInHistory(outgoingTexts) &&
    !clRegLinkSentInHistory(outgoingTexts) &&
    (isClDepositTierChoice(latestCustomerText) ||
      tierChosenRecently ||
      isClRegistrationAccountQuestion(latestCustomerText) ||
      isClRegistrationHelpRequest(latestCustomerText));
  const clNewLeadBypass =
    isNoStatusConversation(conv) &&
    !clScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("CM", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const clInProgressFollowUp =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: awaitingRegAfterTierChoice || clNewLeadBypass || clInProgressFollowUp,
        operatorUserId: operatorUserIdEarly,
        countryLabel: "CL",
        country: "CL",
        catchUpRead: isCatchUpReadActive(state.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const replyLang = resolveClReplyLanguage(
    latestCustomerText,
    recentCustomerTexts,
    convState.clReplyLanguage,
  );

  const playbook = getPlaybook(deps.config, channel.country);
  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  const threadStep = clInferStepFromThread(messages);
  const gapStep = clFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0);
  const effectiveStep = Math.max(threadStep, gapStep, convState.funnelStep ?? 0);
  const messageReaction = resolveMessageReaction(lastIncoming);
  const intent = classifyClMessage(latestCustomerText, {
    hasImage: Boolean(imageUrl),
    funnelStep: effectiveStep,
    messageReaction,
  });

  let scriptKeys = resolveClFunnelScripts(
    effectiveStep,
    latestCustomerText,
    intent,
    outgoingTexts,
    { hasImage: Boolean(imageUrl), messageReaction, recentCustomerTexts },
  );
  if (
    !clScriptSentInHistory(outgoingTexts, "01_intro") &&
    latestCustomerText.trim().length > 0 &&
    !scriptKeys.includes("01_intro")
  ) {
    scriptKeys = ["01_intro", "01_intro_2"];
  }
  if (
    clTierSentInHistory(outgoingTexts) &&
    !clRegLinkSentInHistory(outgoingTexts) &&
    isClDepositTierChoice(latestCustomerText) &&
    !scriptKeys.some((key) => CL_REG_SEND_KEYS.has(key))
  ) {
    scriptKeys = ["05_registration", "06_link", "07_chrome"];
  }
  scriptKeys = limitClScriptsForCustomerTurn(scriptKeys, outgoingTexts);
  scriptKeys = filterDisabledScriptKeys(scriptKeys);
  scriptKeys = filterScriptKeysForSupportAgent("CM", scriptKeys, latestCustomerText, support);

  if (!scriptKeys.length) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} CL — no script (lang=${replyLang}, step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
    );
    return false;
  }

  scriptKeys = await dropScriptKeysAlreadyInThread(client, convId, "CL", scriptKeys);
  if (!scriptKeys.length) {
    await maybeEnsureInProgressAfterRegLink(
      deps,
      currentState,
      client,
      conv,
      convId,
      runtime.channelId,
      "CL",
      outgoingTexts,
      clRegLinkSentInHistory,
    );
    console.log(`Pager worker: CL ${convId.slice(0, 8)} — scripts already in thread`);
    return false;
  }

  await tryTakeConversationForProcessing(client, convId, "CL");

  console.log(
    `Pager worker: CL ${convId.slice(0, 8)} lang=${replyLang} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}]`,
  );

  const allowMultiSend = clAllowsMultiSend(scriptKeys);
  let sentAny = false;
  const sentScriptKeys: string[] = [];

  for (const scriptKey of scriptKeys) {
    const replyText = loadLocalClScript(scriptKey, replyLang)?.trim();
    if (!replyText) {
      if (scriptKey === "01_intro_2") {
        continue;
      }
      console.warn(`Pager worker: CL missing ${replyLang}/${scriptKey} ${convId.slice(0, 8)}`);
      continue;
    }

    const sent = await client.sendMessageReliable(convId, replyText, {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: (convState.sendFailures ?? 0) + 1,
      });
      return sentAny;
    }
    sentAny = true;
    sentScriptKeys.push(scriptKey);
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      clReplyLanguage: replyLang,
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: scriptKey,
      sendFailures: 0,
    });
    await sleep(500);
    if (!allowMultiSend) {
      break;
    }
  }

  if (sentAny) {
    const outAfterSend = collectClOutgoingTexts(await client.listMessages(convId, 1, 80));
    if (clStatusMoveAfterSend(sentScriptKeys) || clRegLinkSentInHistory(outAfterSend)) {
      await maybeEnsureInProgressAfterRegLink(
        deps,
        currentState,
        client,
        conv,
        convId,
        runtime.channelId,
        "CL",
        outAfterSend,
        clRegLinkSentInHistory,
      );
    }
  }

  if (!sentAny) {
    return false;
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    clReplyLanguage: replyLang,
    currentStage: effectiveStep >= 5 ? "registered" : effectiveStep >= 1 ? "engaged" : "new_lead",
    funnelStep: Math.max(effectiveStep, sentScriptKeys.includes("09_deposit") ? 6 : effectiveStep),
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: sentScriptKeys[sentScriptKeys.length - 1] ?? scriptKeys[scriptKeys.length - 1],
    sendFailures: 0,
  });

  return true;
}

async function processZmConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "ZM");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "ZM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} ZM — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }

  const outgoingTexts = collectZmOutgoingTexts(messages);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const zmNewLeadBypass =
    isNoStatusConversation(conv) &&
    !zmScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const operatorUserId = operatorUserIdEarly;
  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("ZM", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const zmInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: zmNewLeadBypass || zmInProgressBypass,
        operatorUserId,
        countryLabel: "ZM",
        country: "ZM",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const threadStep = zmInferStepFromThread(messages);
  const gapStep = zmFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0);
  const effectiveStep = Math.max(threadStep, gapStep, convState.funnelStep ?? 0);
  const messageReaction = resolveMessageReaction(lastIncoming);
  const playbook = getPlaybook(deps.config, channel.country);

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  if (imageUrl && (zmDepositSentInHistory(outgoingTexts) || zmRegLinkSentInHistory(outgoingTexts))) {
    const imageHandled = await tryHandleCustomerImage(deps, {
      state,
      client,
      conv,
      runtime,
      channel,
      convState,
      convId,
      lastIncoming,
      text: latestCustomerText,
      imageUrl,
      playbook,
      outgoingTexts,
      funnelStep: effectiveStep,
      sortedMessages: sorted,
      operatorUserId,
    });
    if (imageHandled) {
      return true;
    }
  }

  let proofKind: import("./config.js").ProofKind | undefined;
  let proofText = "";
  if (imageUrl) {
    try {
      const image = await client.downloadAttachment(imageUrl);
      const classification = await classifyProofFromImage(playbook, image, {
        caption: latestCustomerText,
        ocrEnabled: deps.env.OCR_ENABLED,
        ocrLang: ocrLangForCountry(channel.country),
        country: "ZM",
      });
      proofKind = classification.proofKind;
      proofText = classification.combinedText;
    } catch (error) {
      console.warn(`ZM OCR failed ${convId.slice(0, 8)}:`, formatError(error));
    }
  }

  const intent = classifyZmMessage(latestCustomerText, {
    hasImage: Boolean(imageUrl),
    funnelStep: effectiveStep,
    messageReaction,
  });

  let scriptKeys = resolveZmFunnelScripts(
    effectiveStep,
    latestCustomerText,
    intent,
    outgoingTexts,
    {
      hasImage: Boolean(imageUrl),
      messageReaction,
      recentCustomerTexts,
      proofKind,
      proofText,
    },
  );
  scriptKeys = limitZmScriptsForCustomerTurn(scriptKeys, outgoingTexts);
  scriptKeys = filterDisabledScriptKeys(scriptKeys);
  scriptKeys = filterScriptKeysForSupportAgent("ZM", scriptKeys, latestCustomerText, support);
  const skipEarlySupportAi = supportAgentSkipsEarlyAi("ZM", scriptKeys, support);

  if (
    !scriptKeys.length &&
    zmExplainScriptsSentInHistory(outgoingTexts) &&
    !zmRegLinkSentInHistory(outgoingTexts) &&
    (zmWantsRegistrationLink(latestCustomerText) ||
      zmIsRegistrationHelpRequest(latestCustomerText) ||
      customerAgreedAfterOfferTable(latestCustomerText) ||
      isZmDepositAmountChoice(latestCustomerText))
  ) {
    scriptKeys = ["04_registration", "05_link"];
  }

  if (scriptKeys.length) {
  scriptKeys = await dropScriptKeysAlreadyInThread(client, convId, "ZM", scriptKeys);
  if (!scriptKeys.length) {
    console.log(`Pager worker: ZM ${convId.slice(0, 8)} — scripts already in thread`);
  } else {
  await tryTakeConversationForProcessing(client, convId);

  console.log(
    `Pager worker: ZM ${convId.slice(0, 8)} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}]`,
  );

  const folderId = await resolveZmTemplateFolderId(
    client,
    runtime.runtime.templateBankId,
    currentState.pagerAccount?.liveTemplateBanks,
  );

  let sentAny = false;
  const sentScriptKeys: string[] = [];
  const allowMultiSend = zmAllowsMultiSend(scriptKeys);
  const coveredOutgoing = [...outgoingTexts];
  for (const scriptKey of scriptKeys) {
    if (zmScriptSentInHistory(coveredOutgoing, scriptKey)) {
      console.log(
        `Pager worker: ZM ${convId.slice(0, 8)} skip duplicate key=${scriptKey} (already in thread/batch)`,
      );
      continue;
    }
    const replyText = await resolveScriptTextByKey(client, {
      folderId,
      liveBanks: currentState.pagerAccount?.liveTemplateBanks,
      scriptKey,
      country: "ZM",
      refreshSavedReplies: true,
    });
    if (!replyText?.trim()) {
      if (scriptKey === "04_registration") {
        const fallbackText = loadLocalZmScript("04_registration")?.trim();
        if (fallbackText) {
          const sent = await client.sendMessageReliable(convId, fallbackText, {
            channelId: runtime.channelId,
            conv,
          });
          if (sent) {
            sentAny = true;
            sentScriptKeys.push(scriptKey);
            coveredOutgoing.push(fallbackText);
            await patchConversationState(deps.stateStore, state.chatId, convId, {
              conversationId: convId,
              channelId: runtime.channelId,
              lastCustomerMessageId: lastIncoming.id,
              lastCustomerMessageAt: lastIncoming.createdAt,
              lastReplyAt: new Date().toISOString(),
              lastReplyRole: scriptKey,
              sendFailures: 0,
            });
            await sleep(500);
          }
        } else {
          console.warn(`ZM script missing ${convId.slice(0, 8)}: ${scriptKey}`);
        }
        continue;
      }
      if (scriptKey === "05_link") {
        const fallbackLink =
          loadLocalZmScript("05_link")?.trim() || "https://tinyurl.com/ZAM577";
        const sent = await client.sendMessageReliable(convId, fallbackLink, {
          channelId: runtime.channelId,
          conv,
        });
        if (sent) {
          sentAny = true;
          sentScriptKeys.push(scriptKey);
          await patchConversationState(deps.stateStore, state.chatId, convId, {
            conversationId: convId,
            channelId: runtime.channelId,
            lastCustomerMessageId: lastIncoming.id,
            lastCustomerMessageAt: lastIncoming.createdAt,
            lastReplyAt: new Date().toISOString(),
            lastReplyRole: scriptKey,
            sendFailures: 0,
          });
          await sleep(500);
        }
        continue;
      }
      console.warn(
        `ZM script missing folder=${folderId?.slice(0, 8) ?? "?"} key=${scriptKey} liveBanks=${currentState.pagerAccount?.liveTemplateBanks?.map((bank) => bank.name).join(",") ?? "none"}`,
      );
      continue;
    }

    const sent = await client.sendMessageReliable(convId, replyText.trim(), {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      const failures = (convState.sendFailures ?? 0) + 1;
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: failures,
      });
      console.error(`Pager worker: ZM send failed ${convId.slice(0, 8)} key=${scriptKey}`);
      return sentAny;
    }
    sentAny = true;
    sentScriptKeys.push(scriptKey);
    coveredOutgoing.push(replyText.trim());
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: scriptKey,
      sendFailures: 0,
    });
    if (scriptKey === "07_game_id") {
      const attachment = resolveScriptAttachment("ZM", scriptKey);
      if (attachment) {
        try {
          const imageSent = await client.sendImageReliable(
            convId,
            {
              buffer: readFileSync(attachment.path),
              mimeType: attachment.mimeType,
              filename: attachment.filename,
            },
            {
              channelId: runtime.channelId,
              conv,
            },
          );
          if (!imageSent) {
            console.warn(`Pager worker: ZM image miss ${convId.slice(0, 8)} key=${scriptKey}`);
          }
        } catch (error) {
          console.warn(
            `Pager worker: ZM image failed ${convId.slice(0, 8)} key=${scriptKey}:`,
            formatError(error),
          );
        }
      }
    }
    await sleep(500);
    if (!allowMultiSend) {
      break;
    }
  }

  if (!sentAny) {
    return false;
  }

  const statusTarget = zmStatusMoveTarget(sentScriptKeys);
  if (statusTarget) {
    const statusId = findZmStatusId(currentState, statusTarget);
    const operatorId = await client.probeOperatorUserId();
    const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
    if (statusId && operatorId && currentStatusId !== statusId) {
      try {
        await client.patchConversationStatus(convId, statusId, operatorId);
        console.log(
          `Pager worker: ZM ${convId.slice(0, 8)} status -> ${statusTarget === "registration_complete" ? "registration" : "in progress registration"}`,
        );
        if (statusTarget === "in_progress_registration") {
          await onMovedToInProgressRegistration(deps, state.chatId, convId, runtime.channelId);
        }
      } catch (error) {
        console.warn(`Pager worker: status patch failed ${convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    currentStage: effectiveStep >= 5 ? "registered" : effectiveStep >= 1 ? "engaged" : "new_lead",
    funnelStep: Math.max(effectiveStep, scriptKeys.includes("06_deposit") ? 6 : effectiveStep),
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: sentScriptKeys[sentScriptKeys.length - 1] ?? scriptKeys[scriptKeys.length - 1],
    sendFailures: 0,
  });

  if (
    await trySupportAgentAfterScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "ZM",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      sentScriptKeys,
      support,
      skipEarlySupportAi,
    })
  ) {
    return true;
  }

  return true;
  }
  }

  if (!skipEarlySupportAi) {
    const aiHandledEarly = await tryRunAiAgentTurn(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: "ZM",
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
        aiFolderEnabled,
      },
    );
    if (aiHandledEarly) {
      return true;
    }
  }

  if (
    await trySupportAgentWhenNoScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "ZM",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      scriptKeys,
      support,
    })
  ) {
    return true;
  }
  console.log(
    `Pager worker: skip ${convId.slice(0, 8)} ZM — no script (step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
  );
  return false;
}

/** MG: авто-воронка (локальные скрипты, как ZM). */
async function processMgConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "CM");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "CM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} MG — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }

  const outgoingTexts = collectMgOutgoingTexts(messages);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const mgNewLeadBypass =
    isNoStatusConversation(conv) &&
    !mgScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const operatorUserId = operatorUserIdEarly;
  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("MG", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const mgInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: mgNewLeadBypass || mgInProgressBypass,
        operatorUserId,
        countryLabel: "MG",
        country: "MG",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const threadStep = mgInferStepFromThread(messages);
  const gapStep = mgFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0);
  const effectiveStep = Math.max(threadStep, gapStep, convState.funnelStep ?? 0);
  const messageReaction = resolveMessageReaction(lastIncoming);
  const playbook = getPlaybook(deps.config, channel.country);

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  if (imageUrl && (mgDepositSentInHistory(outgoingTexts) || mgRegLinkSentInHistory(outgoingTexts))) {
    const imageHandled = await tryHandleCustomerImage(deps, {
      state,
      client,
      conv,
      runtime,
      channel,
      convState,
      convId,
      lastIncoming,
      text: latestCustomerText,
      imageUrl,
      playbook,
      outgoingTexts,
      funnelStep: effectiveStep,
      sortedMessages: sorted,
      operatorUserId,
    });
    if (imageHandled) {
      return true;
    }
  }

  let proofKind: import("./config.js").ProofKind | undefined;
  let proofText = "";
  if (imageUrl) {
    try {
      const image = await client.downloadAttachment(imageUrl);
      const classification = await classifyProofFromImage(playbook, image, {
        caption: latestCustomerText,
        ocrEnabled: deps.env.OCR_ENABLED,
        ocrLang: ocrLangForCountry(channel.country),
        country: "CM",
      });
      proofKind = classification.proofKind;
      proofText = classification.combinedText;
    } catch (error) {
      console.warn(`MG OCR failed ${convId.slice(0, 8)}:`, formatError(error));
    }
  }

  const intent = classifyMgMessage(latestCustomerText, {
    hasImage: Boolean(imageUrl),
    funnelStep: effectiveStep,
    messageReaction,
  });

  let scriptKeys = resolveMgFunnelScripts(
    effectiveStep,
    latestCustomerText,
    intent,
    outgoingTexts,
    {
      hasImage: Boolean(imageUrl),
      messageReaction,
      recentCustomerTexts,
      proofKind,
      proofText,
    },
  );
  scriptKeys = limitMgScriptsForCustomerTurn(scriptKeys, outgoingTexts);
  scriptKeys = filterDisabledScriptKeys(scriptKeys);
  scriptKeys = filterScriptKeysForSupportAgent("MG", scriptKeys, latestCustomerText, support);
  const skipEarlySupportAi = supportAgentSkipsEarlyAi("MG", scriptKeys, support);

  if (
    !scriptKeys.length &&
    mgExplainScriptsSentInHistory(outgoingTexts) &&
    !mgRegLinkSentInHistory(outgoingTexts) &&
    (mgWantsRegistrationLink(latestCustomerText) ||
      mgIsRegistrationHelpRequest(latestCustomerText) ||
      customerAgreedAfterOfferTable(latestCustomerText) ||
      isMgOfferTableChoice(latestCustomerText) ||
      isMgDepositAmountChoice(latestCustomerText) ||
      intent === "interested" ||
      intent === "positive" ||
      intent === "ready")
  ) {
    scriptKeys = ["04_registration", "05_link"];
  }

  if (scriptKeys.length) {
  scriptKeys = await dropScriptKeysAlreadyInThread(client, convId, "MG", scriptKeys);
  if (!scriptKeys.length) {
    console.log(`Pager worker: MG ${convId.slice(0, 8)} — scripts already in thread`);
  } else {
  await tryTakeConversationForProcessing(client, convId, "MG");

  console.log(
    `Pager worker: MG ${convId.slice(0, 8)} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}]`,
  );

  let sentAny = false;
  const sentScriptKeys: string[] = [];
  const allowMultiSend = mgAllowsMultiSend(scriptKeys);
  const coveredOutgoing = [...outgoingTexts];
  for (const scriptKey of scriptKeys) {
    if (mgScriptSentInHistory(coveredOutgoing, scriptKey)) {
      console.log(
        `Pager worker: MG ${convId.slice(0, 8)} skip duplicate key=${scriptKey} (already in thread/batch)`,
      );
      continue;
    }
    let replyText = loadLocalMgScript(scriptKey)?.trim();
    if (!replyText) {
      if (scriptKey === "04_registration") {
        const fallbackText = loadLocalMgScript("04_registration")?.trim();
        if (fallbackText) {
          const sent = await client.sendMessageReliable(convId, fallbackText, {
            channelId: runtime.channelId,
            conv,
          });
          if (sent) {
            sentAny = true;
            sentScriptKeys.push(scriptKey);
            coveredOutgoing.push(fallbackText);
            await patchConversationState(deps.stateStore, state.chatId, convId, {
              conversationId: convId,
              channelId: runtime.channelId,
              lastCustomerMessageId: lastIncoming.id,
              lastCustomerMessageAt: lastIncoming.createdAt,
              lastReplyAt: new Date().toISOString(),
              lastReplyRole: scriptKey,
              sendFailures: 0,
            });
            await sleep(500);
          }
        } else {
          console.warn(`MG script missing ${convId.slice(0, 8)}: ${scriptKey}`);
        }
        continue;
      }
      if (scriptKey === "05_link") {
        const fallbackLink = mgDefaultRegistrationLink();
        const sent = await client.sendMessageReliable(convId, fallbackLink, {
          channelId: runtime.channelId,
          conv,
        });
        if (sent) {
          sentAny = true;
          sentScriptKeys.push(scriptKey);
          coveredOutgoing.push(fallbackLink);
          await patchConversationState(deps.stateStore, state.chatId, convId, {
            conversationId: convId,
            channelId: runtime.channelId,
            lastCustomerMessageId: lastIncoming.id,
            lastCustomerMessageAt: lastIncoming.createdAt,
            lastReplyAt: new Date().toISOString(),
            lastReplyRole: scriptKey,
            sendFailures: 0,
          });
          await sleep(500);
        }
        continue;
      }
      console.warn(`MG script missing ${convId.slice(0, 8)}: ${scriptKey}`);
      continue;
    }

    const sent = await client.sendMessageReliable(convId, replyText.trim(), {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      const failures = (convState.sendFailures ?? 0) + 1;
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: failures,
      });
      console.error(`Pager worker: MG send failed ${convId.slice(0, 8)} key=${scriptKey}`);
      return sentAny;
    }
    sentAny = true;
    sentScriptKeys.push(scriptKey);
    coveredOutgoing.push(replyText.trim());
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: scriptKey,
      sendFailures: 0,
    });
    await sleep(500);
    if (!allowMultiSend) {
      break;
    }
  }

  if (!sentAny) {
    return false;
  }

  const statusTarget = mgStatusMoveTarget(sentScriptKeys);
  if (
    statusTarget === "in_progress_registration" ||
    sentScriptKeys.includes("05_link") ||
    mgRegLinkSentInHistory(coveredOutgoing)
  ) {
    const moved = await tryMoveConversationToInProgressRegistration(
      deps,
      currentState,
      client,
      conv,
      convId,
      runtime.channelId,
      "MG",
    );
    if (!moved) {
      await maybeEnsureInProgressAfterRegLink(
        deps,
        currentState,
        client,
        conv,
        convId,
        runtime.channelId,
        "MG",
        coveredOutgoing,
        mgRegLinkSentInHistory,
      );
    }
  } else if (statusTarget === "registration_complete") {
    const statusId = findZmStatusId(currentState, statusTarget);
    const operatorId = await client.probeOperatorUserId();
    const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
    if (statusId && operatorId && currentStatusId !== statusId) {
      try {
        await client.patchConversationStatus(convId, statusId, operatorId);
        console.log(`Pager worker: MG ${convId.slice(0, 8)} status -> registration`);
      } catch (error) {
        console.warn(`Pager worker: status patch failed ${convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    currentStage: effectiveStep >= 5 ? "registered" : effectiveStep >= 1 ? "engaged" : "new_lead",
    funnelStep: Math.max(effectiveStep, scriptKeys.includes("06_deposit") ? 6 : effectiveStep),
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: sentScriptKeys[sentScriptKeys.length - 1] ?? scriptKeys[scriptKeys.length - 1],
    sendFailures: 0,
  });

  if (
    await trySupportAgentAfterScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "CM",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      sentScriptKeys,
      support,
      skipEarlySupportAi,
    })
  ) {
    return true;
  }

  return true;
  }
  }

  // Pre-reg funnel: templates own positive turns; AI only for complex/scam/link issues.
  const mgPreRegFunnel =
    mgScriptSentInHistory(outgoingTexts, "01_intro") &&
    !mgRegLinkSentInHistory(outgoingTexts);
  const mgComplexAiOk =
    isComplexCustomerMessage(latestCustomerText) ||
    isScamOrTrustQuestion(latestCustomerText) ||
    isLinkAccessProblemMessage(latestCustomerText) ||
    isCustomerClarificationMessage(latestCustomerText);
  const mgFunnelBlocksEarlyAi = mgPreRegFunnel && !mgComplexAiOk;

  if (!skipEarlySupportAi && !mgFunnelBlocksEarlyAi) {
    const aiHandledEarly = await tryRunAiAgentTurn(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: "CM",
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
        aiFolderEnabled,
      },
    );
    if (aiHandledEarly) {
      return true;
    }
  }

  if (
    !mgFunnelBlocksEarlyAi &&
    (await trySupportAgentWhenNoScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "CM",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      scriptKeys,
      support,
    }))
  ) {
    return true;
  }
  console.log(
    `Pager worker: skip ${convId.slice(0, 8)} MG — no script (step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
  );
  return false;
}

/** DJ: авто-воронка (локальные скрипты, как MG). */
async function processDjConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "CM");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  const outgoingTexts = collectDjOutgoingTexts(messages);
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "CM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    if (
      await trySendMissingRegistrationLink(
        deps,
        state,
        client,
        conv,
        runtime,
        convId,
        convState,
        outgoingTexts,
      )
    ) {
      return true;
    }
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} DJ — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }
  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const djNewLeadBypass =
    isNoStatusConversation(conv) &&
    !djScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const operatorUserId = operatorUserIdEarly;
  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("DJ", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const djInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: djNewLeadBypass || djInProgressBypass,
        operatorUserId,
        countryLabel: "DJ",
        country: "DJ",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  if (
    await trySendFolderPreset(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      outgoingTexts,
      latestCustomerText,
    )
  ) {
    return true;
  }
  console.log(
    `Pager worker: DJ ${convId.slice(0, 8)} — no saved-reply step, 1xbet scripts are not sent`,
  );
  return true;
}

async function processJoConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "EG");
  if (!lastIncoming) {
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "EG",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} JO — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }

  const outgoingTexts = collectJoOutgoingTexts(messages);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const joNewLeadBypass =
    isNoStatusConversation(conv) &&
    !joScriptSentInHistory(outgoingTexts, "01_intro") &&
    Boolean(latestCustomerText);

  const operatorUserId = operatorUserIdEarly;
  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("JO", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const joInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: joNewLeadBypass || joInProgressBypass,
        operatorUserId,
        countryLabel: "JO",
        country: "JO",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const threadStep = joInferStepFromThread(messages);
  const gapStep = joFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0);
  const effectiveStep = Math.max(threadStep, gapStep, convState.funnelStep ?? 0);
  const messageReaction = resolveMessageReaction(lastIncoming);
  const playbook = getPlaybook(deps.config, channel.country);

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  if (imageUrl && joRegLinkSentInHistory(outgoingTexts)) {
    const imageHandled = await tryHandleCustomerImage(deps, {
      state,
      client,
      conv,
      runtime,
      channel,
      convState,
      convId,
      lastIncoming,
      text: latestCustomerText,
      imageUrl,
      playbook,
      outgoingTexts,
      funnelStep: effectiveStep,
      sortedMessages: sorted,
      operatorUserId,
    });
    if (imageHandled) {
      return true;
    }
  }

  let proofKind: import("./config.js").ProofKind | undefined;
  let proofText = "";
  if (imageUrl) {
    try {
      const image = await client.downloadAttachment(imageUrl);
      const classification = await classifyProofFromImage(playbook, image, {
        caption: latestCustomerText,
        ocrEnabled: deps.env.OCR_ENABLED,
        ocrLang: ocrLangForCountry("EG"),
        country: "EG",
      });
      proofKind = classification.proofKind;
      proofText = classification.combinedText;
    } catch (error) {
      console.warn(`JO OCR failed ${convId.slice(0, 8)}:`, formatError(error));
    }
  }

  const intent = classifyJoMessage(latestCustomerText, {
    hasImage: Boolean(imageUrl),
    funnelStep: effectiveStep,
    messageReaction,
  });

  let scriptKeys = resolveJoFunnelScripts(
    effectiveStep,
    latestCustomerText,
    intent,
    outgoingTexts,
    {
      hasImage: Boolean(imageUrl),
      messageReaction,
      recentCustomerTexts,
      proofKind,
      proofText,
    },
  );
  scriptKeys = limitJoScriptsForCustomerTurn(scriptKeys, outgoingTexts);
  scriptKeys = filterDisabledScriptKeys(scriptKeys);
  scriptKeys = filterScriptKeysForSupportAgent("JO", scriptKeys, latestCustomerText, support);
  const skipEarlySupportAi = supportAgentSkipsEarlyAi("JO", scriptKeys, support);

  if (
    !scriptKeys.length &&
    joExplainScriptsSentInHistory(outgoingTexts) &&
    !joRegLinkSentInHistory(outgoingTexts) &&
    (joWantsRegistrationLink(latestCustomerText) ||
      joIsRegistrationHelpRequest(latestCustomerText) ||
      customerAgreedAfterOfferTable(latestCustomerText) ||
      isJoOfferTableChoice(latestCustomerText) ||
      isJoDepositAmountChoice(latestCustomerText) ||
      intent === "interested" ||
      intent === "positive" ||
      intent === "ready")
  ) {
    scriptKeys = nextJoRegScripts(outgoingTexts);
  }

  if (scriptKeys.length) {
  scriptKeys = await dropScriptKeysAlreadyInThread(client, convId, "JO", scriptKeys);
  if (!scriptKeys.length) {
    console.log(`Pager worker: JO ${convId.slice(0, 8)} — scripts already in thread`);
  } else {
  await tryTakeConversationForProcessing(client, convId, "JO");

  console.log(
    `Pager worker: JO ${convId.slice(0, 8)} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}]`,
  );

  let sentAny = false;
  const sentScriptKeys: string[] = [];
  const allowMultiSend = joAllowsMultiSend(scriptKeys);
  const coveredOutgoing = [...outgoingTexts];
  for (const scriptKey of scriptKeys) {
    if (joScriptSentInHistory(coveredOutgoing, scriptKey)) {
      console.log(
        `Pager worker: JO ${convId.slice(0, 8)} skip duplicate key=${scriptKey} (already in thread/batch)`,
      );
      continue;
    }
    let replyText = loadLocalJoScript(scriptKey)?.trim();
    if (!replyText) {
      if (scriptKey === "04_registration") {
        const fallbackText = loadLocalJoScript("04_registration")?.trim();
        if (fallbackText) {
          const sent = await client.sendMessageReliable(convId, fallbackText, {
            channelId: runtime.channelId,
            conv,
          });
          if (sent) {
            sentAny = true;
            sentScriptKeys.push(scriptKey);
            coveredOutgoing.push(fallbackText);
            await patchConversationState(deps.stateStore, state.chatId, convId, {
              conversationId: convId,
              channelId: runtime.channelId,
              lastCustomerMessageId: lastIncoming.id,
              lastCustomerMessageAt: lastIncoming.createdAt,
              lastReplyAt: new Date().toISOString(),
              lastReplyRole: scriptKey,
              sendFailures: 0,
            });
            await sleep(500);
          }
        } else {
          console.warn(`JO script missing ${convId.slice(0, 8)}: ${scriptKey}`);
        }
        continue;
      }
      if (scriptKey === "05_link") {
        const fallbackLink = joDefaultRegistrationLink();
        const sent = await client.sendMessageReliable(convId, fallbackLink, {
          channelId: runtime.channelId,
          conv,
        });
        if (sent) {
          sentAny = true;
          sentScriptKeys.push(scriptKey);
          coveredOutgoing.push(fallbackLink);
          await patchConversationState(deps.stateStore, state.chatId, convId, {
            conversationId: convId,
            channelId: runtime.channelId,
            lastCustomerMessageId: lastIncoming.id,
            lastCustomerMessageAt: lastIncoming.createdAt,
            lastReplyAt: new Date().toISOString(),
            lastReplyRole: scriptKey,
            sendFailures: 0,
          });
          await sleep(500);
        }
        continue;
      }
      console.warn(`JO script missing ${convId.slice(0, 8)}: ${scriptKey}`);
      continue;
    }

    const sent = await client.sendMessageReliable(convId, replyText.trim(), {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      const failures = (convState.sendFailures ?? 0) + 1;
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: failures,
      });
      console.error(`Pager worker: JO send failed ${convId.slice(0, 8)} key=${scriptKey}`);
      return sentAny;
    }
    sentAny = true;
    sentScriptKeys.push(scriptKey);
    coveredOutgoing.push(replyText.trim());
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: scriptKey,
      sendFailures: 0,
    });
    await sleep(500);
    if (!allowMultiSend) {
      break;
    }
  }

  if (!sentAny) {
    return false;
  }

  const statusTarget = joStatusMoveTarget(sentScriptKeys);
  if (
    statusTarget === "in_progress_registration" ||
    sentScriptKeys.includes("05_link") ||
    joRegLinkSentInHistory(coveredOutgoing)
  ) {
    const moved = await tryMoveConversationToInProgressRegistration(
      deps,
      currentState,
      client,
      conv,
      convId,
      runtime.channelId,
      "JO",
    );
    if (!moved) {
      await maybeEnsureInProgressAfterRegLink(
        deps,
        currentState,
        client,
        conv,
        convId,
        runtime.channelId,
        "JO",
        coveredOutgoing,
        joRegLinkSentInHistory,
      );
    }
  } else if (statusTarget === "registration_complete") {
    const statusId = findZmStatusId(currentState, statusTarget);
    const operatorId = await client.probeOperatorUserId();
    const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
    if (statusId && operatorId && currentStatusId !== statusId) {
      try {
        await client.patchConversationStatus(convId, statusId, operatorId);
        console.log(`Pager worker: JO ${convId.slice(0, 8)} status -> registration`);
      } catch (error) {
        console.warn(`Pager worker: status patch failed ${convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    currentStage: effectiveStep >= 4 ? "registered" : effectiveStep >= 1 ? "engaged" : "new_lead",
    funnelStep: Math.max(effectiveStep, scriptKeys.includes("05_link") ? 4 : effectiveStep),
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: sentScriptKeys[sentScriptKeys.length - 1] ?? scriptKeys[scriptKeys.length - 1],
    sendFailures: 0,
  });

  if (
    await trySupportAgentAfterScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "EG",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      sentScriptKeys,
      support,
      skipEarlySupportAi,
    })
  ) {
    return true;
  }

  return true;
  }
  }

  // Pre-reg funnel: templates own positive turns; AI only for complex/scam/link issues.
  const joPreRegFunnel =
    joScriptSentInHistory(outgoingTexts, "01_intro") &&
    !joRegLinkSentInHistory(outgoingTexts);
  const joComplexAiOk =
    isComplexCustomerMessage(latestCustomerText) ||
    isScamOrTrustQuestion(latestCustomerText) ||
    isLinkAccessProblemMessage(latestCustomerText) ||
    isCustomerClarificationMessage(latestCustomerText);
  const joFunnelBlocksEarlyAi = joPreRegFunnel && !joComplexAiOk;

  if (!skipEarlySupportAi && !joFunnelBlocksEarlyAi) {
    const aiHandledEarly = await tryRunAiAgentTurn(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: "EG",
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
        aiFolderEnabled,
      },
    );
    if (aiHandledEarly) {
      return true;
    }
  }

  if (
    !joFunnelBlocksEarlyAi &&
    (await trySupportAgentWhenNoScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "EG",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      scriptKeys,
      support,
    }))
  ) {
    return true;
  }
  console.log(
    `Pager worker: skip ${convId.slice(0, 8)} JO — no script (step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
  );
  return false;
}

async function sendEgRegistrationThenLink(
  client: PagerClient,
  convId: string,
  runtime: EnabledChannel,
  conv: PagerConversation,
): Promise<boolean> {
  const regText = buildEgRegistrationOnlyMessage();
  if (!regText?.trim()) {
    return false;
  }
  const linkText = buildEgLinkOnlyMessage();
  const sentReg = await client.sendMessageReliable(convId, regText.trim(), {
    channelId: runtime.channelId,
    conv,
  });
  if (!sentReg) {
    return false;
  }
  await sleep(500);
  return client.sendMessageReliable(convId, linkText.trim(), {
    channelId: runtime.channelId,
    conv,
  });
}

async function tryRunAiAgentTurn(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  convState: ConversationRuntimeState,
  lastIncoming: PagerMessage,
  options: {
    country: CountryCode;
    customerText: string;
    recentCustomerTexts: string[];
    outgoingTexts: string[];
    funnelStep: number;
    intent: string;
    scriptKeys: string[];
    support?: import("./ai-support-phase.js").SupportSnapshot;
    forceSupportAgent?: boolean;
    agentTrigger?: import("./ai-assist.js").AiAgentTrigger;
    folderEnabled?: boolean;
    aiFolderEnabled?: boolean;
  },
): Promise<boolean> {
  if (options.aiFolderEnabled === false || options.folderEnabled === false) {
    return false;
  }
  if (
    isTrollDetectionCountry(options.country) &&
    shouldIgnoreTrollCustomer(
      options.customerText,
      options.recentCustomerTexts,
      {
        hasFunnelProgress: hasTrollFunnelProgress(options.country, options.outgoingTexts),
        latestHasImage: false,
      },
      options.funnelStep,
    )
  ) {
    return false;
  }
  if (
    looksLikeOwnScriptEcho(options.customerText, options.country, options.outgoingTexts)
  ) {
    return false;
  }
  const aiText = await runAiAgentTextTurn(deps.env, {
    country: options.country,
    customerText: options.customerText,
    recentCustomerTexts: options.recentCustomerTexts,
    recentOutgoingTexts: options.outgoingTexts,
    funnelStep: options.funnelStep,
    intent: options.intent,
    scriptKeys: options.scriptKeys,
    support: options.support,
    forceSupportAgent: options.forceSupportAgent,
    agentTrigger: options.agentTrigger,
  });
  if (!aiText) {
    return false;
  }
  await tryTakeConversationForProcessing(client, convId, options.country);
  const sent = await client.sendMessageReliable(convId, aiText, {
    channelId: runtime.channelId,
    conv,
  });
  if (!sent) {
    return false;
  }
  console.log(
    `Pager worker: ${options.country} ${convId.slice(0, 8)} AI agent (${aiText.length} chars) build=${getDeployLabel()}`,
  );
  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: "ai_agent",
    sendFailures: 0,
  });
  return true;
}

async function trySupportAgentWhenNoScripts(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  convState: ConversationRuntimeState,
  lastIncoming: PagerMessage,
  options: {
    country: CountryCode;
    customerText: string;
    recentCustomerTexts: string[];
    outgoingTexts: string[];
    funnelStep: number;
    intent: string;
    scriptKeys: string[];
    support: import("./ai-support-phase.js").SupportSnapshot;
  },
): Promise<boolean> {
  if (options.scriptKeys.length || !options.support.active || !options.customerText.trim()) {
    return false;
  }
  if (!customerWantsSupportAgentReply(options.customerText, options.intent)) {
    return false;
  }
  return tryRunAiAgentTurn(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
    ...options,
    forceSupportAgent: true,
  });
}

async function trySupportAgentAfterScripts(
  _deps: WorkerDeps,
  _state: ChatState,
  _client: PagerClient,
  _conv: PagerConversation,
  _runtime: EnabledChannel,
  _convId: string,
  _convState: ConversationRuntimeState,
  _lastIncoming: PagerMessage,
  _options: {
    country: CountryCode;
    customerText: string;
    recentCustomerTexts: string[];
    outgoingTexts: string[];
    funnelStep: number;
    intent: string;
    sentScriptKeys: string[];
    support: import("./ai-support-phase.js").SupportSnapshot;
    skipEarlySupportAi: boolean;
  },
): Promise<boolean> {
  // One customer turn → script OR agent, never auto follow-up after deposit script.
  return false;
}

async function processEgConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, "EG");
  if (!lastIncoming) {
    console.log(
      `Pager worker: EG ${convId.slice(0, 8)} — no_customer_message (msgs=${messages.length}, dir=${sorted[0]?.messageDirection ?? "?"})`,
    );
    return false;
  }

  const operatorUserIdEarly = await client.probeOperatorUserId();
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId: operatorUserIdEarly,
      country: "EG",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} EG — bot_spoke_last (awaiting_customer)`,
    );
    return false;
  }

  if (!isFreshCustomerMessage(lastIncoming.createdAt)) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} EG — stale_customer_message (at=${lastIncoming.createdAt ?? "?"})`,
    );
    if (hasUnreadMarkers(conv)) {
      try {
        await client.acknowledgeConversation(convId);
      } catch {
        // non-fatal
      }
    }
    return false;
  }

  const outgoingTexts = collectEgOutgoingTexts(messages);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const recentCustomerTexts = recentCustomerMessageTexts(sorted, conv);
  const tierChosenRecently = recentCustomerTexts.some((line) => isEgDepositTierChoice(line));
  const awaitingRegAfterTierChoice =
    explainScriptsSentInHistory(outgoingTexts) &&
    !egRegLinkSentInHistory(outgoingTexts) &&
    (isEgDepositTierChoice(latestCustomerText) || tierChosenRecently);
  const egNewLeadBypass =
    isNoStatusConversation(conv) &&
    !egIntroSentInHistory(outgoingTexts) &&
    Boolean(latestCustomerText) &&
    isFreshCustomerMessage(lastIncoming.createdAt);

  const operatorUserId = operatorUserIdEarly;
  const { botFolderEnabled: folderEnabled, aiFolderEnabled } = resolveConversationFolderGates(
    conv,
    currentState,
  );
  const imageUrl = extractProofImageUrl(lastIncoming);
  const support = buildSupportSnapshot("EG", isInProgressStatusConversation(conv), outgoingTexts, {
    operatorFolderEnabled: aiFolderEnabled,
  });
  const egInProgressBypass =
    inProgressFollowUpEligible(support, latestCustomerText, Boolean(imageUrl)) ||
    isCustomerClarificationMessage(latestCustomerText);

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        bypass: awaitingRegAfterTierChoice || egNewLeadBypass || egInProgressBypass,
        operatorUserId,
        countryLabel: "EG",
        country: "EG",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  const threadStep = egInferStepFromThread(messages);
  const gapStep = egFunnelStepFromScriptGaps(outgoingTexts, convState.funnelStep ?? 0);
  const effectiveStep = Math.max(threadStep, gapStep, convState.funnelStep ?? 0);
  const messageReaction = resolveMessageReaction(lastIncoming);
  const playbook = getPlaybook(deps.config, channel.country);

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  if (imageUrl) {
    const imageHandled = await tryHandleCustomerImage(deps, {
      state,
      client,
      conv,
      runtime,
      channel,
      convState,
      convId,
      lastIncoming,
      text: latestCustomerText,
      imageUrl,
      playbook,
      outgoingTexts,
      funnelStep: effectiveStep,
      sortedMessages: sorted,
      operatorUserId,
    });
    if (imageHandled) {
      return true;
    }
  }

  const intent = classifyEgMessage(latestCustomerText, {
    hasImage: Boolean(imageUrl),
    funnelStep: effectiveStep,
    messageReaction,
  });

  let scriptKeys = limitEgScriptsForCustomerTurn(
    resolveEgFunnelScripts(
      effectiveStep,
      latestCustomerText,
      intent,
      outgoingTexts,
      { hasImage: Boolean(imageUrl), messageReaction, recentCustomerTexts },
    ),
    outgoingTexts,
  );
  if (
    !scriptKeys.length &&
    intent !== "declined" &&
    egFunnelNeedsContinuation(latestCustomerText, outgoingTexts)
  ) {
    scriptKeys = resolveEgBacklogFallback(
      effectiveStep,
      outgoingTexts,
      intent,
      latestCustomerText,
      { hasImage: Boolean(imageUrl), messageReaction },
    );
  }
  scriptKeys = filterDisabledScriptKeys(scriptKeys);
  scriptKeys = filterScriptKeysForSupportAgent("EG", scriptKeys, latestCustomerText, support);
  const skipEarlySupportAi = supportAgentSkipsEarlyAi("EG", scriptKeys, support);

  if (!skipEarlySupportAi) {
    const aiHandledEarly = await tryRunAiAgentTurn(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      lastIncoming,
      {
        country: "EG",
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
        aiFolderEnabled,
      },
    );
    if (aiHandledEarly) {
      return true;
    }
  }

  if (!scriptKeys.length) {
    if (
      await trySupportAgentWhenNoScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
        country: "EG",
        customerText: latestCustomerText,
        recentCustomerTexts,
        outgoingTexts,
        funnelStep: effectiveStep,
        intent,
        scriptKeys,
        support,
      })
    ) {
      return true;
    }
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} EG — no script (step=${effectiveStep}, intent=${intent}, text=${truncate(latestCustomerText)})`,
    );
    return false;
  }

  // Take/read only when we actually have something to send — prevents overnight silence.
  scriptKeys = await dropScriptKeysAlreadyInThread(client, convId, "EG", scriptKeys);
  if (!scriptKeys.length) {
    console.log(`Pager worker: EG ${convId.slice(0, 8)} — scripts already in thread`);
    return false;
  }
  await tryTakeConversationForProcessing(client, convId, "EG");

  console.log(
    `Pager worker: EG ${convId.slice(0, 8)} step=${effectiveStep} intent=${intent} scripts=[${scriptKeys.join(",")}] build=${getDeployLabel()}`,
  );

  const folderId = await resolveEgTemplateFolderId(
    client,
    runtime.runtime.templateBankId,
    currentState.pagerAccount?.liveTemplateBanks,
  );

  let sentAny = false;
  const sentScriptKeys: string[] = [];
  const allowMultiSend = egAllowsMultiSend(scriptKeys);
  for (const scriptKey of scriptKeys) {
    if (
      (scriptKey === "04_registration" || scriptKey === "05_link") &&
      sentScriptKeys.includes("04_registration") &&
      sentScriptKeys.includes("05_link")
    ) {
      continue;
    }

    if (
      (scriptKey === "04_registration" || scriptKey === "05_link") &&
      !egFullRegistrationInstructionsSentInHistory(outgoingTexts) &&
      !sentScriptKeys.includes("04_registration")
    ) {
      const sentBundle = await sendEgRegistrationThenLink(client, convId, runtime, conv);
      if (sentBundle) {
        sentAny = true;
        sentScriptKeys.push("04_registration", "05_link");
        console.log(
          `Pager worker: EG ${convId.slice(0, 8)} sent registration text then link (2 messages) build=${getDeployLabel()}`,
        );
        await patchConversationState(deps.stateStore, state.chatId, convId, {
          conversationId: convId,
          channelId: runtime.channelId,
          lastCustomerMessageId: lastIncoming.id,
          lastCustomerMessageAt: lastIncoming.createdAt,
          lastReplyAt: new Date().toISOString(),
          lastReplyRole: "05_link",
          sendFailures: 0,
        });
        continue;
      }
      const failures = (convState.sendFailures ?? 0) + 1;
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: failures,
      });
      console.error(`Pager worker: EG send failed ${convId.slice(0, 8)} key=04_registration+05_link`);
      return sentAny;
    }

    let activeScriptKey = scriptKey;
    let replyText = await resolveScriptTextByKey(client, {
      folderId,
      liveBanks: currentState.pagerAccount?.liveTemplateBanks,
      scriptKey: activeScriptKey,
      country: "EG",
    });
    if (replyText?.trim() && !isEgScriptTextAcceptable(activeScriptKey, replyText)) {
      const localArabic = loadLocalEgScript(activeScriptKey);
      if (localArabic?.trim()) {
        console.warn(
          `EG script forced local Arabic key=${activeScriptKey} (pager text rejected, chars=${replyText.length})`,
        );
        replyText = localArabic;
      } else {
        replyText = undefined;
      }
    }
    if (!replyText?.trim()) {
      const localFallback = loadLocalEgScript(activeScriptKey);
      if (localFallback?.trim()) {
        console.log(`EG script local fallback key=${activeScriptKey}`);
        replyText = localFallback;
      }
    }
    if (
      activeScriptKey === "05_link" &&
      !sentScriptKeys.includes("04_registration") &&
      !egFullRegistrationInstructionsSentInHistory(outgoingTexts)
    ) {
      const regText = buildEgRegistrationOnlyMessage();
      if (regText?.trim()) {
        console.warn(`EG defer bare link — sending registration text first ${convId.slice(0, 8)}`);
        const sentReg = await client.sendMessageReliable(convId, regText.trim(), {
          channelId: runtime.channelId,
          conv,
        });
        if (!sentReg) {
          console.warn(`EG registration text send failed ${convId.slice(0, 8)}`);
          continue;
        }
        sentAny = true;
        sentScriptKeys.push("04_registration");
        await sleep(500);
        replyText = buildEgLinkOnlyMessage();
        activeScriptKey = "05_link";
      }
    }
    if (!replyText?.trim()) {
      if (activeScriptKey === "05_link") {
        const regReady =
          sentScriptKeys.includes("04_registration") ||
          egFullRegistrationInstructionsSentInHistory(outgoingTexts);
        if (!regReady) {
          console.warn(`EG skip bare link ${convId.slice(0, 8)} — registration text missing`);
          continue;
        }
        replyText = buildEgLinkOnlyMessage();
      } else {
        console.warn(
          `EG script missing folder=${folderId?.slice(0, 8) ?? "?"} key=${activeScriptKey} liveBanks=${currentState.pagerAccount?.liveTemplateBanks?.map((bank) => bank.name).join(",") ?? "none"}`,
        );
        continue;
      }
    }

    if (
      shouldBlockEgBareLinkSend(replyText, {
        regAlreadyInHistory: egFullRegistrationInstructionsSentInHistory(outgoingTexts),
        regSentThisTurn: sentScriptKeys.includes("04_registration"),
      })
    ) {
      console.warn(`EG skip bare link ${convId.slice(0, 8)} — registration text must go first`);
      continue;
    }

    const sent = await client.sendMessageReliable(convId, replyText.trim(), {
      channelId: runtime.channelId,
      conv,
    });
    if (!sent) {
      const failures = (convState.sendFailures ?? 0) + 1;
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: failures,
      });
      console.error(`Pager worker: EG send failed ${convId.slice(0, 8)} key=${scriptKey}`);
      return sentAny;
    }
    sentAny = true;
    sentScriptKeys.push(activeScriptKey);
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      lastCustomerMessageId: lastIncoming.id,
      lastCustomerMessageAt: lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: activeScriptKey,
      sendFailures: 0,
    });
    await sleep(500);
    if (!allowMultiSend) {
      break;
    }
  }

  if (!sentAny) {
    return false;
  }

  if (egRegSendTriggersInProgress(scriptKeys)) {
    const statusId = findFunnelFollowUpStatusId(currentState);
    const operatorId = await client.probeOperatorUserId();
    const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
    if (statusId && operatorId) {
      try {
        await client.patchConversationStatus(convId, statusId, operatorId);
        console.log(`Pager worker: EG ${convId.slice(0, 8)} status -> in progress`);
        if (currentStatusId !== statusId) {
          await onMovedToInProgressRegistration(deps, state.chatId, convId, runtime.channelId);
        }
      } catch (error) {
        console.warn(`Pager worker: status patch failed ${convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    currentStage: effectiveStep >= 5 ? "registered" : effectiveStep >= 1 ? "engaged" : "new_lead",
    funnelStep: Math.max(effectiveStep, scriptKeys.includes("06_deposit") ? 6 : effectiveStep),
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: scriptKeys[scriptKeys.length - 1],
    sendFailures: 0,
  });

  if (
    await trySupportAgentAfterScripts(deps, state, client, conv, runtime, convId, convState, lastIncoming, {
      country: "EG",
      customerText: latestCustomerText,
      recentCustomerTexts,
      outgoingTexts,
      funnelStep: effectiveStep,
      intent,
      sentScriptKeys,
      support,
      skipEarlySupportAi,
    })
  ) {
    return true;
  }

  return true;
}

async function trySendFolderPreset(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  convState: ConversationRuntimeState,
  lastIncoming: PagerMessage,
  outgoingTexts: string[],
  customerText: string,
): Promise<boolean> {
  const language = folderMarketLanguage(runtime.runtime.country);
  if (!language || !isFolderMarket(runtime.runtime.country)) {
    return false;
  }
  const folderId =
    runtime.runtime.templateBankId || pickLiveTemplateBank(state, runtime.runtime.country)?.id;
  if (!folderId) {
    console.warn(
      `Pager worker: ${runtime.runtime.country} ${convId.slice(0, 8)} — saved-reply folder is not linked`,
    );
    return false;
  }

  let replies;
  try {
    replies = await client.getSavedReplies(folderId);
  } catch (error) {
    console.warn(`Pager worker: saved replies failed ${convId.slice(0, 8)}:`, formatError(error));
    return false;
  }
  const plan = planFolderPresetAdvance(replies, outgoingTexts, customerText, language, {
    restartIfUnscripted:
      isCatchUpReadActive(state.catchUpRead) && isNoStatusConversation(conv),
  });
  if (!plan) {
    return false;
  }
  if (plan.action === "hold") {
    console.log(
      `Pager worker: ${runtime.runtime.country} ${convId.slice(0, 8)} preset hold (${plan.reason}), no AI`,
    );
    return true;
  }

  console.log(
    `Pager worker: ${runtime.runtime.country} ${convId.slice(0, 8)} ${plan.bubbles.map((bubble) => bubble.role).join("+")}${plan.table ? " table" : ""} from saved replies, no AI`,
  );
  const sentTexts = await deliverPresetBubbles(
    deps,
    state,
    client,
    conv,
    runtime,
    convId,
    convState,
    lastIncoming,
    plan.bubbles,
  );
  if (sentTexts.length) {
    await moveToRegistrationFolderIfLinkSent(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      replies,
      [...outgoingTexts, ...sentTexts],
    );
  }
  return true;
}

async function deliverPresetBubbles(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  convState: ConversationRuntimeState,
  lastIncoming: PagerMessage | undefined,
  bubbles: PresetBubble[],
): Promise<string[]> {
  const sentTexts: string[] = [];
  for (const bubble of bubbles) {
    let sent = false;
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      sent = await client.sendMessageReliable(convId, bubble.text.trim(), {
        channelId: runtime.channelId,
        conv,
      });
      if (sent) {
        break;
      }
      await sleep(600 * attempt);
    }
    if (!sent) {
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        sendFailures: (convState.sendFailures ?? 0) + 1,
      });
      console.error(`Pager worker: preset send failed ${convId.slice(0, 8)} ${bubble.role}`);
      return sentTexts;
    }
    sentTexts.push(bubble.text.trim());
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      conversationId: convId,
      channelId: runtime.channelId,
      lastCustomerMessageId: lastIncoming?.id,
      lastCustomerMessageAt: lastIncoming?.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: bubble.role,
      funnelStep: bubble.index + 1,
      sendFailures: 0,
    });
    if (bubble !== bubbles[bubbles.length - 1]) {
      await sleep(700);
    }
  }
  return sentTexts;
}

async function moveToRegistrationFolderIfLinkSent(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  replies: Awaited<ReturnType<PagerClient["getSavedReplies"]>>,
  outgoingTexts: string[],
): Promise<boolean> {
  if (!folderRegistrationLinkWasSent(replies, outgoingTexts)) {
    return false;
  }
  return maybeEnsureInProgressAfterRegLink(
    deps,
    state,
    client,
    conv,
    convId,
    runtime.channelId,
    runtime.runtime.country,
    outgoingTexts,
    () => true,
  );
}

async function trySendMissingRegistrationLink(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convId: string,
  convState: ConversationRuntimeState,
  outgoingTexts: string[],
): Promise<boolean> {
  const language = folderMarketLanguage(runtime.runtime.country);
  if (!language || !isFolderMarket(runtime.runtime.country)) {
    return false;
  }
  const folderId =
    runtime.runtime.templateBankId || pickLiveTemplateBank(state, runtime.runtime.country)?.id;
  if (!folderId) {
    return false;
  }
  let replies;
  try {
    replies = await client.getSavedReplies(folderId);
  } catch (error) {
    console.warn(`Pager worker: saved replies failed ${convId.slice(0, 8)}:`, formatError(error));
    return false;
  }
  const missing = planMissingRegistrationLink(replies, outgoingTexts);
  let covered = [...outgoingTexts];
  if (missing?.length) {
    console.log(
      `Pager worker: ${runtime.runtime.country} ${convId.slice(0, 8)} registration link follow-up ${missing.map((bubble) => bubble.role).join("+")}`,
    );
    const sentTexts = await deliverPresetBubbles(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      undefined,
      missing,
    );
    covered = [...outgoingTexts, ...sentTexts];
  }
  return moveToRegistrationFolderIfLinkSent(
    deps,
    state,
    client,
    conv,
    runtime,
    convId,
    replies,
    covered,
  );
}

async function processFolderMarketConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  _channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;
  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);
  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 80);
  if (!messages.length) {
    return false;
  }
  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const spanish = folderMarketLanguage(runtime.runtime.country) === "es";
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, spanish ? "ZM" : "CM");
  if (!lastIncoming) {
    return false;
  }
  const operatorUserId = await client.probeOperatorUserId();
  const outgoingTexts = messages
    .filter((message) => {
      const direction = (message.messageDirection ?? "").toLowerCase();
      return (direction === "outgoing" || direction === "out") && Boolean((message.text || "").trim());
    })
    .map((message) => (message.text || "").trim());
  if (
    shouldSkipConversationBotSpokeLast(conv, sorted, lastIncoming, {
      operatorUserId,
      country: spanish ? "ZM" : "CM",
      catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
    })
  ) {
    return trySendMissingRegistrationLink(
      deps,
      state,
      client,
      conv,
      runtime,
      convId,
      convState,
      outgoingTexts,
    );
  }
  const latestCustomerText = (lastIncoming.text || "").trim();
  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
      {
        operatorUserId,
        countryLabel: runtime.runtime.country,
        country: spanish ? "ZM" : "DJ",
        catchUpRead: isCatchUpReadActive(currentState.catchUpRead),
      },
    ))
  ) {
    return false;
  }

  return trySendFolderPreset(
    deps,
    state,
    client,
    conv,
    runtime,
    convId,
    convState,
    lastIncoming,
    outgoingTexts,
    latestCustomerText,
  );
}

async function processGenericConversation(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  channel: ReturnType<typeof buildRuntimeChannelConfig>,
): Promise<boolean> {
  const convId = conv.id;

  const currentState = (await deps.stateStore.get(state.chatId)) ?? state;
  const convState = getConversationState(currentState, convId, runtime.channelId);

  if ((convState.sendFailures ?? 0) >= MAX_SEND_FAILURES) {
    return false;
  }

  const messages = await client.listMessages(convId, 1, 50);
  if (!messages.length) {
    return false;
  }

  const sorted = [...messages].sort(
    (left, right) => Date.parse(right.createdAt ?? "") - Date.parse(left.createdAt ?? ""),
  );
  const lastIncoming = findLatestIncomingFromThread(sorted, conv, channel.country);
  if (!lastIncoming) {
    return false;
  }

  if (
    !(await ensureCustomerMessageEligible(
      deps,
      state,
      client,
      conv,
      convId,
      convState,
      lastIncoming,
      sorted,
    ))
  ) {
    return false;
  }

  await tryTakeConversationForProcessing(client, convId);

  const playbook = getPlaybook(deps.config, channel.country);
  const latestCustomerText = (lastIncoming.text || "").trim();
  const imageUrl = extractProofImageUrl(lastIncoming);
  const outgoingTexts = messages
    .filter((message) => {
      const direction = (message.messageDirection ?? "").toLowerCase();
      return (direction === "outgoing" || direction === "out") && Boolean((message.text || "").trim());
    })
    .map((message) => (message.text || "").trim());

  const specialHandled = await trySendSpecialCustomerResponse(deps, {
    state,
    client,
    conv,
    runtime,
    channel,
    convState,
    convId,
    lastIncoming,
    text: latestCustomerText,
    playbook,
    outgoingTexts,
  });
  if (specialHandled) {
    return true;
  }

  let proofKind;
  if (imageUrl) {
    try {
      const image = await client.downloadAttachment(imageUrl);
      const classification = await classifyProofFromImage(playbook, image, {
        caption: latestCustomerText,
        ocrEnabled: deps.env.OCR_ENABLED,
        ocrLang: ocrLangForCountry(channel.country),
      });
      proofKind = classification.proofKind;
    } catch (error) {
      console.warn(`OCR failed for ${convId.slice(0, 8)}:`, formatError(error));
      const classification = classifyProofFromText(playbook, latestCustomerText);
      proofKind = classification.proofKind;
    }
  }

  const decision = decideNextAction(deps.config, channel, {
    channelId: channel.id,
    currentStage: convState.currentStage,
    latestCustomerText: latestCustomerText || (imageUrl ? "(image)" : undefined),
    proofKind,
  });

  if (!decision?.templateRole) {
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)} — no rule matched (stage=${convState.currentStage}, text=${truncate(latestCustomerText)})`,
    );
    return false;
  }

  const templateRole = decision.templateRole;
  const replyText = await resolveTemplateText(deps.config, client, {
    folderId: runtime.runtime.templateBankId,
    yamlBankName: channel.templateBank,
    role: templateRole,
    country: channel.country,
  });

  if (!replyText?.trim()) {
    console.warn(`No template text resolved for ${convId.slice(0, 8)} role=${templateRole}`);
    return false;
  }

  console.log(
    `Pager worker: sending to ${convId.slice(0, 8)} channel=${runtime.channelName} role=${templateRole} bank=${runtime.runtime.templateBankId?.slice(0, 8) ?? "yaml"}`,
  );

  const sent = await client.sendMessageReliable(convId, replyText.trim(), {
    channelId: runtime.channelId,
    conv,
  });

  if (!sent) {
    const failures = (convState.sendFailures ?? 0) + 1;
    await patchConversationState(deps.stateStore, state.chatId, convId, {
      sendFailures: failures,
    });
    console.error(`Pager worker: send failed for ${convId.slice(0, 8)} (failures=${failures})`);
    return false;
  }

  await patchConversationState(deps.stateStore, state.chatId, convId, {
    conversationId: convId,
    channelId: runtime.channelId,
    currentStage: decision.nextStage,
    lastCustomerMessageId: lastIncoming.id,
    lastCustomerMessageAt: lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: templateRole,
    sendFailures: 0,
  });

  return true;
}

function listStatusFolders(state: ChatState): StatusFolderState[] {
  return state.operatorSettings?.statusFolders ?? state.statusFolders ?? [];
}

function findZmWaitingIdStatusId(state: ChatState): string | undefined {
  for (const folder of listStatusFolders(state)) {
    const name = folder.name.trim().toLowerCase();
    if (/чекаю\s*id|waiting.*id|жду\s*айди|attente.*id/i.test(name)) {
      return folder.id;
    }
  }
  return undefined;
}

function scoreInProgressStatusFolderName(name: string): number {
  const normalized = name.trim().toLowerCase();
  if (/чекаю\s*id|waiting.*id|жду\s*айди|attente.*id/i.test(normalized)) {
    return -1;
  }
  if (isZmInProgressRegistrationStatusName(normalized)) {
    return 100;
  }
  if (
    /в процес[сеіi]*\s*рег|процес.*рег|in registration process|en cours.*inscri|registration process/i.test(
      normalized,
    )
  ) {
    return 100;
  }
  if (/^в процес[сеіi]*$|^in progress$|^en cours$/i.test(normalized)) {
    return 90;
  }
  if (/в процес|у процес|процес|process|рега|реєстраці|регистрац|не заверш|en cours/i.test(normalized)) {
    return 50;
  }
  return 0;
}

function findFunnelFollowUpStatusId(state: ChatState): string | undefined {
  let best: { id: string; score: number } | undefined;
  for (const folder of listStatusFolders(state)) {
    if (!folder.id || folder.id === NO_STATUS_FOLDER_ID || folder.id === ALL_INBOX_FOLDER_ID) {
      continue;
    }
    const score = scoreInProgressStatusFolderName(folder.name);
    if (score <= 0) {
      continue;
    }
    if (!best || score > best.score) {
      best = { id: folder.id, score };
    }
  }
  return best?.id;
}

async function schedulePendingInProgressMove(
  deps: WorkerDeps,
  chatId: number,
  convId: string,
  channelId: string,
): Promise<void> {
  await patchConversationState(deps.stateStore, chatId, convId, {
    conversationId: convId,
    channelId,
    pendingInProgressMoveAt: new Date().toISOString(),
  });
}

async function clearPendingInProgressMove(
  deps: WorkerDeps,
  chatId: number,
  convId: string,
  channelId: string,
): Promise<void> {
  await patchConversationState(deps.stateStore, chatId, convId, {
    conversationId: convId,
    channelId,
    pendingInProgressMoveAt: undefined,
  });
}

async function retryPendingInProgressMoves(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  enabledChannels: EnabledChannel[],
): Promise<void> {
  const entries = Object.entries(state.conversations ?? {});
  if (!entries.length) {
    return;
  }

  const nowMs = Date.now();
  for (const [convId, convState] of entries) {
    if (convState.inProgressEnteredAt?.trim() || convState.pendingInProgressMoveAt?.trim()) {
      continue;
    }
    if (
      convState.lastReplyRole !== "06_link" &&
      convState.lastReplyRole !== "07_chrome" &&
      convState.lastReplyRole !== "05_link" &&
      convState.lastReplyRole !== "05_registration"
    ) {
      continue;
    }
    const lastReplyMs = Date.parse(convState.lastReplyAt ?? "");
    if (!Number.isFinite(lastReplyMs) || nowMs - lastReplyMs > 7 * 24 * 60 * 60 * 1000) {
      continue;
    }
    await schedulePendingInProgressMove(deps, state.chatId, convId, convState.channelId);
  }

  const byChannel = new Map(enabledChannels.map((channel) => [channel.channelId, channel]));
  let retried = 0;
  let fixed = 0;

  for (const [convId, convState] of entries) {
    if (!convState.pendingInProgressMoveAt?.trim()) {
      continue;
    }
    if (convState.inProgressEnteredAt?.trim()) {
      await clearPendingInProgressMove(deps, state.chatId, convId, convState.channelId);
      continue;
    }

    const runtime = byChannel.get(convState.channelId);
    if (!runtime) {
      continue;
    }
    const country = runtime.runtime.country;
    if (country !== "CM" && country !== "CL" && country !== "EG") {
      continue;
    }

    retried += 1;
    let conv: PagerConversation | undefined;
    try {
      conv = await client.openConversation(convId);
    } catch {
      continue;
    }
    if (!conv) {
      continue;
    }
    if (isInProgressStatusConversation(conv)) {
      await onMovedToInProgressRegistration(deps, state.chatId, convId, convState.channelId);
      await clearPendingInProgressMove(deps, state.chatId, convId, convState.channelId);
      fixed += 1;
      continue;
    }

    const messages = await client.listMessages(convId, 1, 80);
    const outgoingTexts =
      country === "CM"
        ? collectCmOutgoingTexts(messages)
        : country === "CL"
          ? collectClOutgoingTexts(messages)
          : collectEgOutgoingTexts(messages);
    const regLinkSent =
      country === "CM"
        ? cmRegLinkSentInHistory
        : country === "CL"
          ? clRegLinkSentInHistory
          : egRegLinkSentInHistory;
    if (!regLinkSent(outgoingTexts)) {
      await clearPendingInProgressMove(deps, state.chatId, convId, convState.channelId);
      continue;
    }

    const moved = await tryMoveConversationToInProgressRegistration(
      deps,
      state,
      client,
      conv,
      convId,
      convState.channelId,
      country,
    );
    if (moved) {
      fixed += 1;
      await clearPendingInProgressMove(deps, state.chatId, convId, convState.channelId);
    }
  }

  if (retried) {
    console.log(`Pager worker: pending in-progress retry checked=${retried} fixed=${fixed}`);
  }
}

async function tryMoveConversationToIgnore(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  convId: string,
  channelId: string,
  countryLabel: string,
): Promise<boolean> {
  if (isIgnoreStatusConversation(conv)) {
    await onMovedToIgnore(deps, state.chatId, convId, channelId);
    return true;
  }

  let workingState = state;
  let statusId = findIgnoreStatusId(workingState);
  if (!statusId) {
    workingState = (await ensureStatusFolders(deps, workingState, client)) ?? workingState;
    statusId = findIgnoreStatusId(workingState);
  }

  const operatorId = await client.probeOperatorUserId();
  const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
  if (!statusId) {
    console.warn(
      `Pager worker: ${countryLabel} ${convId.slice(0, 8)} ignore move skipped — ИГНОР folder not found`,
    );
    return false;
  }
  if (!operatorId) {
    console.warn(
      `Pager worker: ${countryLabel} ${convId.slice(0, 8)} ignore move skipped — no operator user id`,
    );
    return false;
  }
  if (currentStatusId === statusId) {
    await onMovedToIgnore(deps, state.chatId, convId, channelId);
    return true;
  }

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await tryTakeConversationForProcessing(client, convId, countryLabel);
      await client.patchConversationStatus(convId, statusId, operatorId);
      console.log(`Pager worker: ${countryLabel} ${convId.slice(0, 8)} status -> ignore`);
      await onMovedToIgnore(deps, state.chatId, convId, channelId);
      return true;
    } catch (error) {
      if (attempt >= 3) {
        console.warn(
          `Pager worker: ignore status patch failed ${convId.slice(0, 8)} after ${attempt} attempts:`,
          formatError(error),
        );
        return false;
      }
      await sleep(500 * attempt);
    }
  }
  return false;
}

function hasTrollFunnelProgress(country: string, outgoingTexts: string[]): boolean {
  if (country === "CL") {
    return (
      clTierSentInHistory(outgoingTexts) ||
      clRegLinkSentInHistory(outgoingTexts) ||
      clDepositSentInHistory(outgoingTexts)
    );
  }
  if (country === "CM") {
    return (
      tierSentInHistory(outgoingTexts) ||
      cmRegLinkSentInHistory(outgoingTexts) ||
      cmDepositSentInHistory(outgoingTexts)
    );
  }
  return false;
}

async function tryHandleTrollCustomerToIgnore(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  runtime: EnabledChannel,
  convState: ConversationRuntimeState,
  convId: string,
  country: import("./customer-troll.js").TrollDetectionCountry,
  latestCustomerText: string,
  recentCustomerTexts: string[],
  outgoingTexts: string[],
  funnelStep: number,
  latestHasImage: boolean,
): Promise<boolean> {
  if (!isTrollDetectionCountry(country)) {
    return false;
  }
  if (convState.ignoredAt || isIgnoreStatusConversation(conv)) {
    return true;
  }
  if (
    !shouldIgnoreTrollCustomer(
      latestCustomerText,
      recentCustomerTexts,
      {
        hasFunnelProgress: hasTrollFunnelProgress(country, outgoingTexts),
        latestHasImage,
      },
      funnelStep,
    )
  ) {
    return false;
  }

  console.log(
    `Pager worker: ${country} ${convId.slice(0, 8)} troll detected — moving to ignore (text=${truncate(latestCustomerText)})`,
  );

  const moved = await tryMoveConversationToIgnore(
    deps,
    state,
    client,
    conv,
    convId,
    runtime.channelId,
    country,
  );
  if (!moved) {
    return false;
  }

  try {
    await client.acknowledgeConversation(convId);
  } catch {
    // non-fatal
  }
  return true;
}

async function tryMoveConversationToInProgressRegistration(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  convId: string,
  channelId: string,
  countryLabel: string,
): Promise<boolean> {
  if (isInProgressStatusConversation(conv)) {
    return true;
  }

  let workingState = state;
  let statusId = findFunnelFollowUpStatusId(workingState);
  if (!statusId) {
    workingState = (await ensureStatusFolders(deps, workingState, client)) ?? workingState;
    statusId = findFunnelFollowUpStatusId(workingState);
  }

  const operatorId = await client.probeOperatorUserId();
  const currentStatusId = (conv.statusId ?? conv.status?.id ?? "").trim();
  if (!statusId) {
    console.warn(
      `Pager worker: ${countryLabel} ${convId.slice(0, 8)} status move skipped — in-progress folder not found`,
    );
    return false;
  }
  if (!operatorId) {
    console.warn(
      `Pager worker: ${countryLabel} ${convId.slice(0, 8)} status move skipped — no operator user id`,
    );
    return false;
  }
  if (currentStatusId === statusId) {
    await onMovedToInProgressRegistration(deps, state.chatId, convId, channelId);
    return true;
  }

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await tryTakeConversationForProcessing(client, convId, countryLabel);
      await client.patchConversationStatus(convId, statusId, operatorId);
      console.log(`Pager worker: ${countryLabel} ${convId.slice(0, 8)} status -> in progress`);
      await onMovedToInProgressRegistration(deps, state.chatId, convId, channelId);
      return true;
    } catch (error) {
      if (attempt >= 3) {
        console.warn(
          `Pager worker: status patch failed ${convId.slice(0, 8)} after ${attempt} attempts:`,
          formatError(error),
        );
        return false;
      }
      await sleep(500 * attempt);
    }
  }
  return false;
}

async function maybeEnsureInProgressAfterRegLink(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  convId: string,
  channelId: string,
  countryLabel: string,
  outgoingTexts: string[],
  regLinkSent: (out: string[]) => boolean,
): Promise<boolean> {
  if (!regLinkSent(outgoingTexts)) {
    return false;
  }
  if (isInProgressStatusConversation(conv)) {
    await clearPendingInProgressMove(deps, state.chatId, convId, channelId);
    const convState = getConversationState(state, convId, channelId);
    if (!convState.inProgressEnteredAt?.trim()) {
      const lastReplyMs = Date.parse(convState.lastReplyAt ?? "");
      await onMovedToInProgressRegistration(
        deps,
        state.chatId,
        convId,
        channelId,
        Number.isFinite(lastReplyMs) ? lastReplyMs : undefined,
      );
    }
    return false;
  }
  await schedulePendingInProgressMove(deps, state.chatId, convId, channelId);
  const moved = await tryMoveConversationToInProgressRegistration(
    deps,
    state,
    client,
    conv,
    convId,
    channelId,
    countryLabel,
  );
  if (moved) {
    await clearPendingInProgressMove(deps, state.chatId, convId, channelId);
  }
  return moved;
}

function findZmStatusId(state: ChatState, target: ZmStatusMoveTarget): string | undefined {
  for (const folder of listStatusFolders(state)) {
    if (target === "in_progress_registration" && isZmInProgressRegistrationStatusName(folder.name)) {
      return folder.id;
    }
    if (target === "registration_complete" && isZmRegistrationCompleteStatusName(folder.name)) {
      return folder.id;
    }
  }
  if (target === "in_progress_registration") {
    return findFunnelFollowUpStatusId(state);
  }
  return undefined;
}

type EnabledChannel = {
  channelId: string;
  channelName: string;
  runtime: ChannelRuntimeState;
};

function isChannelAllowed(config: BotConfig, state: ChatState, channelId: string): boolean {
  if (isChannelConfigured(config, channelId)) {
    return true;
  }
  return Boolean(state.channels?.[channelId]?.country);
}

function getEnabledChannels(config: BotConfig, state: ChatState): EnabledChannel[] {
  const enabledIds = new Set(
    collectEnabledChannelIdsFromState(state).filter((channelId) =>
      isChannelAllowed(config, state, channelId),
    ),
  );
  const liveChannels = state.pagerAccount?.liveChannels ?? [];
  const enabled: EnabledChannel[] = [];

  if (liveChannels.length) {
    const added = new Set<string>();
    for (const channel of liveChannels) {
      if (!enabledIds.has(channel.id)) {
        continue;
      }
      const yamlChannel = getChannelConfig(config, channel.id);
      const saved = state.channels?.[channel.id];
      const resolved = resolveWorkerCountryForChannel(
        channel.name,
        saved?.country,
        yamlChannel?.country,
      );
      const country =
        coerceMelbetCountry(resolved, saved?.templateBank ?? yamlChannel?.templateBank, channel.name) ??
        resolved;
      const bank = pickLiveTemplateBank(state, country);
      const runtime: ChannelRuntimeState = saved
        ? { ...saved, country }
        : {
            enabled: true,
            country,
            templateBank: yamlChannel?.templateBank ?? bank?.name,
            templateBankId: bank?.id,
          };
      enabled.push({
        channelId: channel.id,
        channelName: channel.name,
        runtime,
      });
      added.add(channel.id);
    }
    for (const channelId of enabledIds) {
      if (added.has(channelId)) {
        continue;
      }
      const yamlChannel = getChannelConfig(config, channelId);
      const liveChannel = liveChannels.find((channel) => channel.id === channelId);
      const saved = state.channels?.[channelId];
      const resolved = resolveWorkerCountryForChannel(
        liveChannel?.name ?? yamlChannel?.name ?? "",
        saved?.country,
        yamlChannel?.country,
      );
      const country =
        coerceMelbetCountry(
          resolved,
          saved?.templateBank ?? yamlChannel?.templateBank,
          liveChannel?.name ?? yamlChannel?.name,
        ) ?? resolved;
      const bank = pickLiveTemplateBank(state, country);
      const runtime: ChannelRuntimeState = saved
        ? { ...saved, country }
        : {
            enabled: true,
            country,
            templateBank: yamlChannel?.templateBank ?? bank?.name,
            templateBankId: bank?.id,
          };
      enabled.push({
        channelId,
        channelName: liveChannel?.name ?? yamlChannel?.name ?? channelId.slice(0, 8),
        runtime,
      });
    }
    return enabled;
  }

  for (const channelId of enabledIds) {
    const yamlChannel = getChannelConfig(config, channelId);
    const country = resolveWorkerCountryForChannel(
      yamlChannel?.name ?? "",
      state.channels?.[channelId]?.country,
      yamlChannel?.country,
    );
    const bank = pickLiveTemplateBank(state, country);
    const saved = state.channels?.[channelId];
    const runtime: ChannelRuntimeState = saved
      ? { ...saved, country }
      : {
          enabled: true,
          country,
          templateBank: yamlChannel?.templateBank ?? bank?.name,
          templateBankId: bank?.id,
        };
    enabled.push({
      channelId,
      channelName: yamlChannel?.name ?? channelId.slice(0, 8),
      runtime,
    });
  }
  return enabled;
}

function logConversationCountsByChannel(
  enabledChannels: EnabledChannel[],
  conversations: PagerConversation[],
  chatId: number,
): void {
  const counts = new Map<string, number>();
  for (const conv of conversations) {
    const channelId = conv.channelId || conv.channel?.id;
    if (!channelId) {
      continue;
    }
    counts.set(channelId, (counts.get(channelId) ?? 0) + 1);
  }

  const parts = enabledChannels.map((channel) => {
    const count = counts.get(channel.channelId) ?? 0;
    return `${channel.channelName}/${channel.runtime.country}=${count}`;
  });
  console.log(`Pager worker: chat ${chatId} — perChannel=[${parts.join(", ")}]`);
}

async function refreshLiveChannelsFromApi(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
): Promise<ChatState | undefined> {
  try {
    const liveChannels = await client.getChannels();
    if (!liveChannels.length) {
      return state;
    }

    const liveTemplateBanks = await client.getTemplateBanks().catch(() => []);
    const channels: Record<string, ChannelRuntimeState> = { ...(state.channels ?? {}) };
    for (const channel of liveChannels) {
      const existing = channels[channel.id];
      const yamlChannel = getChannelConfig(deps.config, channel.id);
      const country =
        existing?.country ??
        yamlChannel?.country ??
        inferCountryFromChannelName(channel.name);
      const bank = pickLiveTemplateBank(
        {
          ...state,
          pagerAccount: {
            ...(state.pagerAccount ?? { authMode: "cookies", connectedAt: state.updatedAt }),
            liveTemplateBanks: liveTemplateBanks.map((item) => ({
              id: item.id,
              name: item.name,
              replyCount: item.replyCount,
            })),
          },
        },
        country,
      );
      channels[channel.id] = {
        enabled: existing?.enabled ?? collectEnabledChannelIdsFromState(state).includes(channel.id),
        country,
        templateBank: existing?.templateBank ?? yamlChannel?.templateBank ?? bank?.name,
        templateBankId: existing?.templateBankId ?? bank?.id,
      };
    }

    return deps.stateStore.patch(state.chatId, {
      channels,
      pagerAccount: {
        ...(state.pagerAccount ?? { authMode: "cookies", connectedAt: state.updatedAt }),
        liveChannels: liveChannels.map((channel) => ({
          id: channel.id,
          name: channel.name,
          channelSource: channel.channelSource,
        })),
        liveTemplateBanks: liveTemplateBanks.map((bank) => ({
          id: bank.id,
          name: bank.name,
          replyCount: bank.replyCount,
        })),
      },
    });
  } catch (error) {
    console.warn(
      `Pager worker: chat ${state.chatId} — live channel refresh failed:`,
      formatError(error),
    );
    return state;
  }
}

type FunnelSendCountry = "CM" | "ZM" | "EG" | "RW" | "CL" | "MG" | "DJ" | "JO";

/** Re-read thread before send — avoids duplicate scripts when two cycles race (e.g. catch-up kick). */
async function dropScriptKeysAlreadyInThread(
  client: PagerClient,
  convId: string,
  country: FunnelSendCountry,
  scriptKeys: string[],
  rwDrafts?: ReturnType<typeof rwActiveScriptDrafts>,
): Promise<string[]> {
  const unique = [...new Set(scriptKeys)];
  if (!unique.length) {
    return unique;
  }
  const messages = await client.listMessages(convId, 1, 80);
  if (country === "CM") {
    const out = collectCmOutgoingTexts(messages);
    return unique.filter((key) => !cmScriptSentInHistory(out, key));
  }
  if (country === "CL") {
    const out = collectClOutgoingTexts(messages);
    return unique.filter((key) => !clScriptSentInHistory(out, key));
  }
  if (country === "ZM") {
    const out = collectZmOutgoingTexts(messages);
    return unique.filter((key) => !zmScriptSentInHistory(out, key));
  }
  if (country === "MG") {
    const out = collectMgOutgoingTexts(messages);
    return unique.filter((key) => !mgScriptSentInHistory(out, key));
  }
  if (country === "DJ") {
    const out = collectDjOutgoingTexts(messages);
    return unique.filter((key) => !djScriptSentInHistory(out, key));
  }
  if (country === "JO") {
    const out = collectJoOutgoingTexts(messages);
    return unique.filter((key) => !joScriptSentInHistory(out, key));
  }
  if (country === "RW") {
    const out = collectRwOutgoingTexts(messages);
    return unique.filter(
      (key) => !rwScriptSentInHistory(out, key as RwScriptKey, rwDrafts),
    );
  }
  const out = collectEgOutgoingTexts(messages);
  return unique.filter((key) => !egScriptSentInHistory(out, key));
}

async function tryTakeConversationForProcessing(
  client: PagerClient,
  convId: string,
  countryLabel?: string,
): Promise<void> {
  const operatorId = await client.probeOperatorUserId();
  if (!operatorId) {
    return;
  }
  try {
    const taken = await client.takeConversation(convId, operatorId);
    if (taken) {
      const label = countryLabel ? ` ${countryLabel}` : "";
      console.log(`Pager worker: take ${convId.slice(0, 8)}${label} ok`);
    }
  } catch (error) {
    console.warn(`Pager worker: take ${convId.slice(0, 8)} failed:`, formatError(error));
  }
}

function getLiveChannelCoverage(config: BotConfig, state: ChatState): {
  enabledIds: string[];
  missingFromLive: string[];
} {
  const enabledIds = collectEnabledChannelIdsFromState(state).filter((channelId) =>
    isChannelAllowed(config, state, channelId),
  );
  const liveIds = new Set((state.pagerAccount?.liveChannels ?? []).map((channel) => channel.id));
  return {
    enabledIds,
    missingFromLive: enabledIds.filter((channelId) => !liveIds.has(channelId)),
  };
}

function collectEnabledChannelIdsFromState(state: ChatState): string[] {
  const enabled = new Set(state.operatorSettings?.enabledChannelIds ?? []);
  for (const id of state.enabledChannelIds ?? []) {
    enabled.add(id);
  }
  for (const [channelId, runtime] of Object.entries(state.channels ?? {})) {
    if (runtime.enabled) {
      enabled.add(channelId);
    }
  }
  return [...enabled];
}

function hydrateOperatorState(state: ChatState): ChatState {
  const enabledChannelIds = collectEnabledChannelIdsFromState(state);
  const statusFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  return {
    ...state,
    enabledChannelIds,
    statusFolders,
  };
}

async function normalizeEnabledChannelsToConfig(
  deps: WorkerDeps,
  state: ChatState,
): Promise<ChatState | undefined> {
  const current = collectEnabledChannelIdsFromState(state);
  const filtered = current.filter((channelId) => isChannelAllowed(deps.config, state, channelId));
  if (filtered.length === current.length) {
    return state;
  }

  const channels: Record<string, ChannelRuntimeState> = { ...(state.channels ?? {}) };
  for (const [channelId, runtime] of Object.entries(channels)) {
    channels[channelId] = { ...runtime, enabled: filtered.includes(channelId) };
  }

  const statusFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  console.log(
    `Pager worker: chat ${state.chatId} — trimmed enabled channels ${current.length} → ${filtered.length} (config whitelist)`,
  );
  return deps.stateStore.patch(state.chatId, {
    enabledChannelIds: filtered,
    channels,
    operatorSettings: {
      enabledChannelIds: filtered,
      statusFolders,
    },
  });
}

async function seedEnabledChannelsFromYaml(
  deps: WorkerDeps,
  state: ChatState,
): Promise<ChatState | undefined> {
  const live = state.pagerAccount?.liveChannels ?? [];
  if (!live.length) {
    return state;
  }

  const liveIds = new Set(live.map((channel) => channel.id));
  let enabledChannelIds = getConfigEnabledChannelIds(deps.config).filter((channelId) =>
    liveIds.has(channelId),
  );
  if (!enabledChannelIds.length) {
    enabledChannelIds = deps.config.channels
      .map((channel) => channel.id)
      .filter((channelId) => liveIds.has(channelId));
  }
  if (!enabledChannelIds.length) {
    return state;
  }

  const channels: Record<string, ChannelRuntimeState> = { ...(state.channels ?? {}) };
  for (const channel of live) {
    const existing = channels[channel.id];
    const yamlChannel = getChannelConfig(deps.config, channel.id);
    const country = existing?.country ?? yamlChannel?.country ?? inferCountryFromChannelName(channel.name);
    const bank = pickLiveTemplateBank(state, country);
    channels[channel.id] = {
      enabled: enabledChannelIds.includes(channel.id),
      country,
      templateBank: existing?.templateBank ?? yamlChannel?.templateBank ?? bank?.name,
      templateBankId: existing?.templateBankId ?? bank?.id,
    };
  }

  const statusFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  return deps.stateStore.patch(state.chatId, {
    enabledChannelIds,
    channels,
    operatorSettings: {
      enabledChannelIds,
      statusFolders,
    },
  });
}

async function ensureCustomerMessageEligible(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  conv: PagerConversation,
  convId: string,
  convState: ConversationRuntimeState,
  lastIncoming: PagerMessage,
  sorted: PagerMessage[],
  options?: {
    bypass?: boolean;
    operatorUserId?: string;
    countryLabel?: string;
    country?: "ZM" | "CM" | "EG" | "CL" | "MG" | "DJ" | "JO";
    catchUpRead?: boolean;
  },
): Promise<boolean> {
  const country = options?.country ?? (options?.countryLabel as "ZM" | "CM" | "EG" | "CL" | "MG" | "DJ" | "JO" | undefined);
  const catchUpRead = Boolean(options?.catchUpRead);
  const threadCountry: CountryCode | undefined =
    country === "CL" || country === "MG" || country === "DJ"
      ? "CM"
      : country === "JO"
        ? "EG"
        : (country as CountryCode | undefined);
  const customerText = (lastIncoming.text || "").trim();
  const isNewCustomerTurn = convState.lastCustomerMessageId !== lastIncoming.id;
  const alreadyRepliedInState =
    !isNewCustomerTurn &&
    convState.lastCustomerMessageId === lastIncoming.id &&
    Boolean(convState.lastReplyAt);
  const botAlreadyReplied = hasBotReplyAfterCustomerMessage(
    sorted,
    lastIncoming,
    conv,
    options?.operatorUserId,
    threadCountry,
  );
  const unreadOrIncoming =
    hasUnreadMarkers(conv) || isIncomingDirection(conv.lastMessageDirection);
  const customerMessageFresh = isFreshCustomerMessage(lastIncoming.createdAt);
  const actionable = isActionableCustomerMessage(
    lastIncoming,
    conv,
    convState,
    sorted,
    { country: threadCountry, operatorUserId: options?.operatorUserId, catchUpRead },
  );
  // Unread / customer-last must reach the script engine — never bury a backlog behind state locks.
  const unreadNeedsScriptPass =
    unreadOrIncoming && !botAlreadyReplied && actionable;

  const funnelContinuation =
    actionable &&
    ((country === "EG" &&
      egFunnelNeedsContinuation(customerText, collectEgOutgoingTexts(sorted))) ||
      (country === "CM" &&
        cmFunnelNeedsContinuation(customerText, collectCmOutgoingTexts(sorted), {
          hasImage: Boolean(extractProofImageUrl(lastIncoming)),
        })) ||
      (country === "CL" &&
        clFunnelNeedsContinuation(customerText, collectClOutgoingTexts(sorted), {
          hasImage: Boolean(extractProofImageUrl(lastIncoming)),
        })) ||
      (country === "ZM" &&
        zmFunnelNeedsContinuation(customerText, collectZmOutgoingTexts(sorted), {
          hasImage: Boolean(extractProofImageUrl(lastIncoming)),
        })));

  if ((options?.bypass && actionable) || unreadNeedsScriptPass || funnelContinuation) {
    return true;
  }

  // State can falsely lock after a bad thread-sync; unread without a delivered bot reply stays open.
  const staleStateLock =
    alreadyRepliedInState && !botAlreadyReplied && unreadOrIncoming;

  if (alreadyRepliedInState && !staleStateLock) {
    const label = options?.countryLabel ? ` ${options.countryLabel}` : "";
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)}${label} — awaiting_customer_reply (text=${truncate(customerText)})`,
    );
    if (unreadOrIncoming && botAlreadyReplied) {
      try {
        await client.acknowledgeConversation(convId);
      } catch {
        // non-fatal
      }
    }
    return false;
  }

  if (!isNewCustomerTurn && botAlreadyReplied) {
    const label = options?.countryLabel ? ` ${options.countryLabel}` : "";
    console.log(
      `Pager worker: skip ${convId.slice(0, 8)}${label} — awaiting_customer_reply (text=${truncate(customerText)})`,
    );
    if (unreadOrIncoming && botAlreadyReplied) {
      try {
        await client.acknowledgeConversation(convId);
      } catch {
        // non-fatal
      }
    }
    return false;
  }

  if (isNewCustomerTurn) {
    if (botAlreadyReplied || !actionable) {
      // Bookkeeping only — do NOT invent lastReplyAt (that permanently locks the chat).
      await patchConversationState(deps.stateStore, state.chatId, convId, {
        conversationId: convId,
        channelId: convState.channelId,
        lastCustomerMessageId: lastIncoming.id,
        lastCustomerMessageAt: lastIncoming.createdAt,
      });
      const label = options?.countryLabel ? ` ${options.countryLabel}` : "";
      console.log(
        `Pager worker: skip ${convId.slice(0, 8)}${label} — awaiting_customer_reply (thread synced, text=${truncate(customerText)})`,
      );
      if (unreadOrIncoming && botAlreadyReplied) {
        try {
          await client.acknowledgeConversation(convId);
        } catch {
          // non-fatal
        }
      }
      return false;
    }
    return true;
  }

  if (staleStateLock && actionable) {
    return true;
  }

  const eligibility = assessReplyEligibility(conv, convState, lastIncoming, sorted, {
    country: threadCountry,
    operatorUserId: options?.operatorUserId,
  });
  if (eligibility.eligible) {
    if (!actionable) {
      const label = options?.countryLabel ? ` ${options.countryLabel}` : "";
      console.log(
        `Pager worker: skip ${convId.slice(0, 8)}${label} — stale_customer_message (text=${truncate(customerText)})`,
      );
      return false;
    }
    return true;
  }

  // Never acknowledge/markSeen on skip — take+ack before scripts caused overnight unread silence.
  const label = options?.countryLabel ? ` ${options.countryLabel}` : "";
  console.log(
    `Pager worker: skip ${convId.slice(0, 8)}${label} — ${eligibility.reason} (text=${truncate((lastIncoming.text || "").trim())})`,
  );
  return false;
}

function inferCountryFromChannelName(name: string): WorkerCountry {
  return defaultCountryForChannelName(name);
}

function pickLiveTemplateBank(
  state: ChatState,
  country: WorkerCountry,
): { id: string; name: string } | undefined {
  const banks = state.pagerAccount?.liveTemplateBanks ?? [];
  if (!banks.length) {
    return undefined;
  }
  const hints: Record<WorkerCountry, string[]> = {
    ZM: ["замб", "zamb", "zambia"],
    EG: ["егип", "egypt", "hapka"],
    CM: ["камер", "cameroon", "cameroun"],
    RW: ["ruand", "rwand", "rw"],
    CL: ["chile", "chili", "чили", "cl"],
    MG: MG_FOLDER_NAME_HINTS,
    DJ: DJ_FOLDER_NAME_HINTS,
    JO: JO_FOLDER_NAME_HINTS,
    MR: ["мавритан", "mauritan"],
    BF: ["буркина", "burkina"],
    BJ: ["бенін", "бенин", "benin", "bénin"],
    CR: ["коста", "costa"],
    SN: ["сенегал", "senegal", "sénégal"],
  };
  if (isFolderOnlyCountry(country)) {
    const matchedOnly = banks.find((bank) => {
      const normalized = bank.name.toLowerCase();
      return hints[country].some((hint) => normalized.includes(hint));
    });
    return matchedOnly;
  }
  const matched = banks.find((bank) => {
    const normalized = bank.name.toLowerCase();
    return hints[country].some((hint) => normalized.includes(hint));
  });
  return matched ?? banks[0];
}

function getConversationState(
  state: ChatState,
  conversationId: string,
  channelId: string,
): ConversationRuntimeState {
  return (
    state.conversations?.[conversationId] ?? {
      conversationId,
      channelId,
      currentStage: "new_lead",
    }
  );
}

async function patchConversationState(
  stateStore: StateStore,
  chatId: number,
  conversationId: string,
  patch: Partial<ConversationRuntimeState>,
): Promise<void> {
  const current = await stateStore.get(chatId);
  if (!current) {
    return;
  }

  const existing = current.conversations?.[conversationId];
  const base =
    existing ??
    ({
      conversationId,
      channelId: patch.channelId ?? "",
      currentStage: "new_lead" as Stage,
    } satisfies ConversationRuntimeState);

  await stateStore.patch(chatId, {
    conversations: {
      ...(current.conversations ?? {}),
      [conversationId]: {
        ...base,
        ...patch,
        conversationId,
      },
    },
  });
}

function buildRuntimeChannelConfig(
  config: BotConfig,
  state: ChatState,
  runtime: EnabledChannel,
): ChannelConfig {
  const mapped = getChannelConfig(config, runtime.channelId);
  const country = runtime.runtime.country;
  const templateBank = resolveYamlTemplateBankName(config, country, runtime.channelId);
  const yamlCountry = (
    country === "RW" ||
    country === "CL" ||
    country === "MG" ||
    country === "DJ" ||
    isFolderOnlyCountry(country)
      ? "CM"
      : country === "JO"
        ? "EG"
        : country
  ) as CountryCode;

  return {
    id: runtime.channelId,
    name: runtime.channelName,
    enabled: true,
    country: yamlCountry,
    templateBank,
    statusMap: mapped?.statusMap ?? statusMapForCountry(config, country),
  };
}

/** True when this script body (or its opening) was already sent in the current batch/thread. */
function cmOutgoingAlreadyContainsText(outgoingTexts: string[], text: string): boolean {
  const body = text.trim().toLowerCase();
  if (!body) {
    return false;
  }
  const blob = outgoingTexts.join("\n").toLowerCase();
  if (!blob) {
    return false;
  }
  if (blob.includes(body)) {
    return true;
  }
  const needle = body.slice(0, Math.min(90, body.length));
  return needle.length >= 40 && blob.includes(needle);
}

function truncate(value: string, max = 40): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1)}…`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type SpecialResponseContext = {
  state: ChatState;
  client: PagerClient;
  conv: PagerConversation;
  runtime: EnabledChannel;
  channel: ChannelConfig;
  convState: ConversationRuntimeState;
  convId: string;
  lastIncoming: PagerMessage;
  text: string;
  playbook: ReturnType<typeof getPlaybook>;
  /** Outgoing bot texts already in the thread (preferred). */
  outgoingTexts?: string[];
};

/** True once a real funnel script went out — not money/phone refusals. */
function specialFunnelAlreadyStarted(ctx: SpecialResponseContext): boolean {
  if ((ctx.convState.funnelStep ?? 0) > 0) {
    return true;
  }
  const role = (ctx.convState.lastReplyRole || "").toLowerCase();
  if (
    role &&
    !["money_request", "phone_request", "no_money", "deferral", "declined", "scam_accusation"].includes(
      role,
    )
  ) {
    return true;
  }
  const out = ctx.outgoingTexts ?? [];
  if (out.length === 0) {
    return false;
  }
  return out.some((text) => !isSpecialRefusalOutgoing(text));
}

function isSpecialRefusalOutgoing(text: string): boolean {
  const t = (text || "").trim().toLowerCase();
  if (!t) {
    return true;
  }
  return (
    t.includes("don't give money") ||
    t.includes("do not give money") ||
    t.includes("ne donnons pas d'argent") ||
    t.includes("ne donnons pas d’argent") ||
    t.includes("no damos dinero") ||
    t.includes("لا نُعطي") ||
    t.includes("لا نعطي") ||
    t.includes("only communicate online") ||
    t.includes("uniquement en ligne") ||
    t.includes("solo en línea") ||
    t.includes("solo en linea") ||
    t.includes("نتواصل فقط")
  );
}

async function trySendSpecialCustomerResponse(
  deps: WorkerDeps,
  ctx: SpecialResponseContext,
): Promise<boolean> {
  const special = classifySpecialCustomerIntent(ctx.playbook, ctx.text);
  if (special === "none") {
    return false;
  }

  // First SMS in a thread: ALWAYS run country scripts (01_intro). Never money-refusal /
  // phone / no_money templates before the funnel has started.
  if (!specialFunnelAlreadyStarted(ctx)) {
    console.log(
      `Pager worker: defer special=${special} ${ctx.channel.country} ${ctx.convId.slice(0, 8)} — first touch, script 1 first (text=${truncate(ctx.text)})`,
    );
    return false;
  }

  if (special === "declined" || special === "scam_accusation") {
    console.log(
      `Pager worker: skip ${ctx.convId.slice(0, 8)} ${ctx.channel.country} — ${special} (text=${truncate(ctx.text)})`,
    );
    await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
      lastCustomerMessageId: ctx.lastIncoming.id,
      lastCustomerMessageAt: ctx.lastIncoming.createdAt,
      currentStage: special === "declined" ? "dormant" : ctx.convState.currentStage,
    });
    return false;
  }

  let replyText: string | undefined;
  let templateRole: TemplateRole | undefined;
  let nextStage: Stage = ctx.convState.currentStage;

  if (special === "money_request") {
    replyText = moneyRefusalText(ctx.channel.country);
    nextStage = "engaged";
  } else if (special === "phone_request") {
    replyText = phoneChatOnlyText(ctx.channel.country);
    nextStage = "engaged";
  } else {
    templateRole = specialIntentTemplateRole(special);
    if (!templateRole) {
      return false;
    }
    replyText = await resolveTemplateText(deps.config, ctx.client, {
      folderId: ctx.runtime.runtime.templateBankId,
      yamlBankName: ctx.channel.templateBank,
      role: templateRole,
      country: ctx.channel.country,
    });
    nextStage = special === "deferral" ? "not_ready" : "no_money";
  }

  if (!replyText?.trim()) {
    return false;
  }

  console.log(
    `Pager worker: ${ctx.channel.country} ${ctx.convId.slice(0, 8)} special=${special} role=${templateRole ?? "money_refusal"}`,
  );

  const sent = await ctx.client.sendMessageReliable(ctx.convId, replyText.trim(), {
    channelId: ctx.runtime.channelId,
    conv: ctx.conv,
  });
  if (!sent) {
    return false;
  }

  await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
    conversationId: ctx.convId,
    channelId: ctx.runtime.channelId,
    currentStage: nextStage,
    lastCustomerMessageId: ctx.lastIncoming.id,
    lastCustomerMessageAt: ctx.lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: templateRole ?? special,
    sendFailures: 0,
  });
  return true;
}

async function sendCmScriptKey(
  deps: WorkerDeps,
  ctx: SpecialResponseContext & { outgoingTexts: string[] },
  scriptKey: "09_deposit" | "08_game_id",
): Promise<boolean> {
  const currentState = (await deps.stateStore.get(ctx.state.chatId)) ?? ctx.state;
  const folderId = await resolveCmTemplateFolderId(
    ctx.client,
    ctx.runtime.runtime.templateBankId,
    currentState.pagerAccount?.liveTemplateBanks,
  );
  const replyText = await resolveScriptTextByKey(ctx.client, {
    folderId,
    liveBanks: currentState.pagerAccount?.liveTemplateBanks,
    scriptKey,
    country: "CM",
  });
  const body =
    replyText?.trim() ||
    (scriptKey === "09_deposit"
      ? loadLocalCmScript("09_deposit")
      : loadLocalCmScript("08_game_id"));
  if (!body?.trim()) {
    return false;
  }
  await tryTakeConversationForProcessing(ctx.client, ctx.convId, "CM");
  const sent = await ctx.client.sendMessageReliable(ctx.convId, body.trim(), {
    channelId: ctx.runtime.channelId,
    conv: ctx.conv,
  });
  if (!sent) {
    return false;
  }
  console.log(
    `Pager worker: CM ${ctx.convId.slice(0, 8)} proof -> ${scriptKey} build=${getDeployLabel()}`,
  );
  await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
    conversationId: ctx.convId,
    channelId: ctx.runtime.channelId,
    lastCustomerMessageId: ctx.lastIncoming.id,
    lastCustomerMessageAt: ctx.lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: scriptKey,
    currentStage: scriptKey === "09_deposit" ? "deposit_pending" : "waiting_id",
    sendFailures: 0,
  });
  return true;
}

async function trySendZmProofFromCombinedText(
  deps: WorkerDeps,
  ctx: SpecialResponseContext & { outgoingTexts: string[] },
  combinedText: string,
  proofKind: import("./config.js").ProofKind | undefined,
): Promise<boolean> {
  if (ctx.channel.country !== "ZM" || !zmRegLinkSentInHistory(ctx.outgoingTexts)) {
    return false;
  }
  const scriptKey = resolveZmProofScriptAfterDeposit(proofKind, combinedText, {
    depositScriptSent: zmDepositSentInHistory(ctx.outgoingTexts),
    gameIdScriptSent: gameIdSentInHistory(ctx.outgoingTexts),
  });
  if (!scriptKey) {
    return false;
  }
  return sendZmScriptKey(deps, ctx, scriptKey, { moveToWaitingId: true });
}

async function sendZmScriptKey(
  deps: WorkerDeps,
  ctx: SpecialResponseContext,
  scriptKey: string,
  options?: { moveToWaitingId?: boolean },
): Promise<boolean> {
  const currentState = (await deps.stateStore.get(ctx.state.chatId)) ?? ctx.state;
  const folderId = await resolveZmTemplateFolderId(
    ctx.client,
    ctx.runtime.runtime.templateBankId,
    currentState.pagerAccount?.liveTemplateBanks,
  );
  const replyText = await resolveScriptTextByKey(ctx.client, {
    folderId,
    liveBanks: currentState.pagerAccount?.liveTemplateBanks,
    scriptKey,
    country: "ZM",
  });
  const body =
    replyText?.trim() ||
    (scriptKey === "07_game_id" ? loadLocalZmScript("07_game_id") : loadLocalZmScript(scriptKey));
  if (!body?.trim()) {
    return false;
  }
  await tryTakeConversationForProcessing(ctx.client, ctx.convId, "ZM");
  const sent = await ctx.client.sendMessageReliable(ctx.convId, body.trim(), {
    channelId: ctx.runtime.channelId,
    conv: ctx.conv,
  });
  if (!sent) {
    return false;
  }
  if (scriptKey === "07_game_id") {
    const attachment = resolveScriptAttachment("ZM", scriptKey);
    if (attachment) {
      try {
        await ctx.client.sendImageReliable(
          ctx.convId,
          {
            buffer: readFileSync(attachment.path),
            mimeType: attachment.mimeType,
            filename: attachment.filename,
          },
          { channelId: ctx.runtime.channelId, conv: ctx.conv },
        );
      } catch (error) {
        console.warn(`ZM proof image failed ${ctx.convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }
  if (options?.moveToWaitingId) {
    const statusId = findZmWaitingIdStatusId(currentState);
    const operatorId = await ctx.client.probeOperatorUserId();
    const currentStatusId = (ctx.conv.statusId ?? ctx.conv.status?.id ?? "").trim();
    if (statusId && operatorId && currentStatusId !== statusId) {
      try {
        await ctx.client.patchConversationStatus(ctx.convId, statusId, operatorId);
        console.log(`Pager worker: ZM ${ctx.convId.slice(0, 8)} status -> waiting for ID`);
      } catch (error) {
        console.warn(`Pager worker: status patch failed ${ctx.convId.slice(0, 8)}:`, formatError(error));
      }
    }
  }
  console.log(
    `Pager worker: ZM ${ctx.convId.slice(0, 8)} proof -> ${scriptKey} build=${getDeployLabel()}`,
  );
  await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
    conversationId: ctx.convId,
    channelId: ctx.runtime.channelId,
    lastCustomerMessageId: ctx.lastIncoming.id,
    lastCustomerMessageAt: ctx.lastIncoming.createdAt,
    lastReplyAt: new Date().toISOString(),
    lastReplyRole: scriptKey,
    currentStage: scriptKey === "07_game_id" ? "waiting_id" : ctx.convState.currentStage,
    sendFailures: 0,
  });
  return true;
}

async function trySendCmProofFromCombinedText(
  deps: WorkerDeps,
  ctx: SpecialResponseContext & { outgoingTexts: string[] },
  combinedText: string,
): Promise<boolean> {
  if (ctx.channel.country !== "CM" || !cmRegLinkSentInHistory(ctx.outgoingTexts)) {
    return false;
  }
  const scriptKey = resolveCmProofScriptFromCombinedText(
    ctx.playbook,
    combinedText,
    ctx.outgoingTexts,
  );
  if (!scriptKey) {
    return false;
  }
  const sent = await sendCmScriptKey(deps, ctx, scriptKey);
  return sent;
}

async function tryHandleCustomerImage(
  deps: WorkerDeps,
  ctx: SpecialResponseContext & {
    imageUrl: string;
    outgoingTexts: string[];
    funnelStep?: number;
    sortedMessages?: PagerMessage[];
    operatorUserId?: string;
  },
): Promise<boolean> {
  if (!ctx.imageUrl) {
    return false;
  }

  let proofKind: string | undefined;
  let image: Buffer;
  let ocrCombinedText = ctx.text;
  try {
    image = await ctx.client.downloadAttachment(ctx.imageUrl);
    const classification = await classifyProofFromImage(ctx.playbook, image, {
      caption: ctx.text,
      ocrEnabled: deps.env.OCR_ENABLED,
      ocrLang: ocrLangForCountry(ctx.channel.country),
      country: ctx.channel.country,
    });
    proofKind = classification.proofKind;
    ocrCombinedText = classification.combinedText;

    if (ctx.channel.country === "CM") {
      const sent = await trySendCmProofFromCombinedText(
        deps,
        ctx,
        classification.combinedText,
      );
      if (sent) {
        return true;
      }
    }
    if (ctx.channel.country === "ZM") {
      const sent = await trySendZmProofFromCombinedText(
        deps,
        ctx,
        classification.combinedText,
        classification.proofKind,
      );
      if (sent) {
        return true;
      }
    }
  } catch (error) {
    console.warn(`OCR failed ${ctx.convId.slice(0, 8)}:`, formatError(error));
    proofKind = classifyProofFromText(ctx.playbook, ctx.text, ctx.channel.country).proofKind;
    try {
      image = await ctx.client.downloadAttachment(ctx.imageUrl);
    } catch {
      return false;
    }
    if (ctx.channel.country === "CM") {
      const sent = await trySendCmProofFromCombinedText(deps, ctx, ctx.text);
      if (sent) {
        return true;
      }
    }
    if (ctx.channel.country === "ZM") {
      const fallbackKind = classifyProofFromText(ctx.playbook, ctx.text, "ZM").proofKind;
      const sent = await trySendZmProofFromCombinedText(deps, ctx, ctx.text, fallbackKind);
      if (sent) {
        return true;
      }
    }
  }

  const zmDepositScreenshot =
    ctx.channel.country === "ZM" &&
    zmDepositSentInHistory(ctx.outgoingTexts) &&
    (proofKind === "deposit_balance_screenshot" ||
      looksLikeZmDepositBalanceScreenshot(ocrCombinedText));
  if (zmDepositScreenshot) {
    const sent = await trySendZmProofFromCombinedText(
      deps,
      ctx,
      ocrCombinedText,
      proofKind as import("./config.js").ProofKind,
    );
    if (sent) {
      return true;
    }
  }

  const funnelStep = ctx.funnelStep ?? ctx.convState.funnelStep ?? 0;
  const support = buildSupportSnapshot(
    ctx.channel.country,
    isInProgressStatusConversation(ctx.conv),
    ctx.outgoingTexts,
    {
      operatorFolderEnabled: isConversationInAiEnabledFolders(ctx.conv, ctx.state),
    },
  );

  if (ctx.channel.country === "CM" && deps.env.AI_ENABLED && image.length > 0 && cmRegLinkSentInHistory(ctx.outgoingTexts) && isConversationInAiEnabledFolders(ctx.conv, ctx.state)) {
    const extract = await maybeAiVisionExtractCmProof(deps.env, {
      imageBase64: image.toString("base64"),
      mimeType: detectImageMimeType(image),
      caption: ctx.text,
      depositScriptAlreadySent: cmDepositSentInHistory(ctx.outgoingTexts),
    });
    if (extract) {
      const aiCombined = cmVisionExtractToCombinedText(extract, ctx.text);
      const sent = await trySendCmProofFromCombinedText(deps, ctx, aiCombined);
      if (sent) {
        return true;
      }
      if (aiCombined.trim()) {
        proofKind = classifyProofFromText(ctx.playbook, aiCombined, "CM").proofKind;
        ocrCombinedText = aiCombined;
      }
    }
  }

  if (deps.env.AI_ENABLED && image.length > 0 && isConversationInAiEnabledFolders(ctx.conv, ctx.state)) {
    const sorted = ctx.sortedMessages ?? [];
    const botAlreadyAnswered =
      sorted.length > 0 &&
      hasBotReplyAfterCustomerMessage(
        sorted,
        ctx.lastIncoming,
        ctx.conv,
        ctx.operatorUserId,
        ctx.channel.country,
      );
    const echoBlob = [ocrCombinedText, ctx.text].filter(Boolean).join("\n");
    const scriptEchoOnImage = looksLikeOwnScriptEcho(
      echoBlob,
      ctx.channel.country,
      ctx.outgoingTexts,
    );
    if (botAlreadyAnswered) {
      console.log(
        `Pager worker: skip ${ctx.convId.slice(0, 8)} ${ctx.channel.country} AI vision — bot_already_replied`,
      );
    } else if (scriptEchoOnImage) {
      console.log(
        `Pager worker: skip ${ctx.convId.slice(0, 8)} ${ctx.channel.country} AI vision — script_echo_on_screenshot`,
      );
    } else if (zmDepositScreenshot) {
      console.log(
        `Pager worker: skip ${ctx.convId.slice(0, 8)} ZM AI vision — deposit_screenshot_uses_script`,
      );
    } else {
    const visionReply = await runAiAgentVisionTurn(deps.env, {
      country: ctx.channel.country,
      caption: ctx.text,
      funnelStep,
      outgoingTexts: ctx.outgoingTexts,
      proofKind: proofKind ?? "unclear_screenshot",
      imageBase64: image.toString("base64"),
      mimeType: detectImageMimeType(image),
      support,
      ocrCombinedText: ocrCombinedText,
    });
    if (visionReply) {
      const sent = await ctx.client.sendMessageReliable(ctx.convId, visionReply, {
        channelId: ctx.runtime.channelId,
        conv: ctx.conv,
      });
      if (sent) {
        console.log(
          `Pager worker: ${ctx.channel.country} ${ctx.convId.slice(0, 8)} AI agent vision (${visionReply.length} chars) build=${getDeployLabel()}`,
        );
        await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
          conversationId: ctx.convId,
          channelId: ctx.runtime.channelId,
          lastCustomerMessageId: ctx.lastIncoming.id,
          lastCustomerMessageAt: ctx.lastIncoming.createdAt,
          lastReplyAt: new Date().toISOString(),
          lastReplyRole: "ai_agent_vision",
          sendFailures: 0,
        });
        return true;
      }
    }
    }
  }

  if (ctx.channel.country === "CM" && extractCmClientLoginId17(ocrCombinedText)) {
    const sent = await trySendCmProofFromCombinedText(deps, ctx, ocrCombinedText);
    if (sent) {
      return true;
    }
  }

  if (proofKind === "registration_screenshot" || proofKind === "id_screenshot") {
    return false;
  }

  const depositSent =
    ctx.channel.country === "ZM"
      ? zmDepositSentInHistory(ctx.outgoingTexts)
      : ctx.channel.country === "EG"
        ? egDepositSentInHistory(ctx.outgoingTexts)
        : cmDepositSentInHistory(ctx.outgoingTexts);
  const regLinkSent =
    ctx.channel.country === "ZM"
      ? zmRegLinkSentInHistory(ctx.outgoingTexts)
      : ctx.channel.country === "EG"
        ? egRegLinkSentInHistory(ctx.outgoingTexts)
        : cmRegLinkSentInHistory(ctx.outgoingTexts);

  if (proofKind === "unclear_screenshot") {
    if (!regLinkSent || !depositSent) {
      return false;
    }
    const replyText = await resolveTemplateText(deps.config, ctx.client, {
      folderId: ctx.runtime.runtime.templateBankId,
      yamlBankName: ctx.channel.templateBank,
      role: "ask_clear_screenshot",
      country: ctx.channel.country,
    });
    if (!replyText?.trim()) {
      return false;
    }
    const sent = await ctx.client.sendMessageReliable(ctx.convId, replyText.trim(), {
      channelId: ctx.runtime.channelId,
      conv: ctx.conv,
    });
    if (!sent) {
      return false;
    }
    await patchConversationState(deps.stateStore, ctx.state.chatId, ctx.convId, {
      conversationId: ctx.convId,
      channelId: ctx.runtime.channelId,
      currentStage: "waiting_id",
      lastCustomerMessageId: ctx.lastIncoming.id,
      lastCustomerMessageAt: ctx.lastIncoming.createdAt,
      lastReplyAt: new Date().toISOString(),
      lastReplyRole: "ask_clear_screenshot",
      sendFailures: 0,
    });
    return true;
  }

  return false;
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function isRecoverablePagerError(error: unknown): boolean {
  return (
    isPagerSessionError(error) ||
    (error instanceof PagerApiError &&
      error.status === 400 &&
      error.body.toLowerCase().includes("organization id"))
  );
}

async function pollConversations(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
  channelIds: string[],
): Promise<{ conversations: PagerConversation[]; client: PagerClient }> {
  // CM/ZM inboxes regularly exceed 2k chats — dig deep enough that unread is not buried.
  const needsDeepPoll = channelIds.some((channelId) => {
    const country =
      state.channels?.[channelId]?.country ??
      getChannelConfig(deps.config, channelId)?.country ??
      inferCountryFromChannelName(
        state.pagerAccount?.liveChannels?.find((channel) => channel.id === channelId)?.name ?? "",
      );
    return country === "CM" || country === "ZM" || country === "EG";
  });
  const catchUpDeep = isCatchUpReadActive(state.catchUpRead);
  const maxPages = needsDeepPoll ? (catchUpDeep ? 40 : 25) : catchUpDeep ? 20 : 10;
  try {
    await client.syncOrgIdFromChannels();
    const conversations = await client.collectConversationsForChannels(channelIds, maxPages);
    return { conversations, client };
  } catch (error) {
    if (!isRecoverablePagerError(error) || !state.pagerAccount?.password) {
      throw error;
    }
    console.warn(`Pager poll retry with credential refresh for chat ${state.chatId}`);
    const refreshed = await refreshPagerSessionWithCredentials(deps, state);
    if (!refreshed) {
      throw error;
    }
    const conversations = await refreshed.client.collectConversationsForChannels(
      channelIds,
      maxPages,
    );
    return { conversations, client: refreshed.client };
  }
}

async function ensureStatusFolders(
  deps: WorkerDeps,
  state: ChatState,
  client: PagerClient,
): Promise<ChatState | undefined> {
  try {
    const session = await client.bootstrapSession();
    const statuses = await client.loadAllStatuses().catch(() => []);
    const statusFolders = buildStatusFoldersFromPager(
      statuses,
      state.operatorSettings?.statusFolders ?? state.statusFolders,
      state.pagerAccount?.liveChannels,
    );
    return deps.stateStore.patch(state.chatId, {
      statusFolders,
      operatorSettings: {
        enabledChannelIds:
          state.operatorSettings?.enabledChannelIds ?? collectEnabledChannelIdsFromState(state),
        statusFolders,
      },
      pagerAccount: {
        ...(state.pagerAccount ?? { authMode: "cookies", connectedAt: new Date().toISOString() }),
        cookies: session.cookieHeader,
        organizationId: session.organizationId,
        organizationSlug: session.organizationSlug || state.pagerAccount?.organizationSlug,
        organizationName: session.organizationName ?? state.pagerAccount?.organizationName,
      },
    });
  } catch (error) {
    console.error(`ensureStatusFolders failed for chat ${state.chatId}:`, formatError(error));
    return state;
  }
}
