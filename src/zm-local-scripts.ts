import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SCRIPTS_DIR = join(process.cwd(), "scripts", "zm");
const cache = new Map<string, string>();

export function loadLocalZmScript(scriptKey: string): string | undefined {
  const cached = cache.get(scriptKey);
  if (cached) {
    return cached;
  }

  const path = join(SCRIPTS_DIR, `${scriptKey}.txt`);
  if (!existsSync(path)) {
    return undefined;
  }

  const text = readFileSync(path, "utf8").trim();
  if (!text) {
    return undefined;
  }

  cache.set(scriptKey, text);
  return text;
}
