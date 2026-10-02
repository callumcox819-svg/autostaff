import type { PagerSavedReply } from "./pager-client.js";

/** Countries whose saved-reply folders drive the early funnel. */
export type FolderMarketCode = "MR" | "DJ" | "BF" | "CM" | "BJ" | "CR" | "SN";

export type PresetLanguage = "fr" | "es";

export type FolderMarket = {
  language: PresetLanguage;
  hints: string[];
  label: string;
};

export const FOLDER_MARKETS: Record<FolderMarketCode, FolderMarket> = {
  MR: { language: "fr", hints: ["мавритан", "mauritan"], label: "Мавритания" },
  DJ: { language: "fr", hints: ["джибут", "djibouti", "djib"], label: "Джибути" },
  BF: { language: "fr", hints: ["буркина", "burkina"], label: "Буркина-Фасо" },
  CM: { language: "fr", hints: ["камер", "cameroon", "cameroun"], label: "Камерун" },
  BJ: { language: "fr", hints: ["бенін", "бенин", "benin", "bénin"], label: "Бенин" },
  CR: { language: "es", hints: ["коста", "costa"], label: "Коста-Рика" },
  SN: { language: "fr", hints: ["сенегал", "senegal", "sénégal"], label: "Сенегал" },
};

/** Markets that have no legacy script engine and must use folder order. */
export const FOLDER_ONLY_COUNTRIES = ["MR", "BF", "BJ", "CR", "SN"] as const;

export type FolderOnlyCountry = (typeof FOLDER_ONLY_COUNTRIES)[number];

export function isFolderMarket(country: string): country is FolderMarketCode {
  return Object.prototype.hasOwnProperty.call(FOLDER_MARKETS, country);
}

export function isFolderOnlyCountry(country: string): country is FolderOnlyCountry {
  return (FOLDER_ONLY_COUNTRIES as readonly string[]).includes(country);
}

export function folderMarketLanguage(country: string): PresetLanguage | undefined {
  return isFolderMarket(country) ? FOLDER_MARKETS[country].language : undefined;
}

/** Infer Melbet country from a Pager saved-reply folder name (e.g. «Бенин» → BJ). */
export function inferFolderMarketFromBankName(bankName?: string): FolderMarketCode | undefined {
  if (!bankName?.trim()) {
    return undefined;
  }
  const normalized = bankName
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
  for (const code of Object.keys(FOLDER_MARKETS) as FolderMarketCode[]) {
    if (FOLDER_MARKETS[code].hints.some((hint) => normalized.includes(hint))) {
      return code;
    }
  }
  return undefined;
}

/**
 * Melbet: if saved country is a stale 1xbet code (ZM/RW/…), recover from template folder.
 */
export function coerceMelbetCountry(
  country: string | undefined,
  templateBank?: string,
  channelName?: string,
): FolderMarketCode | undefined {
  if (country && isFolderMarket(country)) {
    return country;
  }
  const fromBank = inferFolderMarketFromBankName(templateBank);
  if (fromBank) {
    return fromBank;
  }
  if (channelName) {
    const normalized = channelName.toLowerCase();
    for (const code of Object.keys(FOLDER_MARKETS) as FolderMarketCode[]) {
      if (FOLDER_MARKETS[code].hints.some((hint) => normalized.includes(hint))) {
        return code;
      }
    }
  }
  return undefined;
}

export type PresetPlan =
  | { action: "send"; text: string; index: number; role: string; table: boolean }
  | { action: "hold"; reason: string };

const AMOUNT_PAIR =
  /(\d[\d\s.,]{0,12})\s*(?:mru|djf|xof|fcfa|cfa|crc|usd|eur|€)?\s*[-–—]\s*(\d[\d\s.,]{0,12})/gi;

export function foldPresetText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[’`]/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

export function isTablePresetText(text: string): boolean {
  const matches = text.match(AMOUNT_PAIR);
  return (matches?.length ?? 0) >= 2;
}

export function findTablePresetIndex(replies: PagerSavedReply[]): number {
  return replies.findIndex((reply) => isTablePresetText(reply.text));
}

function replyWasSent(replyText: string, outgoingTexts: string[]): boolean {
  const folded = foldPresetText(replyText);
  const needle = folded.slice(0, 80);
  if (needle.length < 24) {
    return false;
  }
  return outgoingTexts.some((outgoing) => {
    const body = foldPresetText(outgoing);
    if (!body) {
      return false;
    }
    if (body.includes(needle)) {
      return true;
    }
    return body.length >= 24 && needle.includes(body.slice(0, 80));
  });
}

export function lastSentPresetIndex(replies: PagerSavedReply[], outgoingTexts: string[]): number {
  for (let index = replies.length - 1; index >= 0; index -= 1) {
    if (replyWasSent(replies[index]?.text ?? "", outgoingTexts)) {
      return index;
    }
  }
  return -1;
}

function isDecline(language: PresetLanguage, text: string): boolean {
  const folded = foldPresetText(text);
  if (!folded) {
    return false;
  }
  if (language === "es") {
    return /^(no|nop|nel|luego|despues|ahora no|no tengo|no me interesa|no quiero|para|dejalo|basta)\b/.test(
      folded,
    );
  }
  return /^(non|nan|pas interesse|pas d'argent|j'ai pas|je n'ai pas|plus tard|pas maintenant|arrete|stop|laisse)\b/.test(
    folded,
  );
}

function isBareAgreement(language: PresetLanguage, text: string): boolean {
  const raw = text.trim();
  if (!raw || raw.length > 80 || raw.includes("?")) {
    return false;
  }
  const folded = foldPresetText(raw);
  if (!folded || isDecline(language, folded)) {
    return false;
  }
  if (
    /\b(comment|pourquoi|combien|quel|quelle|cuando|como|por que|why|how)\b/.test(folded) &&
    !/^(oui|ouais|ok|si|dale|claro)\b/.test(folded)
  ) {
    return false;
  }
  const pattern =
    language === "es"
      ? /^(si|ok|okay|okey|dale|va|vale|listo|de acuerdo|claro|bueno|quiero|me interesa|vamos|perfecto|sale|simon|yes|ya)([\s,!.]+.*)?$/
      : /^(oui|ouais|ouai|ok|okay|okey|d'accord|daccord|dac|yes|si|bien sur|bien|super|parfait|vas-y|vas y|go|ca marche|je suis pret|pret|interesse|je veux|montre|montrez|explique|continue|suivant|merci|allons-y|d'acc)([\s,!.]+.*)?$/;
  return pattern.test(folded);
}

function isTableAmountChoice(text: string): boolean {
  const folded = foldPresetText(text);
  if (!folded || folded.length > 40 || text.includes("?")) {
    return false;
  }
  return /\d/.test(folded);
}

/**
 * Next saved reply after an agreement.
 * Preset 2 (index 1) always advances to preset 3 (index 2).
 * If that reply is not the amount table, it is sent as-is; the table is the later step.
 */
export function planFolderPresetAdvance(
  replies: PagerSavedReply[],
  outgoingTexts: string[],
  customerText: string,
  language: PresetLanguage,
): PresetPlan | null {
  if (!replies.length || !customerText.trim()) {
    return null;
  }
  if (isDecline(language, customerText)) {
    return null;
  }

  const last = lastSentPresetIndex(replies, outgoingTexts);
  const tableIndex = findTablePresetIndex(replies);

  if (last < 0) {
    const alreadySpoke = outgoingTexts.some((text) => text.trim().length > 0);
    if (alreadySpoke) {
      return null;
    }
    const first = replies[0];
    if (!first?.text.trim()) {
      return null;
    }
    return {
      action: "send",
      text: first.text,
      index: 0,
      role: "preset:1",
      table: tableIndex === 0,
    };
  }

  const agreed = isBareAgreement(language, customerText) || (last === tableIndex && isTableAmountChoice(customerText));
  if (!agreed) {
    return null;
  }

  const next = last + 1;
  if (next >= replies.length) {
    return { action: "hold", reason: "agreement-after-last-preset" };
  }
  const reply = replies[next];
  if (!reply?.text.trim()) {
    return { action: "hold", reason: "empty-next-preset" };
  }
  return {
    action: "send",
    text: reply.text,
    index: next,
    role: `preset:${next + 1}`,
    table: next === tableIndex,
  };
}
