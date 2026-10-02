import type { CountryCode } from "./config.js";
import { CM_SCRIPT_SEARCH_NEEDLES } from "./cm-script-engine.js";
import { EG_SCRIPT_SEARCH_NEEDLES } from "./eg-script-engine.js";
import { ZM_SCRIPT_SEARCH_NEEDLES } from "./zm-script-engine.js";

/** Distinctive multi-word / branded phrases only — short greetings & common words
 *  must NOT mark real customer replies as bot echoes. */
const EXTRA_EG_OUTBOUND =
  /(أهلاً، إذا كنت مهتمًا|اهلا، اذا كنت مهتم|هتعمل حساب من اللينك|السكرين مش واضح|مرحبًا\. تحقق استراتيجياتنا|إنت من مصر\؟|بساعد ناس يعملوا شوية دخل|تمام كده:|هبعتلك اللينك دلوقتي|tinyurl\.com\/egypt0011|\+ الأخضر|ينفع الاتنين)/i;

const MIN_OUTBOUND_NEEDLE_LEN = 12;

function needlesForCountry(country: CountryCode): string[] {
  const map =
    country === "EG"
      ? EG_SCRIPT_SEARCH_NEEDLES
      : country === "CM"
        ? CM_SCRIPT_SEARCH_NEEDLES
        : ZM_SCRIPT_SEARCH_NEEDLES;
  return Object.values(map).flat();
}

export function isAutomatedFunnelOutgoing(text: string, country: CountryCode): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  if (country === "EG" && EXTRA_EG_OUTBOUND.test(t)) {
    return true;
  }
  const lower = t.toLowerCase();
  for (const needle of needlesForCountry(country)) {
    const normalized = needle.trim().toLowerCase();
    if (normalized.length < MIN_OUTBOUND_NEEDLE_LEN) {
      continue;
    }
    if (lower.includes(normalized)) {
      return true;
    }
  }
  return false;
}

/** OCR/caption that mostly mirrors our funnel scripts (e.g. chat screenshot with bot bubbles). */
export function looksLikeOwnScriptEcho(
  text: string,
  country: CountryCode,
  recentOutgoingTexts?: string[],
): boolean {
  const t = (text || "").trim();
  if (!t || t.length < 24) {
    return false;
  }
  if (isAutomatedFunnelOutgoing(t, country)) {
    return true;
  }
  const lower = t.toLowerCase();
  let snippetHits = 0;
  for (const out of recentOutgoingTexts ?? []) {
    const normalized = out.trim();
    if (normalized.length < MIN_OUTBOUND_NEEDLE_LEN) {
      continue;
    }
    const head = normalized.slice(0, 56).toLowerCase();
    if (head.length >= MIN_OUTBOUND_NEEDLE_LEN && lower.includes(head.slice(0, 40))) {
      snippetHits += 1;
    }
  }
  if (snippetHits >= 2) {
    return true;
  }
  return snippetHits >= 1 && t.length >= 100;
}
