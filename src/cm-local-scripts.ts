import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SCRIPTS_DIR = join(process.cwd(), "scripts", "cm");
const cache = new Map<string, string>();

const CM_KEY_ALIASES: Record<string, string> = {
  "02_how_it_works": "02_age",
  "03_zmw_table": "04_tier",
  "04_registration": "05_registration",
  "05_link": "06_link",
  "06_deposit": "09_deposit",
  "07_game_id": "08_game_id",
};

export function resolveCmScriptKey(key: string): string {
  return CM_KEY_ALIASES[key] ?? key;
}

export function loadLocalCmScript(scriptKey: string): string | undefined {
  const key = resolveCmScriptKey(scriptKey);
  const cached = cache.get(key);
  if (cached) {
    return cached;
  }

  const path = join(SCRIPTS_DIR, `${key}.txt`);
  if (!existsSync(path)) {
    return undefined;
  }

  const text = readFileSync(path, "utf8").trim();
  if (!text) {
    return undefined;
  }

  cache.set(key, text);
  return text;
}
