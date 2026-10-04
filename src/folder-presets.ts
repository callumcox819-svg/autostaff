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

export type PresetBubble = {
  text: string;
  index: number;
  role: string;
};

export type PresetPlan =
  | { action: "send"; bubbles: PresetBubble[]; table: boolean }
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

function replyHasUrl(text: string): boolean {
  return /https?:\/\/|tinyurl\.com|bit\.ly|t\.me\/|www\./i.test(text);
}

function looksLikeRegistrationCopy(text: string): boolean {
  const folded = foldPresetText(text);
  return /voici le lien|here is the link|este es el enlace|aqui esta el enlace|aqui tienes el enlace|lien special|lien d'inscription|special registration link|enlace especial|je vais vous envoyer un lien|te enviare un enlace|te envio el enlace|codigo promo|code promo/.test(
    folded,
  );
}

/**
 * Registration instructions with the URL in the next saved reply.
 * Same rule for every Melbet country: the link bubble follows the registration text.
 */
export function isRegistrationWithoutLink(
  text: string,
  replies?: PagerSavedReply[],
  index?: number,
): boolean {
  if (!text.trim() || replyHasUrl(text) || isTablePresetText(text)) {
    return false;
  }
  if (replies && index != null) {
    for (let cursor = index + 1; cursor < replies.length && cursor <= index + 2; cursor += 1) {
      const next = replies[cursor];
      if (!next?.text.trim() || isTablePresetText(next.text)) {
        break;
      }
      if (replyHasUrl(next.text)) {
        return true;
      }
      if (next.text.trim().length > 180) {
        break;
      }
    }
  }
  return looksLikeRegistrationCopy(text);
}

function replyWasSent(replyText: string, outgoingTexts: string[]): boolean {
  const url = replyText.match(/https?:\/\/\S+/i)?.[0]?.replace(/[),.;]+$/g, "");
  if (url && url.length >= 12) {
    const needle = url.toLowerCase();
    if (outgoingTexts.some((outgoing) => outgoing.toLowerCase().includes(needle))) {
      return true;
    }
  }
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

function bubbleAt(replies: PagerSavedReply[], index: number): PresetBubble | undefined {
  const reply = replies[index];
  if (!reply?.text.trim()) {
    return undefined;
  }
  return { text: reply.text, index, role: `preset:${index + 1}` };
}

/** Registration text plus the following link bubble (and a short promo line between them). */
export function registrationBundle(replies: PagerSavedReply[], start: number): PresetBubble[] {
  const first = bubbleAt(replies, start);
  if (!first) {
    return [];
  }
  const bubbles = [first];
  if (!isRegistrationWithoutLink(first.text, replies, start)) {
    return bubbles;
  }
  for (let cursor = start + 1; cursor < replies.length && bubbles.length < 3; cursor += 1) {
    const next = replies[cursor];
    if (!next?.text.trim() || isTablePresetText(next.text)) {
      break;
    }
    const isLink = replyHasUrl(next.text);
    if (!isLink && next.text.trim().length > 180) {
      break;
    }
    const bubble = bubbleAt(replies, cursor);
    if (!bubble) {
      break;
    }
    bubbles.push(bubble);
    if (isLink) {
      break;
    }
  }
  return bubbles;
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

/** Customer is moving the saved-reply funnel forward, not only a bare «oui». */
function shouldAdvancePreset(language: PresetLanguage, text: string): boolean {
  if (isDecline(language, text)) {
    return false;
  }
  const folded = foldPresetText(text).replace(/[!?.…]+$/g, "").trim();
  if (!folded || folded.length > 120) {
    return false;
  }
  if (/\b(arnaque|scam|voleur|faux numero|faux compte)\b/.test(folded)) {
    return false;
  }
  if (isBareAgreement(language, text)) {
    return true;
  }
  if (language === "es") {
    if (/^(aok|ok+|si+|quiero|me interesa|mas info|necesito ayuda)/.test(folded) || /\b(invertir|informacion|ayuda)\b/.test(folded)) {
      return true;
    }
  } else if (
    /^(aok|okk|ok+|ouii|wi+|plus d'infos?|plus dinfos|infos|je voulais|j'ai besoin|besoin d'aide|aidemoi|aide moi|aidez)/.test(
      folded,
    ) ||
    /\b(investir|investissement|interesse|plus d'info|besoin d'aide|gagner de l'argent)\b/.test(folded)
  ) {
    return true;
  }
  // Short replies after a script («Aok», «Je voulais investir») must not leave the chat stuck.
  return folded.length <= 80;
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
  options?: { restartIfUnscripted?: boolean },
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
    // Catch-up of «Без статусу»: a human line before the bot was on must not block preset 1.
    if (alreadySpoke && !options?.restartIfUnscripted) {
      return null;
    }
    const first = replies[0];
    if (!first?.text.trim()) {
      return null;
    }
    const bubbles = registrationBundle(replies, 0);
    if (!bubbles.length) {
      return null;
    }
    return {
      action: "send",
      bubbles,
      table: tableIndex === 0,
    };
  }

  const agreed =
    shouldAdvancePreset(language, customerText) || (last === tableIndex && isTableAmountChoice(customerText));
  if (!agreed) {
    return null;
  }

  const next = last + 1;
  if (next >= replies.length) {
    return { action: "hold", reason: "agreement-after-last-preset" };
  }
  const bubbles = registrationBundle(replies, next).filter(
    (bubble) => !replyWasSent(bubble.text, outgoingTexts),
  );
  if (!bubbles.length) {
    return { action: "hold", reason: "empty-next-preset" };
  }
  return {
    action: "send",
    bubbles,
    table: bubbles.some((bubble) => bubble.index === tableIndex),
  };
}

/** Registration instructions and the link bubble after them are both already in the thread. */
export function folderRegistrationLinkWasSent(
  replies: PagerSavedReply[],
  outgoingTexts: string[],
): boolean {
  for (let index = 0; index < replies.length; index += 1) {
    const reply = replies[index];
    if (!reply || !isRegistrationWithoutLink(reply.text, replies, index) || !replyWasSent(reply.text, outgoingTexts)) {
      continue;
    }
    const link = registrationBundle(replies, index).find((bubble) => replyHasUrl(bubble.text));
    if (link && replyWasSent(link.text, outgoingTexts)) {
      return true;
    }
  }
  return replies.some(
    (reply) =>
      replyHasUrl(reply.text) &&
      replyWasSent(reply.text, outgoingTexts) &&
      looksLikeRegistrationCopy(reply.text),
  );
}

/** Registration already went out, but the link saved-reply after it did not. */
export function planMissingRegistrationLink(
  replies: PagerSavedReply[],
  outgoingTexts: string[],
): PresetBubble[] | null {
  const last = lastSentPresetIndex(replies, outgoingTexts);
  if (last < 0 || !isRegistrationWithoutLink(replies[last]?.text ?? "", replies, last)) {
    return null;
  }
  const missing = registrationBundle(replies, last)
    .slice(1)
    .filter((bubble) => !replyWasSent(bubble.text, outgoingTexts));
  return missing.length ? missing : null;
}
