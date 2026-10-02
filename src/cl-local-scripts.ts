import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ClReplyLanguage } from "./cl-language.js";

const SCRIPTS_ROOT = join(process.cwd(), "scripts", "cl");
const cache = new Map<string, string>();

export function loadLocalClScript(
  scriptKey: string,
  lang: ClReplyLanguage,
): string | undefined {
  const cacheKey = `${lang}:${scriptKey}`;
  const cached = cache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const path = join(SCRIPTS_ROOT, lang, `${scriptKey}.txt`);
  if (!existsSync(path)) {
    return undefined;
  }

  const text = readFileSync(path, "utf8").trim();
  if (!text) {
    return undefined;
  }

  cache.set(cacheKey, text);
  return text;
}
