import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_EG_LINK = "https://tinyurl.com/Egypt0011";

/** Bundled fallbacks if `scripts/eg/*.txt` is missing on the host (Railway cwd, etc.). */
const EMBEDDED_EG_SCRIPTS: Record<string, string> = {
  "04_registration": `هبعتلك اللينك دلوقتي
انسخه وحطه في Chrome أو أي متصفح

لما تسجل:
مصر 🇪🇬
EGP جنيه مصري
كود EG011

الإيميل أحسن من الموبايل — SMS بيتأخر ساعات

خلصت؟ ابعتلي`,
  "05_link": DEFAULT_EG_LINK,
};

const cache = new Map<string, string>();

function resolveEgScriptsDir(): string {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "scripts", "eg"),
    join(process.cwd(), "scripts", "eg"),
    join(process.cwd(), "dist", "scripts", "eg"),
  ];
  for (const dir of candidates) {
    if (existsSync(join(dir, "04_registration.txt"))) {
      return dir;
    }
  }
  return candidates[0]!;
}

export function loadLocalEgScript(scriptKey: string): string | undefined {
  const cached = cache.get(scriptKey);
  if (cached) {
    return cached;
  }

  const path = join(resolveEgScriptsDir(), `${scriptKey}.txt`);
  if (existsSync(path)) {
    const text = readFileSync(path, "utf8").trim();
    if (text) {
      cache.set(scriptKey, text);
      return text;
    }
  }

  const embedded = EMBEDDED_EG_SCRIPTS[scriptKey]?.trim();
  if (embedded) {
    cache.set(scriptKey, embedded);
    return embedded;
  }

  return undefined;
}

export function isEgBareLinkOnlyMessage(text: string): boolean {
  const trimmed = (text || "").trim();
  if (!trimmed) {
    return false;
  }
  if (/^https?:\/\/\S+$/i.test(trimmed)) {
    return true;
  }
  return /tinyurl\.com\/egypt0011/i.test(trimmed) && trimmed.length < 160 && !/هبعتلك اللينك/i.test(trimmed);
}

export function buildEgRegistrationOnlyMessage(): string | undefined {
  return loadLocalEgScript("04_registration")?.trim() ?? EMBEDDED_EG_SCRIPTS["04_registration"];
}

export function buildEgLinkOnlyMessage(): string {
  return loadLocalEgScript("05_link")?.trim() || DEFAULT_EG_LINK;
}

/** Block a lone URL when registration text has not gone out yet (caller sends reg first). */
export function shouldBlockEgBareLinkSend(
  replyText: string,
  options: { regAlreadyInHistory: boolean; regSentThisTurn: boolean },
): boolean {
  if (options.regAlreadyInHistory || options.regSentThisTurn) {
    return false;
  }
  return isEgBareLinkOnlyMessage(replyText);
}
