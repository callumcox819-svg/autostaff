import type { CountryCode } from "./config.js";
import { describeAiMarketLanguage } from "./ai-country-language.js";
import {
  depositSentInHistory as cmDepositSent,
  gameIdSentInHistory as cmGameIdSent,
  regLinkSentInHistory as cmRegLinkSent,
} from "./cm-script-engine.js";
import {
  depositSentInHistory as egDepositSent,
  gameIdSentInHistory as egGameIdSent,
  regLinkSentInHistory as egRegLinkSent,
} from "./eg-script-engine.js";
import { registrationHelpScriptKeys } from "./funnel-common.js";
import { isLinkAccessProblemMessage } from "./customer-clarity.js";
import { isRegistrationHelpRequest, wantsRegistrationLink } from "./zm-intent.js";
import {
  depositSentInHistory as zmDepositSent,
  gameIdSentInHistory as zmGameIdSent,
  regLinkSentInHistory as zmRegLinkSent,
} from "./zm-script-engine.js";
import {
  depositSentInHistory as mgDepositSent,
  gameIdSentInHistory as mgGameIdSent,
  regLinkSentInHistory as mgRegLinkSent,
} from "./mg-script-engine.js";
import {
  regLinkSentInHistory as djRegLinkSent,
} from "./dj-script-engine.js";
import {
  regLinkSentInHistory as joRegLinkSent,
} from "./jo-script-engine.js";

export type SupportPhase =
  | "off"
  | "pre_deposit"
  | "awaiting_deposit_proof"
  | "awaiting_game_id";

export type SupportCountry = CountryCode | "MG" | "DJ" | "JO";

export type SupportSnapshot = {
  country: SupportCountry;
  /** Post-funnel support agent (folder «в процессе» + reg link sent). */
  active: boolean;
  phase: SupportPhase;
  inProgressFolder: boolean;
  regLinkSent: boolean;
  depositScriptSent: boolean;
  gameIdScriptSent: boolean;
};

type FunnelHistorySignals = {
  regLinkSent: (outgoing: string[]) => boolean;
  depositSent: (outgoing: string[]) => boolean;
  gameIdSent: (outgoing: string[]) => boolean;
  introScriptKeys: string[];
  linkResendScriptKeys: string[];
  depositScriptKeys: string[];
  gameIdScriptKeys: string[];
};

const SUPPORT_FUNNEL: Record<SupportCountry, FunnelHistorySignals> = {
  CM: {
    regLinkSent: cmRegLinkSent,
    depositSent: cmDepositSent,
    gameIdSent: cmGameIdSent,
    introScriptKeys: [
      "01_intro",
      "01_intro_3",
      "02_age",
      "03_steps",
      "04_tier",
      "05_registration",
    ],
    linkResendScriptKeys: ["06_link"],
    depositScriptKeys: ["09_deposit"],
    gameIdScriptKeys: ["08_game_id"],
  },
  EG: {
    regLinkSent: egRegLinkSent,
    depositSent: egDepositSent,
    gameIdSent: egGameIdSent,
    introScriptKeys: ["01_intro", "02_how_it_works", "04_registration"],
    linkResendScriptKeys: ["05_link", "08_app_or_browser"],
    depositScriptKeys: ["06_deposit"],
    gameIdScriptKeys: ["07_game_id"],
  },
  ZM: {
    regLinkSent: zmRegLinkSent,
    depositSent: zmDepositSent,
    gameIdSent: zmGameIdSent,
    introScriptKeys: ["01_intro", "02_how_it_works", "03_zmw_table", "04_registration"],
    linkResendScriptKeys: ["05_link"],
    depositScriptKeys: ["06_deposit"],
    gameIdScriptKeys: ["07_game_id"],
  },
  MG: {
    regLinkSent: mgRegLinkSent,
    depositSent: mgDepositSent,
    gameIdSent: mgGameIdSent,
    introScriptKeys: ["01_intro", "02_how_it_works", "03_mga_table", "04_registration"],
    linkResendScriptKeys: ["05_link"],
    depositScriptKeys: ["06_deposit"],
    gameIdScriptKeys: ["07_game_id"],
  },
  DJ: {
    regLinkSent: djRegLinkSent,
    depositSent: () => false,
    gameIdSent: () => false,
    introScriptKeys: [
      "01_intro",
      "02_how_it_works",
      "03_djf_table",
      "04_ready_ask",
      "05_registration",
    ],
    linkResendScriptKeys: ["06_link", "07_promo"],
    depositScriptKeys: [],
    gameIdScriptKeys: [],
  },
  JO: {
    regLinkSent: joRegLinkSent,
    depositSent: () => false,
    gameIdSent: () => false,
    introScriptKeys: ["01_intro", "02_how_it_works", "03_jod_table", "04_registration"],
    linkResendScriptKeys: ["05_link"],
    depositScriptKeys: [],
    gameIdScriptKeys: [],
  },
};

export function getSupportFunnelConfig(country: SupportCountry): FunnelHistorySignals {
  return SUPPORT_FUNNEL[country];
}

export function buildSupportSnapshot(
  country: SupportCountry,
  inProgressFolder: boolean,
  outgoingTexts: string[],
  options?: { operatorFolderEnabled?: boolean },
): SupportSnapshot {
  const cfg = getSupportFunnelConfig(country);
  const regLinkSent = cfg.regLinkSent(outgoingTexts);
  const depositScriptSent = cfg.depositSent(outgoingTexts);
  const gameIdScriptSent = cfg.gameIdSent(outgoingTexts);
  const folderOk = options?.operatorFolderEnabled !== false;
  const inProgress = inProgressFolder && folderOk;

  if (!inProgress || !regLinkSent) {
    return {
      country,
      active: false,
      phase: "off",
      inProgressFolder: inProgress,
      regLinkSent,
      depositScriptSent,
      gameIdScriptSent,
    };
  }

  let phase: SupportPhase = "pre_deposit";
  if (depositScriptSent && !gameIdScriptSent) {
    phase = "awaiting_deposit_proof";
  } else if (depositScriptSent && gameIdScriptSent) {
    phase = "awaiting_game_id";
  }

  return {
    country,
    active: true,
    phase,
    inProgressFolder: inProgress,
    regLinkSent,
    depositScriptSent,
    gameIdScriptSent,
  };
}

export function describeSupportPhase(support: SupportSnapshot): string {
  if (!support.active) {
    return "";
  }
  const base = `Country ${support.country}; reply ONLY in ${describeAiMarketLanguage(support.country === "MG" || support.country === "DJ" ? "CM" : support.country === "JO" ? "EG" : support.country)}. Folder «в процессе регистрации» — scripts already sent link and steps.`;
  switch (support.phase) {
    case "pre_deposit":
      return `${base} Coach first deposit on the official app/site, payment method for this market, ask for balance screenshot when done. If the customer says they have NO account yet / not registered — do NOT ask for account ID or deposit; scripts resend the registration link.`;
    case "awaiting_deposit_proof":
      return `${base} Deposit instructions sent — reassure, answer questions, acknowledge «will send later», remind to send deposit screenshot. Never coach deposit if they said they are not registered yet.`;
    case "awaiting_game_id":
      return `${base} Deposit done — help with confusion, remind player/account ID is next. Never ask for ID if they said they have no account yet.`;
    default:
      return base;
  }
}

export function filterScriptKeysForSupportAgent(
  country: SupportCountry,
  scriptKeys: string[],
  customerText: string,
  support: SupportSnapshot,
): string[] {
  if (!support.active) {
    return scriptKeys;
  }
  const cfg = getSupportFunnelConfig(country);
  const introSet = new Set(cfg.introScriptKeys);
  let keys = scriptKeys.filter((key) => !introSet.has(key));
  if (isLinkAccessProblemMessage(customerText)) {
    const drop = new Set(cfg.linkResendScriptKeys);
    keys = keys.filter((key) => !drop.has(key));
  }
  if (support.depositScriptSent) {
    const drop = new Set(cfg.depositScriptKeys);
    keys = keys.filter((key) => !drop.has(key));
  }
  return keys;
}

export function supportAgentSkipsEarlyAi(
  country: SupportCountry,
  scriptKeys: string[],
  support: SupportSnapshot,
): boolean {
  if (!support.active || !scriptKeys.length) {
    return false;
  }
  const cfg = getSupportFunnelConfig(country);
  const helpCountry = country === "MG" || country === "DJ" || country === "JO" ? "ZM" : country;
  const mechanical = new Set([
    ...cfg.depositScriptKeys,
    ...cfg.gameIdScriptKeys,
    ...cfg.linkResendScriptKeys,
    ...registrationHelpScriptKeys(helpCountry),
  ]);
  return scriptKeys.some((key) => mechanical.has(key));
}

export function scriptKeysIncludeDeposit(
  country: SupportCountry,
  scriptKeys: string[],
): boolean {
  const cfg = getSupportFunnelConfig(country);
  const set = new Set(cfg.depositScriptKeys);
  return scriptKeys.some((key) => set.has(key));
}

/** Pre-«в процессе»: queued funnel scripts must run before the AI agent. */
export function hasPreSupportFunnelScripts(
  country: SupportCountry,
  scriptKeys: string[],
): boolean {
  if (!scriptKeys.length) {
    return false;
  }
  const cfg = getSupportFunnelConfig(country);
  const mechanical = new Set([
    ...cfg.introScriptKeys,
    ...cfg.linkResendScriptKeys,
    ...cfg.depositScriptKeys,
    ...cfg.gameIdScriptKeys,
  ]);
  return scriptKeys.some((key) => mechanical.has(key));
}

export function inProgressFollowUpEligible(
  support: SupportSnapshot,
  customerText: string,
  hasImage: boolean,
): boolean {
  if (!support.inProgressFolder || !support.regLinkSent) {
    return false;
  }
  if (hasImage) {
    return true;
  }
  if (isLinkAccessProblemMessage(customerText)) {
    return true;
  }
  if (wantsRegistrationLink(customerText) || isRegistrationHelpRequest(customerText)) {
    return true;
  }
  return false;
}
