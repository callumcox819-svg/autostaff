import { existsSync } from "node:fs";
import { join } from "node:path";
import type { CountryCode } from "./config.js";

const ZM_ASSETS_DIR = join(process.cwd(), "scripts", "zm", "assets");

const SCRIPT_ATTACHMENT_FILES: Partial<Record<CountryCode, Record<string, string>>> = {
  ZM: {
    "07_game_id": "07_game_id_hint.png",
  },
};

export type ScriptAttachment = {
  path: string;
  mimeType: string;
  filename: string;
};

export function resolveScriptAttachment(
  country: CountryCode,
  scriptKey: string,
): ScriptAttachment | undefined {
  const file = SCRIPT_ATTACHMENT_FILES[country]?.[scriptKey];
  if (!file) {
    return undefined;
  }

  const path = join(ZM_ASSETS_DIR, file);
  if (!existsSync(path)) {
    return undefined;
  }

  return {
    path,
    mimeType: mimeTypeForFilename(file),
    filename: file,
  };
}

function mimeTypeForFilename(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".png")) {
    return "image/png";
  }
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (lower.endsWith(".webp")) {
    return "image/webp";
  }
  return "application/octet-stream";
}
