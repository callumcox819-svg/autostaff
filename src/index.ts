import { resolve } from "node:path";
import {
  getChannelConfig,
  getConfigEnabledChannelIds,
  getDefaultEnabledChannel,
  getPlaybook,
  loadConfig,
  statusMapForCountry,
} from "./config.js";
import { ClerkPasswordAuthClient, enrichPagerCookies, parseCookieHeader } from "./clerk-auth.js";
import { decideNextAction } from "./decision-engine.js";
import { loadEnv, shouldFetchStatsFromApi, usesHybridStats } from "./env.js";
import { PagerClient } from "./pager-client.js";
import { runPagerWorker, runPagerWorkerOnceForChat } from "./pager-worker.js";
import { CATCH_UP_READ_ACTIVE_MS, isIncomingDirection } from "./conversation-reply.js";
import { classifyProofFromImage } from "./proof-classifier.js";
import { clearTemplateReplyCache } from "./template-resolver.js";
import { createStateStore, type ChannelRuntimeState, type ChatState, type StateStore } from "./state-store.js";
import { createAppMetaStore, type AppMetaStore } from "./app-meta-store.js";
import {
  buildStatusFoldersFromPager,
  countApiStatusFolders,
  isAiFolderEnabled,
  setAllStatusFolders,
  setAllAiStatusFolders,
  stripChannelNamesFromFolders,
  toggleStatusFolder,
  toggleAiStatusFolder,
  hasEnabledStatusFolders,
} from "./status-folders.js";
import {
  buildPagerAccountPatch,
  ensurePagerSession,
  resolvePagerOrgSlug,
} from "./pager-session.js";
import { applyPagerPause } from "./pager-pause.js";
import {
  TelegramApi,
  buildChannelKeyboard,
  buildCountryKeyboard,
  buildFoldersKeyboard,
  buildAiFoldersKeyboard,
  buildFoldersRetryKeyboard,
  CHANNELS_PAGE_SIZE,
  FOLDERS_PAGE_SIZE,
  buildMainMenuKeyboard,
  buildOperatorReplyKeyboard,
  buildPagerAccountKeyboard,
  buildStatsCountryKeyboard,
  buildStatsIntervalKeyboard,
  buildStatsPlayersKeyboard,
  buildTemplateKeyboard,
  getDeployLabel,
  type TelegramMessage,
  type TelegramUpdate,
} from "./telegram-api.js";
import {
  configureXPartnersSessionStore,
  getXPartnersClient,
  startXPartnersKeepAlive,
  type XPartnersCountry,
  type XPartnersQuickStats,
} from "./xpartners-client.js";
import {
  cacheStale,
  formatStatsMessage,
  formatAllCountriesStats,
  formatPlayersIdsMessageParts,
  parseRefreshHours,
  type StatsRefreshHours,
} from "./xpartners-stats-ui.js";
import {
  describeXPartnersSession,
  ensureXPartnersSession,
  maskXPartnersLogin,
  warmupXPartnersSession,
} from "./xpartners-session.js";
import {
  loadGlobalPartnerStats,
  saveGlobalPartnerStats,
  type GlobalPartnerStatsState,
} from "./xpartners-stats-cache.js";
import {
  describePostbackActivity,
  formatPostbackCabinetSetupText,
  loadPostbackCountryStats,
  postbackCabinetSetups,
  startXPartnersPostbackServer,
  usesPostbackStats,
  usesPostbackStatsForFetch,
} from "./xpartners-postback.js";

import { isFolderMarket, isFolderOnlyCountry, coerceMelbetCountry, type FolderMarketCode } from "./folder-presets.js";
import {
  defaultCountryForChannelName,
  formatRwLearningSummary,
  resolveWorkerCountryForChannel,
  type WorkerCountry,
} from "./rw-learn.js";

/** Melbet Auto Staff — only these countries are processed by the worker. */
const MELBET_COUNTRY_CODES = ["MR", "DJ", "BF", "CM", "BJ", "CR", "SN"] as const satisfies ReadonlyArray<FolderMarketCode>;

const COUNTRY_FOLDER_HINTS: Record<WorkerCountry, string[]> = {
  ZM: ["замб", "zamb", "zambia"],
  EG: ["егип", "egypt", "hapka"],
  CM: ["камер", "cameroon", "cameroun"],
  RW: ["ruand", "rwand", "rw"],
  CL: ["chile", "chili", "чили", "cl"],
  MG: ["мадаг", "madag", "madagascar", "mg", "mdg"],
  DJ: ["джибут", "djibouti", "djib", "djf", "bji"],
  JO: ["йордан", "jordan", "jo", "jod", "jor"],
  MR: ["мавритан", "mauritan"],
  BF: ["буркина", "burkina"],
  BJ: ["бенін", "бенин", "benin", "bénin"],
  CR: ["коста", "costa"],
  SN: ["сенегал", "senegal", "sénégal"],
};

const OPERATOR_COUNTRY_CODES = new Set<WorkerCountry>([...MELBET_COUNTRY_CODES]);

const CHANNEL_COUNTRY_DISPLAY: Record<string, string> = {
  CM: "Камерун",
  DJ: "Джибути",
  MR: "Мавритания",
  BF: "Буркина-Фасо",
  BJ: "Бенин",
  CR: "Коста-Рика",
  SN: "Сенегал",
};

function formatChannelIdSuffix(id: string): string {
  const compact = id.replace(/-/g, "");
  return compact.length > 6 ? compact.slice(-6) : compact;
}

function parseOperatorCountry(value: string): WorkerCountry | undefined {
  const code = value.trim().toUpperCase();
  return OPERATOR_COUNTRY_CODES.has(code as WorkerCountry) ? (code as WorkerCountry) : undefined;
}

function isMelbetCountry(country: string | undefined): country is FolderMarketCode {
  return Boolean(country && isFolderMarket(country));
}

/** Fix stale 1xbet countries (ZM/RW/…) using Melbet template folder name when possible. */
function coerceMelbetRuntime(
  runtime: ChannelRuntimeState,
  channelName?: string,
): ChannelRuntimeState {
  const coerced = coerceMelbetCountry(runtime.country, runtime.templateBank, channelName);
  if (coerced && coerced !== runtime.country) {
    return { ...runtime, country: coerced };
  }
  return runtime;
}

function displayCountryLabel(country: string | undefined): string {
  if (!country) {
    return "??";
  }
  if (!isMelbetCountry(country)) {
    return "?? (выбери страну)";
  }
  return CHANNEL_COUNTRY_DISPLAY[country] ?? country;
}

const env = loadEnv();
const config = loadConfig(resolve(process.cwd(), env.BOT_CONFIG_PATH));
let stateStore: StateStore;
let appMetaStore: AppMetaStore;
const telegram = new TelegramApi(env.TELEGRAM_BOT_TOKEN);

async function main() {
  stateStore = await createStateStore(env);
  appMetaStore = await createAppMetaStore(env);
  configureXPartnersSessionStore(appMetaStore);
  console.log(`Starting ${env.TELEGRAM_BOT_NAME} build=${getDeployLabel()}...`);
  await telegram.setMyCommands([
    { command: "start", description: "Открыть меню" },
    { command: "pause", description: "Пауза авто-ответов" },
    { command: "reset_pause", description: "Снять паузу" },
    { command: "learn", description: "RW: авто-воронка (справка)" },
  ]).catch((error) => {
    console.warn("Telegram setMyCommands failed:", formatError(error));
  });
  await warmupConnectedAccounts();
  warmupXPartnersSession(env);
  startXPartnersKeepAlive(env);
  startXPartnersPostbackServer(env, appMetaStore);

  await Promise.all([
    runTelegramBot(),
    runPagerWorker({ env, config, stateStore, telegram }),
  ]);
}

async function warmupConnectedAccounts(): Promise<void> {
  const states = await stateStore.listAll();
  for (const state of states) {
    if (!state.pagerAccount?.cookies?.trim() && !(state.pagerAccount?.email && state.pagerAccount?.password)) {
      continue;
    }
    try {
      await ensurePagerSession({ env, stateStore }, state);
    } catch (error) {
      console.warn(`Startup session warmup failed for chat ${state.chatId}:`, formatError(error));
    }
  }
}

async function runTelegramBot(): Promise<never> {
  try {
    await telegram.deleteWebhook();
    console.log("Telegram: webhook cleared, using long polling");
  } catch (error) {
    console.warn("Telegram: could not delete webhook:", formatError(error));
  }

  let offset: number | undefined;

  while (true) {
    try {
      const updates = await telegram.getUpdates(offset);
      for (const update of updates) {
        offset = update.update_id + 1;
        await handleUpdate(update);
      }
    } catch (error) {
      const message = formatError(error);
      if (message.includes("409")) {
        console.warn(
          "Telegram 409 conflict — another bot instance may be running. Retrying in 10s...",
        );
        await sleep(10_000);
        continue;
      }
      console.error("Polling error:", error);
      await sleep(env.POLL_INTERVAL_MS);
    }
  }
}

async function handleUpdate(update: TelegramUpdate) {
  try {
    if (update.callback_query?.message?.chat.id) {
      const chatId = update.callback_query.message.chat.id;
      const messageId = update.callback_query.message.message_id;
      await handleCallback(chatId, update.callback_query.id, update.callback_query.data, messageId);
      return;
    }

    if (update.message) {
      await handleMessage(update.message);
    }
  } catch (error) {
    const chatId =
      update.callback_query?.message?.chat.id ?? update.message?.chat.id;
    console.error("Telegram update failed:", formatError(error));
    if (chatId) {
      try {
        if (update.callback_query?.id) {
          await telegram.answerCallbackQuery(update.callback_query.id, "Ошибка меню");
        }
        await telegram.sendMessage(
          chatId,
          `Не удалось открыть меню: ${formatError(error)}\nПопробуй ещё раз или /start.`,
          buildMainMenuKeyboard(),
        );
      } catch {
        // ignore secondary send failure
      }
    }
  }
}

async function handleCallback(
  chatId: number,
  callbackId: string,
  data?: string,
  messageId?: number,
) {
  if (!data) {
    await telegram.answerCallbackQuery(callbackId, "No callback data");
    return;
  }

  const state = await getOrCreateState(chatId);
  const { kind, value, extra } = parseCallbackData(data);

  if (kind === "channels") {
    if (value === "all_on" || value === "all_off") {
      // handled below
    } else {
      if (value === "page" && extra !== undefined) {
        await telegram.answerCallbackQuery(callbackId);
        await showChannelsMenu(chatId, state, messageId, Number(extra) || 0);
        return;
      }
      if (value === "noop") {
        await telegram.answerCallbackQuery(callbackId);
        return;
      }
      if (value === "back" || value === "refresh") {
        const nextState =
          value === "refresh" ? (await refreshPagerData(chatId, state)) ?? state : state;
        await telegram.answerCallbackQuery(callbackId);
        await showChannelsMenu(chatId, nextState, messageId);
        return;
      }
      if (value === "catchup") {
        const activeUntil = new Date(Date.now() + CATCH_UP_READ_ACTIVE_MS).toISOString();
        await stateStore.patch(chatId, {
          catchUpRead: {
            activeUntil,
            requestedAt: new Date().toISOString(),
            windowHours: 24,
            notifiedAt: undefined,
          },
        });
        await telegram.answerCallbackQuery(callbackId, "Догоняю чаты…");
        await telegram.sendMessage(
          chatId,
          "Включён догон: все unread в «Без статусу» (любой возраст) + read/unread за 24 ч (CM/EG/ZM/RW). Несколько циклов ~35 мин…",
        );
        void runPagerWorkerOnceForChat({ env, config, stateStore, telegram }, chatId).catch((error) => {
          console.warn(`Catch-up worker kick failed chat ${chatId}:`, formatError(error));
        });
        return;
      }
      await telegram.answerCallbackQuery(callbackId);
    }
  }

  if (kind === "channel_toggle" && value) {
    const latestState = (await stateStore.get(chatId)) ?? state;
    const channel = getChannelFromCallback(latestState, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Channel not found");
      return;
    }

    const page = Number(extra ?? "0");
    const runtime = getChannelRuntime(latestState, channel.id, channel.country);
    const nextEnabled = !isChannelEnabled(latestState, channel.id, runtime.enabled);
    if (nextEnabled && !isMelbetCountry(runtime.country)) {
      await telegram.answerCallbackQuery(
        callbackId,
        "Сначала выбери страну Melbet (кнопка ??)",
      );
      return;
    }
    const nextState = await setChannelEnabled(chatId, latestState, channel.id, nextEnabled);
    await telegram.answerCallbackQuery(callbackId, nextEnabled ? "🟢 Включено" : "🔴 Выключено");
    if (messageId) {
      await telegram.editMessageReplyMarkup(
        chatId,
        messageId,
        buildChannelKeyboard(
          getSelectableChannels(nextState ?? latestState),
          Number.isFinite(page) ? page : 0,
        ),
      );
    }
    return;
  }

  if (kind === "channel_info" && value) {
    const latestState = (await stateStore.get(chatId)) ?? state;
    const channel = getChannelFromCallback(latestState, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Канал не найден — жми «Обновить каналы»");
      return;
    }

    const row = getSelectableRowForChannel(latestState, channel.id);
    const channelNum = getChannelDisplayNumber(latestState, channel.id);
    await telegram.answerCallbackQuery(callbackId, "Смотрю последний чат…");

    try {
      const sessionResult = await ensurePagerSession({ env, stateStore }, latestState);
      if (!sessionResult) {
        await telegram.sendMessage(chatId, "Pager не подключён — не могу загрузить чаты.");
        return;
      }

      const { client } = sessionResult;
      const convs = await client.listConversations({ channelId: channel.id, pageSize: 20 });
      const sorted = [...convs].sort((a, b) => {
        const ta = Date.parse(a.lastMessageAt ?? "") || 0;
        const tb = Date.parse(b.lastMessageAt ?? "") || 0;
        return tb - ta;
      });
      const latest = sorted[0];
      let preview = "Нет чатов на этом канале.";
      let lastAt = "";
      if (latest) {
        const msgs = await client.listMessages(latest.id, 1, 40);
        const incoming = [...msgs]
          .reverse()
          .filter((message) => isIncomingDirection(message.messageDirection))
          .slice(0, 3)
          .map((message) => (message.text ?? "").trim().slice(0, 120))
          .filter(Boolean);
        const fallback = msgs[msgs.length - 1];
        const fallbackText = (fallback?.text ?? "").trim().slice(0, 160);
        lastAt = latest.lastMessageAt
          ? new Date(latest.lastMessageAt).toLocaleString("ru-RU")
          : "";
        if (incoming.length) {
          preview = incoming.map((text, index) => `${index + 1}) ${text}`).join("\n");
        } else {
          preview = fallbackText || "(без текста — возможно фото или стикер)";
        }
      }

      const suffix = formatChannelIdSuffix(channel.id);
      const source = row?.channelSource ? `\nИсточник: ${row.channelSource}` : "";
      const country = row?.country ?? channel.country;
      const countryLabel = displayCountryLabel(country);
      const melbetOk = isMelbetCountry(country);
      const warning = melbetOk
        ? ""
        : [
            "",
            "⚠️ Бот Melbet НЕ отвечает на этом канале:",
            "страна не Melbet (ZM/RW/… — остаток 1xbet).",
            "Жми кнопку страны и выбери Мавритания/Бенин/Камерун/…",
            "Потом папку шаблонов под эту страну.",
          ].join("\n");

      await telegram.sendMessage(
        chatId,
        [
          `Канал #${channelNum}: ${channel.name}`,
          `ID …${suffix}${source}`,
          `Страна в боте: ${countryLabel}`,
          `Шаблоны: ${row?.templateBank ?? "?"}`,
          "",
          `Последний чат${lastAt ? ` (${lastAt})` : ""}:`,
          preview,
          warning,
          "",
          "Сверь текст с Pager/Facebook — у одинаковых имён разный ID.",
          melbetOk
            ? "Если страна неверна — жми кнопку страны (MR/BJ/CM/…) у этого канала."
            : "",
        ]
          .filter((line) => line !== undefined)
          .join("\n"),
      );
    } catch (error) {
      await telegram.sendMessage(chatId, `Не удалось загрузить чат: ${formatError(error)}`);
    }
    return;
  }

  if (kind === "channels" && value === "all_on") {
    const latestState = (await stateStore.get(chatId)) ?? state;
    const nextState = await setAllChannelsEnabled(chatId, latestState, true);
    await telegram.answerCallbackQuery(callbackId, "Все каналы включены");
    if (messageId) {
      await telegram.editMessageReplyMarkup(
        chatId,
        messageId,
        buildChannelKeyboard(getSelectableChannels(nextState ?? latestState)),
      );
    }
    return;
  }

  if (kind === "channels" && value === "all_off") {
    const latestState = (await stateStore.get(chatId)) ?? state;
    const nextState = await setAllChannelsEnabled(chatId, latestState, false);
    await telegram.answerCallbackQuery(callbackId, "Все каналы выключены");
    if (messageId) {
      await telegram.editMessageReplyMarkup(
        chatId,
        messageId,
        buildChannelKeyboard(getSelectableChannels(nextState ?? latestState)),
      );
    }
    return;
  }

  if (kind === "channel_country" && value) {
    const channel = getChannelFromCallback(state, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Channel not found");
      return;
    }

    await telegram.answerCallbackQuery(callbackId);
    await safeEditMenu(
      chatId,
      messageId,
      `Выбери страну для ${channel.name}:`,
      buildCountryKeyboard(channel.id),
      callbackId,
    );
    return;
  }

  if (kind === "country_pick" && value && extra) {
    const channel = getChannelFromCallback(state, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Channel not found");
      return;
    }

    const country = parseOperatorCountry(extra);
    if (!country) {
      await telegram.answerCallbackQuery(callbackId, "Неизвестная страна");
      return;
    }
    const runtime = getChannelRuntime(state, channel.id, country);
    const bank = pickTemplateBankFromLiveBanks(getLiveTemplateBanks(state), country);
    await stateStore.patch(chatId, {
      channels: {
        ...(state.channels ?? {}),
        [channel.id]: {
          ...runtime,
          country,
          templateBank: bank?.name ?? runtime.templateBank,
          templateBankId: bank?.id ?? runtime.templateBankId,
        },
      },
    });
    const nextState = await stateStore.get(chatId) ?? state;
    await telegram.answerCallbackQuery(
      callbackId,
      CHANNEL_COUNTRY_DISPLAY[country]
        ? `${CHANNEL_COUNTRY_DISPLAY[country]} · сохранённые ответы Melbet`
        : `Страна: ${country}`,
    );
    await showChannelsMenu(chatId, nextState, messageId);
    return;
  }

  if (kind === "channel_bank" && value) {
    const channel = getChannelFromCallback(state, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Channel not found");
      return;
    }

    const banks = getLiveTemplateBanks(state);
    if (!banks.length) {
      await telegram.answerCallbackQuery(callbackId, "Папки не загружены — нажми Обновить");
      return;
    }

    await telegram.answerCallbackQuery(callbackId);
    await safeEditMenu(
      chatId,
      messageId,
      `Выбери папку шаблонов для ${channel.name}:`,
      buildTemplateKeyboard(channel.id, banks),
      callbackId,
    );
    return;
  }

  if (kind === "template_pick" && value && extra) {
    const channel = getChannelFromCallback(state, value);
    if (!channel) {
      await telegram.answerCallbackQuery(callbackId, "Channel not found");
      return;
    }

    const bank = getLiveTemplateBanks(state)[Number(extra)];
    if (!bank) {
      await telegram.answerCallbackQuery(callbackId, "Папка не найдена");
      return;
    }

    const runtime = getChannelRuntime(state, channel.id, channel.country);
    await stateStore.patch(chatId, {
      channels: {
        ...(state.channels ?? {}),
        [channel.id]: {
          ...runtime,
          templateBank: bank.name,
          templateBankId: bank.id,
        },
      },
    });
    const nextState = await stateStore.get(chatId) ?? state;
    await telegram.answerCallbackQuery(callbackId, `Папка: ${bank.name}`);
    await showChannelsMenu(chatId, nextState, messageId);
    return;
  }

  if (kind === "folders") {
    await telegram.answerCallbackQuery(callbackId);

    if (value === "page" && extra) {
      await showFoldersMenu(chatId, state, messageId, Number(extra));
      return;
    }

    if (value === "noop") {
      return;
    }

    if (value === "refresh") {
      const synced = await syncStatusFolders(chatId, state);
      if (synced.error) {
        await telegram.sendMessage(chatId, `⚠️ ${synced.error}`);
      }
      await showFoldersMenu(chatId, synced.state ?? state, messageId);
      return;
    }

    if (value === "all_on" || value === "all_off") {
      const baseFolders = state.operatorSettings?.statusFolders ?? state.statusFolders ?? [];
      const folders = setAllStatusFolders(baseFolders, value === "all_on");
      let nextState =
        (await stateStore.patch(chatId, {
          statusFolders: folders,
          operatorSettings: buildOperatorSettings(state, { statusFolders: folders }),
        })) ?? state;
      await showFoldersMenu(chatId, nextState, messageId);
      return;
    }

    if (value === "ai") {
      await showAiFoldersMenu(chatId, state, messageId);
      return;
    }

    if (value === "back") {
      await showFoldersMenu(chatId, state, messageId);
      return;
    }
    return;
  }

  if (kind === "ai_folders") {
    await telegram.answerCallbackQuery(callbackId);

    if (value === "page" && extra) {
      await showAiFoldersMenu(chatId, state, messageId, Number(extra));
      return;
    }

    if (value === "noop") {
      return;
    }

    if (value === "all_on" || value === "all_off") {
      const baseFolders = state.operatorSettings?.statusFolders ?? state.statusFolders ?? [];
      const folders = setAllAiStatusFolders(baseFolders, value === "all_on");
      const nextState =
        (await stateStore.patch(chatId, {
          statusFolders: folders,
          operatorSettings: buildOperatorSettings(state, { statusFolders: folders }),
        })) ?? state;
      await showAiFoldersMenu(chatId, nextState, messageId);
      return;
    }
    return;
  }

  if (kind === "ai_folder_toggle" && value) {
    const index = Number(value);
    const baseFolders = state.operatorSettings?.statusFolders ?? state.statusFolders ?? [];
    const folders = toggleAiStatusFolder(baseFolders, index);
    const folder = folders[index];
    const nextState =
      (await stateStore.patch(chatId, {
        statusFolders: folders,
        operatorSettings: buildOperatorSettings(state, { statusFolders: folders }),
      })) ?? state;
    const page = Math.floor(index / FOLDERS_PAGE_SIZE);
    await telegram.answerCallbackQuery(
      callbackId,
      folder ? `AI: ${isAiFolderEnabled(folder) ? "вкл" : "выкл"} — ${folder.name}` : "Готово",
    );
    await showAiFoldersMenu(chatId, nextState, messageId, page);
    return;
  }

  if (kind === "folder_toggle" && value) {
    const index = Number(value);
    const baseFolders = state.operatorSettings?.statusFolders ?? state.statusFolders ?? [];
    const folders = toggleStatusFolder(baseFolders, index);
    let nextState =
      (await stateStore.patch(chatId, {
        statusFolders: folders,
        operatorSettings: buildOperatorSettings(state, { statusFolders: folders }),
      })) ?? state;
    const folder = folders[index];
    await telegram.answerCallbackQuery(
      callbackId,
      folder?.enabled ? `✅ ${folder.name}` : `⬜ ${folder?.name ?? "папка"}`,
    );
    const page = Math.floor(index / FOLDERS_PAGE_SIZE);
    await showFoldersMenu(chatId, nextState, messageId, page);
    return;
  }

  if (kind === "menu") {
    await telegram.answerCallbackQuery(callbackId);

    if (value === "main") {
      await sendMainMenu(chatId, state, messageId);
      return;
    }

    if (value === "pager_account") {
      await sendPagerAccountMenu(chatId, state);
      return;
    }

    if (value === "channels") {
      await showChannelsMenu(chatId, state);
      return;
    }

    if (value === "folders") {
      await showFoldersMenu(chatId, state);
      return;
    }

    if (value === "status") {
      await sendStatus(chatId, state);
      return;
    }

    if (value === "stats") {
      await showStatsMenu(chatId, state, messageId);
      return;
    }

    if (value === "learn") {
      const latest = (await stateStore.get(chatId)) ?? state;
      await telegram.sendMessage(chatId, formatRwLearningSummary(latest.rwLearning), buildMainMenuKeyboard());
      return;
    }

    if (value === "reset") {
      await stateStore.delete(chatId);
      const nextState = await getOrCreateState(chatId);
      await telegram.sendMessage(
        chatId,
        `State reset.\nChannel: ${getEffectiveChannel(nextState).name}\nStage: ${nextState.currentStage}`,
        buildMainMenuKeyboard(),
      );
      return;
    }
  }

  if (kind === "stats") {
    const latest = (await stateStore.get(chatId)) ?? state;
    const globalStats = await loadGlobalPartnerStats(appMetaStore);
    if (value === "interval" && extra === "menu") {
      await telegram.answerCallbackQuery(callbackId);
      const hours = globalStats.refreshIntervalHours;
      await safeEditMenu(
        chatId,
        messageId,
        `Как часто обновлять общий кэш 1xPartners?\n\nСейчас: <b>${hours} ч</b>\n\nОдин аккаунт на сервере — все операторы видят одни цифры.`,
        buildStatsIntervalKeyboard(hours),
        callbackId,
      );
      return;
    }
    if (value === "interval" && (extra === "1" || extra === "3" || extra === "5")) {
      const hours = parseRefreshHours(extra);
      await saveGlobalPartnerStats(appMetaStore, {
        ...globalStats,
        refreshIntervalHours: hours,
      });
      await telegram.answerCallbackQuery(callbackId, `Интервал: ${hours} ч`);
      await showStatsMenu(chatId, latest, messageId);
      return;
    }
    if (value === "refresh" && extra === "all") {
      await refreshAllPartnerStats(chatId, latest, messageId, callbackId);
      return;
    }
    if (value === "country" && (extra === "CM" || extra === "EG" || extra === "ZM" || extra === "RW")) {
      await sendCountryStats(chatId, latest, extra, callbackId);
      return;
    }
    if (value === "players" && extra === "menu") {
      await telegram.answerCallbackQuery(callbackId);
      await safeEditMenu(
        chatId,
        messageId,
        "<b>1xPartners · ID игроков за сегодня</b>\n\nКак в отчёте «По игрокам»: период «сегодня» (USD). Выберите страну или «Все 4» — пришлю список ID в чат.",
        buildStatsPlayersKeyboard(),
        callbackId,
      );
      return;
    }
    if (
      value === "players" &&
      (extra === "CM" || extra === "EG" || extra === "ZM" || extra === "RW" || extra === "ALL")
    ) {
      await sendPlayersIdsExport(chatId, extra === "ALL" ? "ALL" : extra, callbackId);
      return;
    }
  }

  if (kind === "pager") {
    await telegram.answerCallbackQuery(callbackId);

    if (value === "login_password") {
      await stateStore.patch(chatId, {
        pendingAction: "await_pager_email",
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        "Введи email от Pager аккаунта следующим сообщением.",
      );
      return;
    }

    if (value === "import_cookies") {
      await stateStore.patch(chatId, {
        pendingAction: "await_pager_cookies",
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        "Отправь cookies одной строкой следующим сообщением.",
      );
      return;
    }

    if (value === "disconnect") {
      await stateStore.patch(chatId, {
        pagerAccount: undefined,
        pendingAction: undefined,
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        "Pager аккаунт очищен из локального состояния бота.",
        buildPagerAccountKeyboard(false),
      );
      return;
    }

    if (value === "back") {
      await sendMainMenu(chatId, state);
      return;
    }
    return;
  }

  await telegram.answerCallbackQuery(callbackId, "Unhandled action");
}

async function handleMessage(message: TelegramMessage) {
  const chatId = message.chat.id;
  const state = await getOrCreateState(chatId);

  if (message.text?.startsWith("/")) {
    await handleCommand(chatId, message.text, state);
    return;
  }

  if (message.text && state.pendingAction) {
    const handled = await handlePendingInput(chatId, state, message.text);
    if (handled) {
      return;
    }
  }

  const menuAction = resolveMenuTextAction(message.text);
  if (menuAction) {
    await dispatchMenuAction(chatId, state, menuAction);
    return;
  }

  const effectiveChannel = getEffectiveChannel(state);
  const playbookCountry =
    effectiveChannel.country === "RW" ||
    effectiveChannel.country === "CL" ||
    effectiveChannel.country === "MG" ||
    effectiveChannel.country === "DJ" ||
    isFolderOnlyCountry(effectiveChannel.country)
      ? "CM"
      : effectiveChannel.country === "JO"
        ? "EG"
      : effectiveChannel.country;
  const playbook = getPlaybook(config, playbookCountry);
  const channelForDecision = {
    ...effectiveChannel,
    country: (effectiveChannel.country === "RW" ||
    effectiveChannel.country === "CL" ||
    effectiveChannel.country === "MG" ||
    effectiveChannel.country === "DJ" ||
    isFolderOnlyCountry(effectiveChannel.country)
      ? "CM"
      : effectiveChannel.country === "JO"
        ? "EG"
      : effectiveChannel.country) as "ZM" | "CM" | "EG",
  };

  if (message.photo?.length) {
    const largestPhoto = [...message.photo].sort(
      (left, right) => (right.file_size ?? 0) - (left.file_size ?? 0),
    )[0];

    const file = await telegram.getFile(largestPhoto.file_id);
    if (!file.file_path) {
      await telegram.sendMessage(chatId, "Could not fetch Telegram image file.");
      return;
    }

    const image = await telegram.downloadFile(file.file_path, env.TELEGRAM_BOT_TOKEN);
    const classification = await classifyProofFromImage(playbook, image, {
      caption: message.caption,
      ocrEnabled: env.OCR_ENABLED,
      ocrLang: env.OCR_LANG,
    });

    const decision = decideNextAction(config, channelForDecision, {
      channelId: effectiveChannel.id,
      currentStage: state.currentStage,
      latestCustomerText: message.caption,
      proofKind: classification.proofKind,
    });

    if (!decision) {
      await telegram.sendMessage(
        chatId,
        [
          `Screenshot classified as: ${classification.proofKind}`,
          `Reason: ${classification.reason}`,
          "No next action matched. Use /status or /stages if you want to adjust the flow manually.",
        ].join("\n"),
        buildMainMenuKeyboard(),
      );
      return;
    }

    await stateStore.patch(chatId, { currentStage: decision.nextStage });
    await telegram.sendMessage(
      chatId,
      [
        `Screenshot classified as: ${classification.proofKind}`,
        `Reason: ${classification.reason}`,
        `Next stage: ${decision.nextStage}`,
        `Decision reason: ${decision.reason}`,
      ].join("\n"),
      buildMainMenuKeyboard(),
    );

    if (decision.templateToSend) {
      await telegram.sendMessage(chatId, decision.templateToSend);
    }
    return;
  }

  const decision = decideNextAction(config, channelForDecision, {
    channelId: effectiveChannel.id,
    currentStage: state.currentStage,
    latestCustomerText: message.text,
  });

  if (!decision) {
    await telegram.sendMessage(
      chatId,
      "No rule matched this message yet. Use /status, /channels, or send a clearer text or screenshot.",
      buildMainMenuKeyboard(),
    );
    return;
  }

  await stateStore.patch(chatId, { currentStage: decision.nextStage });
  await telegram.sendMessage(
    chatId,
    `Rule matched.\nNext stage: ${decision.nextStage}\nReason: ${decision.reason}`,
    buildMainMenuKeyboard(),
  );
  if (decision.templateToSend) {
    await telegram.sendMessage(chatId, decision.templateToSend);
  }
}

async function handleCommand(chatId: number, commandText: string, state: ChatState) {
  const command = normalizeTelegramCommand(commandText);

  if (command === "/start") {
    await sendMainMenu(chatId, state);
    return;
  }

  if (command === "/learn") {
    const latest = (await stateStore.get(chatId)) ?? state;
    await telegram.sendMessage(chatId, formatRwLearningSummary(latest.rwLearning), buildMainMenuKeyboard());
    return;
  }

  if (command === "/pause") {
    await applyPagerPause(stateStore, state, true);
    await telegram.sendMessage(
      chatId,
      [
        "⏸ Авто-ответы на паузе только у тебя.",
        "Другие операторы бота не затрагиваются.",
        "",
        "Снять паузу: /reset_pause",
      ].join("\n"),
      buildMainMenuKeyboard(),
    );
    return;
  }

  if (command === "/reset_pause") {
    await applyPagerPause(stateStore, state, false);
    await telegram.sendMessage(
      chatId,
      [
        "▶️ Пауза снята только у тебя.",
        "Бот продолжит обрабатывать чаты по твоим каналам и папкам.",
      ].join("\n"),
      buildMainMenuKeyboard(),
    );
    return;
  }

  if (command === "/channels") {
    await showChannelsMenu(chatId, state);
    return;
  }

  if (command === "/reset") {
    await stateStore.delete(chatId);
    const nextState = await getOrCreateState(chatId);
    await telegram.sendMessage(
      chatId,
      `State reset.\nChannel: ${getEffectiveChannel(nextState).name}\nStage: ${nextState.currentStage}`,
      buildMainMenuKeyboard(),
    );
    return;
  }

  if (command === "/status") {
    await sendStatus(chatId, state);
    return;
  }

  if (command === "/account") {
    await sendPagerAccountMenu(chatId, state);
    return;
  }

  await telegram.sendMessage(
    chatId,
    "Unknown command. Available: /start, /pause, /reset_pause, /account, /channels, /status, /reset",
    buildMainMenuKeyboard(),
  );
}

function normalizeTelegramCommand(commandText: string): string {
  const token = commandText.trim().split(/\s+/)[0] ?? "";
  const base = token.split("@")[0]?.toLowerCase() ?? "";
  return base.startsWith("/") ? base : `/${base}`;
}

async function getOrCreateState(chatId: number): Promise<ChatState> {
  const existing = await stateStore.get(chatId);
  if (existing) {
    return existing;
  }

  const channel = getDefaultEnabledChannel(config);
  return await stateStore.upsert({
    chatId,
    channelId: channel.id,
    currentStage: "new_lead",
    channels: Object.fromEntries(
      config.channels.map((item) => [
        item.id,
        {
          enabled: false,
          country: item.country,
          templateBank: `${item.country.toLowerCase()}-default`,
        },
      ]),
    ),
    updatedAt: new Date().toISOString(),
  });
}

function getEffectiveChannel(state: ChatState) {
  const channel = resolveChannelForState(state, state.channelId);
  if (!channel) {
    throw new Error(`Unknown channel in state: ${state.channelId}`);
  }

  if (!state.templateBankOverride) {
    return {
      ...channel,
      templateBank:
        state.channels?.[channel.id]?.templateBank ?? channel.templateBank,
    };
  }

  return {
    ...channel,
    templateBank: state.templateBankOverride,
  };
}

function parseCallbackData(data: string): { kind: string; value: string; extra?: string } {
  if (data.includes("|")) {
    const [kind, value, extra] = data.split("|");
    return { kind: kind ?? "", value: value ?? "", extra };
  }
  const [kind, value, extra] = data.split(":");
  return { kind: kind ?? "", value: value ?? "", extra };
}

function getSelectableRowForChannel(
  state: ChatState,
  channelId: string,
): ReturnType<typeof getSelectableChannels>[number] | undefined {
  return getSelectableChannels(state).find((row) => row.id === channelId);
}

function getChannelDisplayNumber(state: ChatState, channelId: string): number {
  const index = getSelectableChannels(state).findIndex((row) => row.id === channelId);
  return index >= 0 ? index + 1 : 0;
}

function getChannelById(state: ChatState, channelId: string) {
  const row = getSelectableRowForChannel(state, channelId);
  if (!row) {
    return undefined;
  }
  return resolveChannelForState(state, row.id);
}

/** Legacy keyboards used list index; new ones use channel id. */
function getChannelFromCallback(state: ChatState, value: string) {
  if (/^\d+$/.test(value)) {
    return getChannelByIndex(state, value);
  }
  return getChannelById(state, value);
}

function getChannelByIndex(state: ChatState, indexRaw: string) {
  const index = Number(indexRaw);
  if (!Number.isInteger(index) || index < 0) {
    return undefined;
  }

  const row = getSelectableChannels(state)[index];
  if (!row) {
    return undefined;
  }

  return resolveChannelForState(state, row.id);
}

async function safeEditMenu(
  chatId: number,
  messageId: number | undefined,
  text: string,
  keyboard: ReturnType<typeof buildMainMenuKeyboard>,
  callbackId?: string,
) {
  if (!messageId) {
    await telegram.sendMessage(chatId, text, keyboard);
    return;
  }

  try {
    await telegram.editMessageText(chatId, messageId, text, keyboard);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes("message is not modified")) {
      return;
    }
    console.error("Failed to edit Telegram menu:", error);
    if (callbackId) {
      await telegram.answerCallbackQuery(callbackId, "Открываю меню заново");
    }
    await telegram.sendMessage(chatId, text, keyboard);
  }
}

function getSelectableChannels(state: ChatState) {
  const liveChannels = state.pagerAccount?.liveChannels ?? [];
  if (liveChannels.length > 0) {
    return liveChannels.map((channel) => {
      const fallbackCountry = inferCountryFromName(channel.name);
      const runtime = getChannelRuntime(state, channel.id, fallbackCountry, channel.name);
      return {
        id: channel.id,
        name: channel.name,
        channelSource: channel.channelSource ?? undefined,
        country: runtime.country,
        enabled: isChannelEnabled(state, channel.id, runtime.enabled),
        templateBank: runtime.templateBank ?? "Шаблоны",
      };
    });
  }

  return config.channels.map((channel) => {
    const runtime = getChannelRuntime(state, channel.id, channel.country, channel.name);
    return {
      id: channel.id,
      name: channel.name,
      channelSource: undefined,
      country: runtime.country,
      enabled: isChannelEnabled(state, channel.id, runtime.enabled),
      templateBank: runtime.templateBank ?? `${channel.country.toLowerCase()}-default`,
    };
  });
}

function isChannelEnabled(
  state: ChatState,
  channelId: string,
  runtimeEnabled = false,
): boolean {
  if (state.operatorSettings?.enabledChannelIds?.includes(channelId)) {
    return true;
  }
  if (state.enabledChannelIds?.includes(channelId)) {
    return true;
  }
  return runtimeEnabled;
}

function collectEnabledChannelIds(state: ChatState): string[] {
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

async function setChannelEnabled(
  chatId: number,
  state: ChatState,
  channelId: string,
  enabled: boolean,
): Promise<ChatState | undefined> {
  const liveChannel = state.pagerAccount?.liveChannels?.find((channel) => channel.id === channelId);
  const fallbackCountry = liveChannel
    ? inferCountryFromName(liveChannel.name)
    : (getChannelConfig(config, channelId)?.country ?? "ZM");
  const runtime = getChannelRuntime(state, channelId, fallbackCountry);
  const enabledIds = new Set(collectEnabledChannelIds(state));
  if (enabled) {
    enabledIds.add(channelId);
  } else {
    enabledIds.delete(channelId);
  }

  return stateStore.patch(chatId, {
    enabledChannelIds: [...enabledIds],
    channels: {
      [channelId]: {
        ...runtime,
        enabled,
      },
    },
    operatorSettings: buildOperatorSettings(state, { enabledChannelIds: [...enabledIds] }),
  });
}

async function setAllChannelsEnabled(
  chatId: number,
  state: ChatState,
  enabled: boolean,
): Promise<ChatState | undefined> {
  const selectable = getSelectableChannels(state);
  const enabledIds = enabled
    ? selectable.filter((channel) => isMelbetCountry(channel.country)).map((channel) => channel.id)
    : [];
  const channels: Record<string, ChannelRuntimeState> = { ...(state.channels ?? {}) };

  for (const channel of selectable) {
    const runtime = getChannelRuntime(state, channel.id, channel.country, channel.name);
    const canEnable = enabled && isMelbetCountry(runtime.country);
    channels[channel.id] = {
      ...runtime,
      enabled: canEnable,
    };
  }

  return stateStore.patch(chatId, {
    enabledChannelIds: enabledIds,
    channels,
    operatorSettings: buildOperatorSettings(state, { enabledChannelIds: enabledIds }),
  });
}

function buildOperatorSettings(
  state: ChatState,
  overrides: Partial<NonNullable<ChatState["operatorSettings"]>>,
): NonNullable<ChatState["operatorSettings"]> {
  return {
    enabledChannelIds:
      overrides.enabledChannelIds ??
      state.operatorSettings?.enabledChannelIds ??
      collectEnabledChannelIds(state),
    statusFolders:
      overrides.statusFolders ??
      state.operatorSettings?.statusFolders ??
      state.statusFolders,
  };
}

function mergeChannelsOnLogin(
  state: ChatState,
  channels: Array<{ id: string; name: string }>,
  templateBanks: Array<{ id: string; name: string }>,
): { channels: Record<string, ChannelRuntimeState>; enabledChannelIds: string[] } {
  const defaults = buildChannelRuntimeMap(channels, templateBanks);
  const enabledIds = new Set(
    state.operatorSettings?.enabledChannelIds?.length
      ? state.operatorSettings.enabledChannelIds
      : collectEnabledChannelIds(state),
  );

  const merged: Record<string, ChannelRuntimeState> = { ...defaults };
  for (const [channelId, runtime] of Object.entries(state.channels ?? {})) {
    if (merged[channelId]) {
      const channelName = channels.find((channel) => channel.id === channelId)?.name;
      merged[channelId] = coerceMelbetRuntime(
        { ...merged[channelId], ...runtime },
        channelName,
      );
    }
  }

  for (const channelId of Object.keys(merged)) {
    const channelName = channels.find((channel) => channel.id === channelId)?.name;
    merged[channelId] = coerceMelbetRuntime(merged[channelId], channelName);
  }

  const liveIds = new Set(channels.map((channel) => channel.id));
  const yamlEnabled = getConfigEnabledChannelIds(config).filter((channelId) => liveIds.has(channelId));

  if (!enabledIds.size) {
    for (const channelId of yamlEnabled) {
      enabledIds.add(channelId);
      merged[channelId] = { ...merged[channelId], enabled: true };
    }
  } else {
    for (const channelId of enabledIds) {
      if (merged[channelId]) {
        merged[channelId] = { ...merged[channelId], enabled: true };
      }
    }
  }

  return { channels: merged, enabledChannelIds: [...enabledIds] };
}

function getLiveTemplateBanks(state: ChatState) {
  return state.pagerAccount?.liveTemplateBanks ?? [];
}

function getChannelRuntime(
  state: ChatState,
  channelId: string,
  fallbackCountry: WorkerCountry,
  channelName?: string,
) {
  const existing = state.channels?.[channelId];
  if (existing) {
    return coerceMelbetRuntime(existing, channelName);
  }

  const bank = pickTemplateBankFromLiveBanks(getLiveTemplateBanks(state), fallbackCountry);
  return coerceMelbetRuntime(
    {
      enabled: false,
      country: fallbackCountry,
      templateBank: bank?.name,
      templateBankId: bank?.id,
    },
    channelName,
  );
}

function pickTemplateBankFromLiveBanks(
  banks: Array<{ id: string; name: string }>,
  country: WorkerCountry,
) {
  if (!banks.length) {
    return undefined;
  }

  const hints = COUNTRY_FOLDER_HINTS[country];
  const matched = banks.find((bank) => {
    const normalized = bank.name.toLowerCase();
    return hints.some((hint) => normalized.includes(hint));
  });
  if (matched) {
    return matched;
  }
  // Melbet: never fall back to a random first folder (that caused Rwanda→Benin).
  if (isFolderMarket(country) || isFolderOnlyCountry(country)) {
    return undefined;
  }
  return undefined;
}

function buildChannelRuntimeMap(
  channels: Array<{ id: string; name: string }>,
  templateBanks: Array<{ id: string; name: string }>,
) {
  return Object.fromEntries(
    channels.map((channel) => {
      const country = defaultCountryForChannelName(channel.name);
      const bank = pickTemplateBankFromLiveBanks(templateBanks, country);
      return [
        channel.id,
        {
          enabled: false,
          country,
          templateBank: bank?.name,
          templateBankId: bank?.id,
        },
      ];
    }),
  );
}

async function showChannelsMenu(chatId: number, state: ChatState, messageId?: number, page = 0) {
  const channels = getSelectableChannels(state);
  const text = buildChannelsMenuCaption(state, page);
  const keyboard = buildChannelKeyboard(channels, page);

  try {
    if (!messageId) {
      await telegram.sendMessage(chatId, text, keyboard);
      return;
    }
    await safeEditMenu(chatId, messageId, text, keyboard);
  } catch (error) {
    console.error("showChannelsMenu failed:", formatError(error));
    await telegram.sendMessage(
      chatId,
      [
        "Не удалось показать список каналов.",
        formatError(error),
        channels.length
          ? `Каналов: ${channels.length}. Нажми «Каналы» ещё раз.`
          : "Сначала подключи Pager аккаунт.",
      ].join("\n"),
      buildMainMenuKeyboard(),
    );
  }
}

async function showFoldersMenu(
  chatId: number,
  state: ChatState,
  messageId?: number,
  page = 0,
) {
  let currentState = state;
  if (!currentState.pagerAccount?.cookies && !currentState.pagerAccount?.password) {
    await telegram.sendMessage(
      chatId,
      "Сначала подключи Pager аккаунт через «Pager аккаунт».",
      buildMainMenuKeyboard(),
    );
    return;
  }

  const savedFolders =
    currentState.operatorSettings?.statusFolders ?? currentState.statusFolders ?? [];

  if (countApiStatusFolders(savedFolders) === 0) {
    const synced = await syncStatusFolders(chatId, currentState);
    currentState = synced.state ?? currentState;
    if (countApiStatusFolders(currentState.statusFolders) === 0) {
      await telegram.sendMessage(
        chatId,
        [
          "Не удалось загрузить папки из Pager.",
          synced.error ? `Причина: ${synced.error}` : "Сессия обновляется автоматически, попробуй через минуту.",
        ].join("\n"),
        buildFoldersRetryKeyboard(),
      );
      return;
    }
  } else {
    currentState = {
      ...currentState,
      statusFolders: savedFolders,
    };
  }

  const folders = stripChannelNamesFromFolders(
    currentState.statusFolders ?? [],
    currentState.pagerAccount?.liveChannels,
  );
  if (folders.length !== (currentState.statusFolders ?? []).length) {
    currentState =
      (await stateStore.patch(chatId, {
        statusFolders: folders,
        operatorSettings: buildOperatorSettings(currentState, { statusFolders: folders }),
      })) ?? currentState;
  }
  const enabled = folders.filter((folder) => folder.enabled).length;
  const apiFolderCount = folders.filter(
    (folder) => folder.id !== "" && folder.id !== "*",
  ).length;
  const text = [
    "Папки Pager — откуда бот берёт чаты:",
    "Только твои галочки: чужие «в процесі» и другие папки бот не трогает.",
    "✅ включена | ⬜ выключена",
    "",
    `Включено папок: ${enabled} из ${folders.length}`,
    apiFolderCount
      ? `Загружено из Pager: ${apiFolderCount} папок`
      : "⚠️ Список из Pager пуст — нажми «Обновить папки».",
    "«Без статусу» — только новые чаты без статуса.",
    "«Всі» — все чаты, кроме «в процесі» (её нужно включить отдельно).",
    "Каналы включаются отдельно в меню «Каналы».",
    "AI — отдельно в кнопке «Папки AI».",
  ].join("\n");
  const keyboard = buildFoldersKeyboard(folders, page);

  if (!messageId) {
    await telegram.sendMessage(chatId, text, keyboard);
    return;
  }

  await safeEditMenu(chatId, messageId, text, keyboard);
}

async function showAiFoldersMenu(
  chatId: number,
  state: ChatState,
  messageId?: number,
  page = 0,
) {
  const folders = stripChannelNamesFromFolders(
    state.operatorSettings?.statusFolders ?? state.statusFolders ?? [],
    state.pagerAccount?.liveChannels,
  );
  if (!folders.length) {
    await telegram.sendMessage(chatId, "Сначала загрузи папки в меню «Папки».", buildFoldersRetryKeyboard());
    return;
  }

  const aiOn = folders.filter((folder) => isAiFolderEnabled(folder)).length;
  const text = [
    "Папки AI — где бот может отвечать через AI:",
    "🤖 включено | ⬜ выключено",
    "",
    `AI включён в ${aiOn} из ${folders.length} папок`,
    "Скрипты работают по настройкам в меню «Папки».",
    "Если папку не трогали — AI повторяет настройку бота для неё.",
    "Пример: скрипты в «Без статусу», AI только в «В процесі реєстрації».",
  ].join("\n");
  const keyboard = buildAiFoldersKeyboard(folders, page);

  if (!messageId) {
    await telegram.sendMessage(chatId, text, keyboard);
    return;
  }

  await safeEditMenu(chatId, messageId, text, keyboard);
}

async function syncStatusFolders(
  chatId: number,
  state: ChatState,
): Promise<{ state?: ChatState; error?: string }> {
  const previousFolders = state.operatorSettings?.statusFolders ?? state.statusFolders;
  const previousApiFolderCount = countApiStatusFolders(previousFolders);

  try {
    const sessionResult = await ensurePagerSession({ env, stateStore }, state);
    if (!sessionResult) {
      return { state, error: "Pager сессия недоступна" };
    }

    const { client, state: sessionState } = sessionResult;
    const statuses = await client.loadAllStatuses();
    const statusFolders = buildStatusFoldersFromPager(
      statuses,
      previousFolders,
      sessionState.pagerAccount?.liveChannels,
    );
    const apiCount = countApiStatusFolders(statusFolders);
    const patch: Partial<Omit<ChatState, "chatId">> = {
      pagerAccount: buildPagerAccountPatch(sessionState, {
        organizationId: sessionState.pagerAccount?.organizationId,
        organizationSlug: sessionState.pagerAccount?.organizationSlug,
        organizationName: sessionState.pagerAccount?.organizationName,
        cookieHeader: client.getCookieHeader(),
      }),
      operatorSettings: buildOperatorSettings(sessionState, { statusFolders }),
    };
    if (apiCount > 0 || !previousApiFolderCount) {
      patch.statusFolders = statusFolders;
    }

    const patched = await stateStore.patch(chatId, patch);
    if (apiCount <= 0 && previousApiFolderCount > 0) {
      return {
        state: patched ?? state,
        error:
          "Pager не отдал список папок — оставил прежний список. Сессия обновлена, перелогин не нужен.",
      };
    }
    if (apiCount <= 0) {
      return {
        state: patched,
        error: "Pager не отдал список папок. Попробуй ещё раз через минуту.",
      };
    }
    return { state: patched };
  } catch (error) {
    console.error("syncStatusFolders failed:", error);
    return {
      state,
      error: `Не удалось обновить папки: ${formatError(error)}. Прежний список сохранён.`,
    };
  }
}

async function refreshPagerData(chatId: number, state: ChatState): Promise<ChatState | undefined> {
  const cookies = state.pagerAccount?.cookies;
  if (!cookies) {
    return state;
  }

  try {
    clearTemplateReplyCache();
    const session = await buildPagerClient(
      cookies,
      state.pagerAccount?.organizationId,
      resolvePagerOrgSlug(state),
    ).validateSession();
    const defaults = buildChannelRuntimeMap(
      session.channels.map((channel) => ({ id: channel.id, name: channel.name })),
      session.templateBanks.map((bank) => ({ id: bank.id, name: bank.name })),
    );
    const mergedChannels: Record<string, ChannelRuntimeState> = {};
    const allIds = new Set([...Object.keys(defaults), ...Object.keys(state.channels ?? {})]);
    for (const channelId of allIds) {
      const channelName =
        session.channels.find((channel) => channel.id === channelId)?.name ?? "";
      const runtime = coerceMelbetRuntime(
        {
          ...(defaults[channelId] ?? {
            enabled: false,
            country: defaultCountryForChannelName(channelName),
          }),
          ...(state.channels?.[channelId] ?? {}),
        },
        channelName,
      );
      // If country was coerced from template bank, also align bank when missing match.
      if (isMelbetCountry(runtime.country) && !runtime.templateBank) {
        const bank = pickTemplateBankFromLiveBanks(
          session.templateBanks.map((item) => ({ id: item.id, name: item.name })),
          runtime.country,
        );
        mergedChannels[channelId] = {
          ...runtime,
          templateBank: bank?.name ?? runtime.templateBank,
          templateBankId: bank?.id ?? runtime.templateBankId,
        };
      } else {
        mergedChannels[channelId] = runtime;
      }
    }
    const enabledChannelIds = collectEnabledChannelIds({
      ...state,
      channels: mergedChannels,
    });
    const client = buildPagerClient(
      cookies,
      state.pagerAccount?.organizationId,
      resolvePagerOrgSlug(state),
    );
    const statuses = await client.loadAllStatuses().catch(() => []);
    const liveChannels = session.channels.map((channel) => ({
      id: channel.id,
      name: channel.name,
      channelSource: channel.channelSource,
    }));
    const statusFolders = buildStatusFoldersFromPager(statuses, state.statusFolders, liveChannels);

    return await stateStore.patch(chatId, {
      pagerAccount: {
        ...(state.pagerAccount ?? { authMode: "cookies", connectedAt: new Date().toISOString() }),
        organizationId: session.organizationId,
        organizationName: session.organizationName,
        organizationSlug: session.organizationSlug,
        liveChannels,
        liveTemplateBanks: session.templateBanks.map((bank) => ({
          id: bank.id,
          name: bank.name,
          replyCount: bank.replyCount,
        })),
      },
      channels: mergedChannels,
      enabledChannelIds,
      statusFolders,
    });
  } catch (error) {
    console.error("refreshPagerData failed:", error);
    return state;
  }
}

function resolveChannelForState(state: ChatState, channelId: string) {
  const mapped = getChannelConfig(config, channelId);
  if (mapped) {
    return { ...mapped, isLive: false };
  }

  const live = state.pagerAccount?.liveChannels?.find((channel) => channel.id === channelId);
  if (!live) {
    return undefined;
  }

  const country = inferCountryFromName(live.name);
  const resolvedCountry = resolveWorkerCountryForChannel(
    live.name,
    state.channels?.[live.id]?.country,
    country,
  );
  return {
    id: live.id,
    name: live.name,
    enabled: getChannelEnabled(state, live.id),
    country: resolvedCountry,
    templateBank:
      state.channels?.[live.id]?.templateBank ??
      pickTemplateBankFromLiveBanks(getLiveTemplateBanks(state), country)?.name ??
      "Шаблоны",
    statusMap: statusMapForCountry(config, resolvedCountry),
    isLive: true,
  };
}

function getChannelEnabled(state: ChatState, channelId: string): boolean {
  const runtime = state.channels?.[channelId];
  return isChannelEnabled(state, channelId, runtime?.enabled ?? false);
}

function getChannelCountry(
  state: ChatState,
  channelId: string,
  fallback: WorkerCountry,
): WorkerCountry {
  return state.channels?.[channelId]?.country ?? fallback;
}

function inferCountryFromName(name: string): WorkerCountry {
  return defaultCountryForChannelName(name);
}

function buildPagerClient(cookieHeader: string, orgId?: string, orgSlug?: string, pagerUserId?: string) {
  const enriched = enrichPagerCookies(cookieHeader, { organizationId: orgId, pagerUserId });
  const cookies = parseCookieHeader(enriched);
  return new PagerClient({
    baseUrl: env.PAGER_BASE_URL,
    webBaseUrl: env.PAGER_WEB_URL,
    cookieHeader: enriched,
    orgId: orgId || cookies._pager_org_id,
    orgSlug: orgSlug || cookies._pager_org_slug,
    locale: "uk",
    sessionUserId: pagerUserId || cookies._pager_user_id,
  });
}

function buildClerkAuthClient() {
  return new ClerkPasswordAuthClient({
    frontendApi: "clerk.pager.co.ua",
  });
}

function sleep(ms: number) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function handlePendingInput(
  chatId: number,
  state: ChatState,
  text: string,
): Promise<boolean> {
  if (state.pendingAction === "await_pager_email") {
    await stateStore.patch(chatId, {
      draftPagerEmail: text.trim(),
      pendingAction: "await_pager_password",
    });
    await telegram.sendMessage(chatId, "Теперь отправь пароль от Pager аккаунта.");
    return true;
  }

  if (state.pendingAction === "await_pager_password") {
    try {
      const email = state.draftPagerEmail?.trim();
      if (!email) {
        throw new Error("Pager email is missing. Start the login flow again.");
      }

      const login = await buildClerkAuthClient().signInWithPassword(email, text.trim());
      const session = await buildPagerClient(
        login.cookieHeader,
        login.organizationId,
      ).validateSession();
      const statusClient = buildPagerClient(
        login.cookieHeader,
        session.organizationId ?? login.organizationId,
        session.organizationSlug,
      );
      const statuses = await statusClient.loadAllStatuses().catch(() => []);
      const liveChannels = session.channels.map((channel) => ({
        id: channel.id,
        name: channel.name,
        channelSource: channel.channelSource,
      }));
      const statusFolders = buildStatusFoldersFromPager(
        statuses,
        state.operatorSettings?.statusFolders ?? state.statusFolders,
        liveChannels,
      );
      const merged = mergeChannelsOnLogin(
        state,
        session.channels.map((channel) => ({ id: channel.id, name: channel.name })),
        session.templateBanks.map((bank) => ({ id: bank.id, name: bank.name })),
      );
      const enrichedCookies = enrichPagerCookies(login.cookieHeader, {
        organizationId: session.organizationId ?? login.organizationId,
        pagerUserId: login.pagerUserId,
      });
      const probedUserId =
        (await buildPagerClient(
          enrichedCookies,
          session.organizationId ?? login.organizationId,
          session.organizationSlug,
          login.pagerUserId,
        ).probeOperatorUserId()) || login.pagerUserId;

      await stateStore.patch(chatId, {
        pendingAction: undefined,
        pagerAccount: {
          authMode: "credentials",
          email,
          password: text.trim(),
          cookies: enrichPagerCookies(enrichedCookies, { pagerUserId: probedUserId }),
          pagerUserId: probedUserId,
          organizationId: session.organizationId ?? login.organizationId,
          organizationName: session.organizationName,
          organizationSlug: session.organizationSlug,
          liveChannels: session.channels.map((channel) => ({
            id: channel.id,
            name: channel.name,
            channelSource: channel.channelSource,
          })),
          liveTemplateBanks: session.templateBanks.map((bank) => ({
            id: bank.id,
            name: bank.name,
            replyCount: bank.replyCount,
          })),
          connectedAt: state.pagerAccount?.connectedAt ?? new Date().toISOString(),
        },
        channels: merged.channels,
        enabledChannelIds: merged.enabledChannelIds,
        statusFolders,
        operatorSettings: buildOperatorSettings(state, {
          enabledChannelIds: merged.enabledChannelIds,
          statusFolders,
        }),
        draftPagerEmail: undefined,
      });

      await telegram.sendMessage(
        chatId,
        [
          "Pager аккаунт подключён через email + пароль.",
          `Email: ${maskEmail(email)}`,
          `Организация: ${session.organizationName ?? session.organizationId ?? "unknown"}`,
          `Каналов найдено: ${session.channelCount}`,
          `Банков шаблонов: ${session.templateBanks.length}`,
          `Папки чатов: ${statusFolders.length} (по умолчанию включено «Всі»)`,
        ].join("\n"),
        buildPagerAccountKeyboard(true),
      );
    } catch (error) {
      await stateStore.patch(chatId, {
        pendingAction: undefined,
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        `Не удалось войти по email + пароль: ${formatError(error)}`,
        buildPagerAccountKeyboard(false),
      );
    }
    return true;
  }

  if (state.pendingAction === "await_pager_cookies") {
    try {
      const session = await buildPagerClient(text.trim()).validateSession();
      const statusClient = buildPagerClient(
        text.trim(),
        session.organizationId,
        session.organizationSlug,
      );
      const statuses = await statusClient.loadAllStatuses().catch(() => []);
      const liveChannels = session.channels.map((channel) => ({
        id: channel.id,
        name: channel.name,
        channelSource: channel.channelSource,
      }));
      const statusFolders = buildStatusFoldersFromPager(
        statuses,
        state.operatorSettings?.statusFolders ?? state.statusFolders,
        liveChannels,
      );
      const merged = mergeChannelsOnLogin(
        state,
        session.channels.map((channel) => ({ id: channel.id, name: channel.name })),
        session.templateBanks.map((bank) => ({ id: bank.id, name: bank.name })),
      );
      const enrichedCookies = enrichPagerCookies(text.trim(), {
        organizationId: session.organizationId,
      });
      await stateStore.patch(chatId, {
        pendingAction: undefined,
        pagerAccount: {
          authMode: "cookies",
          cookies: enrichedCookies,
          organizationId: session.organizationId,
          organizationName: session.organizationName,
          organizationSlug: session.organizationSlug,
          liveChannels: session.channels.map((channel) => ({
            id: channel.id,
            name: channel.name,
            channelSource: channel.channelSource,
          })),
          liveTemplateBanks: session.templateBanks.map((bank) => ({
            id: bank.id,
            name: bank.name,
            replyCount: bank.replyCount,
          })),
          connectedAt: state.pagerAccount?.connectedAt ?? new Date().toISOString(),
        },
        channels: merged.channels,
        enabledChannelIds: merged.enabledChannelIds,
        statusFolders,
        operatorSettings: buildOperatorSettings(state, {
          enabledChannelIds: merged.enabledChannelIds,
          statusFolders,
        }),
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        [
          "Cookies сохранены и проверены.",
          `Организация: ${session.organizationName ?? session.organizationId ?? "unknown"}`,
          `Каналов найдено: ${session.channelCount}`,
          `Банков шаблонов: ${session.templateBanks.length}`,
          `Папки чатов: ${statusFolders.length} (по умолчанию включено «Всі»)`,
          "Теперь кнопка `Каналы` будет показывать живые каналы аккаунта.",
        ].join("\n"),
        buildPagerAccountKeyboard(true),
      );
    } catch (error) {
      await stateStore.patch(chatId, {
        pendingAction: undefined,
        draftPagerEmail: undefined,
      });
      await telegram.sendMessage(
        chatId,
        `Не удалось авторизовать cookies: ${formatError(error)}`,
        buildPagerAccountKeyboard(false),
      );
    }
    return true;
  }

  return false;
}

async function sendMainMenu(chatId: number, state: ChatState, messageId?: number) {
  const text = buildMainMenuCaption(state);
  const keyboard = buildMainMenuKeyboard();
  if (!messageId) {
    await telegram.sendMessage(chatId, text, keyboard);
    await telegram
      .sendMessage(chatId, "Меню", buildOperatorReplyKeyboard())
      .catch(() => {});
    return;
  }
  await safeEditMenu(chatId, messageId, text, keyboard);
}

function buildMainMenuCaption(state: ChatState): string {
  const account = state.pagerAccount;
  const hasPager = Boolean(account?.cookies?.trim() || (account?.email && account?.password));
  if (!hasPager) {
    return `Pager не подключён — открой «Pager аккаунт».\nbuild ${getDeployLabel()}`;
  }

  const org = account?.organizationName || account?.organizationSlug || "Pager";
  const enabledChannels = getSelectableChannels(state).filter((channel) =>
    isChannelEnabled(state, channel.id, getChannelRuntime(state, channel.id, channel.country).enabled),
  );
  const liveCount = account?.liveChannels?.length ?? enabledChannels.length;
  if (!enabledChannels.length) {
    return `Pager: ${org}\nКаналы не включены (${liveCount} доступно).\nbuild ${getDeployLabel()}`;
  }

  const summary = enabledChannels
    .slice(0, 4)
    .map((channel) => `${channel.name} · ${channel.country}`)
    .join("\n");
  const extra =
    enabledChannels.length > 4 ? `\n… ещё ${enabledChannels.length - 4}` : "";
  return `Pager: ${org}\nВключено ${enabledChannels.length}/${liveCount}:\n${summary}${extra}\nbuild ${getDeployLabel()}`;
}

function buildChannelsMenuCaption(state: ChatState, page = 0): string {
  const channels = getSelectableChannels(state);
  const enabled = channels.filter((channel) =>
    isChannelEnabled(state, channel.id, getChannelRuntime(state, channel.id, channel.country).enabled),
  ).length;

  const nameCounts = new Map<string, number>();
  for (const channel of channels) {
    nameCounts.set(channel.name, (nameCounts.get(channel.name) ?? 0) + 1);
  }
  const hasDuplicateNames = [...nameCounts.values()].some((count) => count > 1);
  const totalPages = Math.max(1, Math.ceil(channels.length / CHANNELS_PAGE_SIZE));
  const safePage = Math.min(Math.max(page, 0), totalPages - 1);
  const pageLabel = totalPages > 1 ? ` · стр. ${safePage + 1}/${totalPages}` : "";

  const base = `Каналы ${enabled}/${channels.length}${pageLabel} · build ${getDeployLabel()}`;
  const needsCountry = channels.filter((channel) => !isMelbetCountry(channel.country)).length;
  const hints: string[] = [];
  if (hasDuplicateNames) {
    hints.push("Одинаковые имена — жми ℹ️ (смотри ID и текст чата).");
  }
  if (needsCountry > 0) {
    hints.push(`⚠️ ${needsCountry} канал(ов) без страны Melbet (кнопка ??) — бот их не обрабатывает.`);
  }
  return hints.length ? `${base}\n${hints.join("\n")}` : base;
}

async function sendPagerAccountMenu(chatId: number, state: ChatState) {
  const account = state.pagerAccount;
  const lines = account
    ? [
        "Pager аккаунт подключён",
        `Режим: ${account.authMode === "credentials" ? "email + пароль" : "cookies"}`,
        account.email ? `Email: ${maskEmail(account.email)}` : undefined,
        account.organizationName
          ? `Org: ${account.organizationName}`
          : account.organizationId
            ? `Org ID: ${account.organizationId}`
            : undefined,
        account.liveChannels?.length
          ? `Каналы: ${account.liveChannels.length}`
          : undefined,
        account.liveTemplateBanks?.length
          ? `Банки шаблонов: ${account.liveTemplateBanks.length}`
          : undefined,
        `Подключен: ${new Date(account.connectedAt).toLocaleString("ru-RU")}`,
      ].filter(Boolean)
    : [
        "Pager аккаунт не подключён",
        "Можно войти через email + пароль или сохранить cookies.",
        "Для реального live-подключения сейчас уже работает вариант через cookies.",
      ];

  await telegram.sendMessage(
    chatId,
    lines.join("\n"),
    buildPagerAccountKeyboard(Boolean(account)),
  );
}

type MenuAction = "main" | "pager_account" | "channels" | "folders" | "status" | "stats" | "learn" | "reset";

const XP_STATS_COUNTRIES: XPartnersCountry[] = ["CM", "EG", "ZM", "RW"];

function normalizeMenuButtonText(text: string): string {
  return text
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF\u2060]/g, "")
    .replace(/[^\p{L}\p{N}\s/:-]+/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function resolveMenuTextAction(text?: string): MenuAction | undefined {
  if (!text?.trim()) {
    return undefined;
  }
  const normalized = normalizeMenuButtonText(text);
  if (/pager\s*аккаунт|pager\s*account|^account$/.test(normalized)) {
    return "pager_account";
  }
  if (/канал|channels/.test(normalized)) {
    return "channels";
  }
  if (/выбор\s*папок|^папки$|folders/.test(normalized)) {
    return "folders";
  }
  if (/^статус$|^status$|настройки|settings/.test(normalized)) {
    return "status";
  }
  if (/статистик|statistics|^stats$|1xpartners/.test(normalized)) {
    return "stats";
  }
  if (/rw\s*воронка|обучение\s*rw|^обучение$|rw\s*learn|^learn$/.test(normalized)) {
    return "learn";
  }
  if (/^сброс$|^reset$/.test(normalized)) {
    return "reset";
  }
  if (/^меню$|^menu$|^start$/.test(normalized)) {
    return "main";
  }
  return undefined;
}

async function dispatchMenuAction(
  chatId: number,
  state: ChatState,
  action: MenuAction,
  messageId?: number,
): Promise<void> {
  if (action === "main") {
    await sendMainMenu(chatId, state, messageId);
    return;
  }
  if (action === "pager_account") {
    await sendPagerAccountMenu(chatId, state);
    return;
  }
  if (action === "channels") {
    await showChannelsMenu(chatId, state);
    return;
  }
  if (action === "folders") {
    await showFoldersMenu(chatId, state);
    return;
  }
  if (action === "status") {
    await sendStatus(chatId, state);
    return;
  }
  if (action === "stats") {
    await showStatsMenu(chatId, state, messageId);
    return;
  }
  if (action === "learn") {
    const latest = (await stateStore.get(chatId)) ?? state;
    await telegram.sendMessage(chatId, formatRwLearningSummary(latest.rwLearning), buildMainMenuKeyboard());
    return;
  }
  if (action === "reset") {
    await stateStore.delete(chatId);
    const nextState = await getOrCreateState(chatId);
    await telegram.sendMessage(
      chatId,
      `State reset.\nChannel: ${getEffectiveChannel(nextState).name}\nStage: ${nextState.currentStage}`,
      buildMainMenuKeyboard(),
    );
  }
}

async function showStatsMenu(chatId: number, state: ChatState, messageId?: number) {
  const client = getXPartnersClient(env);
  if (!client) {
    await safeEditMenu(
      chatId,
      messageId,
      "1xPartners статистика выключена.\n\nВключите модуль в <b>Variables</b> сервиса Railway.",
      buildMainMenuKeyboard(),
    );
    return;
  }
  try {
    if (shouldFetchStatsFromApi(env)) {
      void ensureXPartnersSession(env).catch(() => {});
    }
  } catch {
    // keep-alive and stat fetches retry too
  }
  const globalStats = await loadGlobalPartnerStats(appMetaStore);
  const hours = globalStats.refreshIntervalHours;
  const stale = cacheStale(globalStats.cachedAt, hours);
  const postbackMode = usesPostbackStats(env);
  const hybridMode = usesHybridStats(env);
  const session = postbackMode && !hybridMode
    ? { connected: true, loginHint: "postback" }
    : await describeXPartnersSession(env, appMetaStore);
  const sessionLine = hybridMode
    ? session.connected
      ? "Сервер: 🟢 hybrid · отчёт из кабинета + postback live"
      : "Сервер: 🔴 hybrid · обнови XPARTNERS_COOKIE в Railway"
    : postbackMode
      ? "Сервер: 🟢 postback · счётчики с входящих {reg}/{ftd}"
      : session.connected
        ? `Сервер: 🟢 в сети · ${maskXPartnersLogin(session.loginHint)}`
        : "Сервер: 🔴 переподключение… (проверь XPARTNERS_* в Railway, если долго)";
  const postbackActivityLine =
    postbackMode || hybridMode ? escapeHtmlLite(await describePostbackActivity(appMetaStore)) : "";
  const postbackHint =
    postbackMode || hybridMode
      ? (() => {
          const cmReg = postbackCabinetSetups(env)[0];
          const cabinetBlock = cmReg
            ? [
                "<b>Форма 1xPartners (пример CM reg):</b>",
                `URL: <code>${escapeHtmlLite(cmReg.url)}</code>`,
                `Статика: <code>${escapeHtmlLite(cmReg.staticParams)}</code>`,
                `Динамика: click_id → <code>{click_id}</code>, reg → <code>{reg}</code>`,
                `Название события: <code>${escapeHtmlLite(cmReg.eventNameInSystem)}</code>`,
                "Метод: GET · 4 postback: CM/ZM × reg/ftd",
              ]
            : [];
          return [
            "",
            hybridMode ? "<b>Hybrid:</b> «Обновить все» = цифры как в «Кратком отчёте»." : "",
            ...cabinetBlock,
            "",
            postbackActivityLine,
            "Трафик только через «Ссылку для размещения» · статус Active.",
          ].filter(Boolean);
        })()
      : [];
  const lines = [
    "<b>1xPartners · Статистика</b>",
    hybridMode
      ? "Hybrid: кабинет при «Обновить все» + postback для новых событий."
      : postbackMode
        ? "Счётчики с postback — каждый {reg} и {ftd} от 1xPartners +1 в бот."
        : "Общий аккаунт на сервере — все смотрят цифры без входа на сайт.",
    hybridMode || !postbackMode ? "Сессия обновляется сама (keep-alive + при запросе статистики)." : "",
    "",
    sessionLine,
    `Кэш: ${stale ? "устарел — «Обновить все»" : "актуален"} · интервал <b>${hours} ч</b>`,
    ...postbackHint,
    "",
    "Cameroon · Egypt · Zambia · Rwanda",
  ];
  await safeEditMenu(chatId, messageId, lines.join("\n"), buildStatsCountryKeyboard());
}

async function fetchAndCacheCountryStats(
  country: XPartnersCountry,
  force: boolean,
): Promise<{ globalStats: GlobalPartnerStatsState; stats: XPartnersQuickStats }> {
  const globalStats = await loadGlobalPartnerStats(appMetaStore);
  const hours = globalStats.refreshIntervalHours;
  const cached = globalStats.byCountry?.[country];
  const cachedAt = globalStats.cachedAt;
  if (usesPostbackStatsForFetch(env)) {
    const stats = await loadPostbackCountryStats(appMetaStore, env, country);
    const nextStats: GlobalPartnerStatsState = {
      refreshIntervalHours: hours,
      cachedAt: new Date().toISOString(),
      byCountry: { ...(globalStats.byCountry ?? {}), [country]: stats },
    };
    await saveGlobalPartnerStats(appMetaStore, nextStats);
    return { globalStats: nextStats, stats };
  }
  const client = getXPartnersClient(env);
  if (!client) {
    throw new Error("1xPartners отключён (XPARTNERS_ENABLED=false).");
  }
  if (!force && cached && !cacheStale(cachedAt, hours)) {
    return { globalStats, stats: cached };
  }
  const stats = await client.fetchQuickStatsToday(country);
  const nextStats: GlobalPartnerStatsState = {
    refreshIntervalHours: hours,
    cachedAt: new Date().toISOString(),
    byCountry: { ...(globalStats.byCountry ?? {}), [country]: stats },
  };
  await saveGlobalPartnerStats(appMetaStore, nextStats);
  return { globalStats: nextStats, stats };
}

async function sendPlayersIdsExport(
  chatId: number,
  target: XPartnersCountry | "ALL",
  callbackId: string,
): Promise<void> {
  const client = getXPartnersClient(env);
  if (!client) {
    await telegram.answerCallbackQuery(callbackId, "1xPartners выключен");
    return;
  }
  await telegram.answerCallbackQuery(callbackId, "Загружаю ID игроков…");

  try {
    const countries: XPartnersCountry[] =
      target === "ALL" ? [...XP_STATS_COUNTRIES] : [target];

    const results = await Promise.allSettled(
      countries.map((c) => client.fetchPlayerIdsToday(c)),
    );

    const keyboard = buildStatsCountryKeyboard();
    if (target === "ALL") {
      let lastSuccessIndex = -1;
      for (let i = 0; i < results.length; i++) {
        if (results[i]?.status === "fulfilled") {
          lastSuccessIndex = i;
        }
      }
      for (let i = 0; i < results.length; i++) {
        const r = results[i]!;
        const country = countries[i]!;
        if (r.status === "rejected") {
          const isLast = i === results.length - 1;
          await telegram.sendMessage(
            chatId,
            `⚠️ <b>${country}</b>: ${escapeHtmlLite(formatError(r.reason))}`,
            isLast && lastSuccessIndex < 0 ? keyboard : undefined,
          );
          continue;
        }
        const e = r.value;
        const parts = formatPlayersIdsMessageParts(e.country, e);
        const isLastCountry = i === results.length - 1;
        for (let p = 0; p < parts.length; p++) {
          const isLastPart = isLastCountry && p === parts.length - 1;
          await telegram.sendMessage(chatId, parts[p]!, isLastPart ? keyboard : undefined);
        }
      }
      if (lastSuccessIndex < 0) {
        await telegram.sendMessage(chatId, "Не удалось загрузить ID ни для одной страны.", keyboard);
      }
      return;
    }

    const single = results[0];
    if (!single || single.status === "rejected") {
      throw single?.reason ?? new Error("1xPartners: нет ответа");
    }

    const data = single.value;
    const parts = formatPlayersIdsMessageParts(data.country, data);
    for (let p = 0; p < parts.length; p++) {
      await telegram.sendMessage(chatId, parts[p]!, p === parts.length - 1 ? keyboard : undefined);
    }
  } catch (error) {
    await telegram.sendMessage(
      chatId,
      `⚠️ ${formatError(error)}`,
      buildStatsCountryKeyboard(),
    );
  }
}

async function sendCountryStats(
  chatId: number,
  state: ChatState,
  country: XPartnersCountry,
  callbackId: string,
): Promise<void> {
  const client = getXPartnersClient(env);
  if (!client) {
    await telegram.answerCallbackQuery(callbackId, "1xPartners выключен");
    await telegram.sendMessage(
      chatId,
      "1xPartners не настроен — добавьте переменные в Railway Variables.",
      buildMainMenuKeyboard(),
    );
    return;
  }
  await telegram.answerCallbackQuery(callbackId, "Загрузка…");
  try {
    const { stats, globalStats } = await fetchAndCacheCountryStats(country, true);
    const text = formatStatsMessage(country, stats, globalStats.refreshIntervalHours);
    await telegram.sendMessage(chatId, text, buildStatsCountryKeyboard());
  } catch (error) {
    await telegram.sendMessage(
      chatId,
      `⚠️ ${formatError(error)}`,
      buildStatsCountryKeyboard(),
    );
  }
}

async function refreshAllPartnerStats(
  chatId: number,
  state: ChatState,
  messageId: number | undefined,
  callbackId: string,
): Promise<void> {
  const client = getXPartnersClient(env);
  if (!client) {
    await telegram.answerCallbackQuery(callbackId, "1xPartners выключен");
    return;
  }
  await telegram.answerCallbackQuery(callbackId, "Обновляю CM, EG, ZM, RW…");
  if (messageId) {
    await safeEditMenu(
      chatId,
      messageId,
      "⏳ Загрузка отчётов 1xPartners…",
      buildStatsCountryKeyboard(),
      callbackId,
    );
  }
  let globalStats = await loadGlobalPartnerStats(appMetaStore);
  const hours = globalStats.refreshIntervalHours;
  const errors: string[] = [];
  const byCountry: Partial<Record<XPartnersCountry, XPartnersQuickStats>> = {
    ...(globalStats.byCountry ?? {}),
  };
  for (const country of XP_STATS_COUNTRIES) {
    try {
      const result = await fetchAndCacheCountryStats(country, true);
      globalStats = result.globalStats;
      byCountry[country] = result.stats;
    } catch (error) {
      const msg = formatError(error);
      errors.push(`${country}: ${msg}`);
      if (isXPartnersSessionError(msg)) {
        break;
      }
    }
  }
  const blocks: string[] = [formatAllCountriesStats(byCountry, hours)];
  if (usesPostbackStats(env) || usesHybridStats(env)) {
    blocks.push("", escapeHtmlLite(await describePostbackActivity(appMetaStore)));
  }
  if (errors.length) {
    const unique = dedupeStatErrors(errors);
    blocks.push("", `<b>Ошибка:</b> ${escapeHtmlLite(unique.join(" · "))}`);
  }
  await safeEditMenu(chatId, messageId, blocks.join("\n").trim(), buildStatsCountryKeyboard(), callbackId);
}

function escapeHtmlLite(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function dedupeStatErrors(errors: string[]): string[] {
  const messages = errors.map((entry) => {
    const splitAt = entry.indexOf(": ");
    return splitAt >= 0 ? entry.slice(splitAt + 2).trim() : entry.trim();
  });
  return [...new Set(messages)];
}

function isXPartnersSessionError(message: string): boolean {
  return (
    message.includes("TOKEN_ERROR") ||
    message.includes("XPARTNERS_COOKIE") ||
    message.includes("cookie не принята") ||
    message.includes("COOKIE_REJECTED") ||
    message.includes("refresh-token") ||
    message.includes("cookie не прошёл") ||
    message.includes("автологин")
  );
}

async function sendStatus(chatId: number, state: ChatState) {
  const effectiveChannel = getEffectiveChannel(state);
  await telegram.sendMessage(
    chatId,
    [
      `Channel: ${effectiveChannel.name}`,
      `Country: ${effectiveChannel.country}`,
      `Stage: ${state.currentStage}`,
      `Template bank: ${state.templateBankOverride ?? effectiveChannel.templateBank}`,
      `Pager account: ${state.pagerAccount ? "saved" : "not connected"}`,
      `Enabled channels: ${collectEnabledChannelIds(state).length}`,
      `Live channels: ${state.pagerAccount?.liveChannels?.length ?? 0}`,
      `Status folders enabled: ${state.statusFolders?.filter((folder) => folder.enabled).length ?? "all (not configured)"}`,
      `Paused: ${state.paused ? "yes" : "no"}`,
      `Pending action: ${state.pendingAction ?? "none"}`,
    ].join("\n"),
    buildMainMenuKeyboard(),
  );
}

function maskEmail(email?: string): string {
  if (!email) {
    return "unknown";
  }

  const [name, domain] = email.split("@");
  if (!domain) {
    return email;
  }

  if (name.length <= 2) {
    return `${name[0] ?? "*"}*@${domain}`;
  }

  return `${name.slice(0, 2)}***@${domain}`;
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

main().catch((error) => {
  console.error("Fatal bot error:", error);
  process.exit(1);
});
