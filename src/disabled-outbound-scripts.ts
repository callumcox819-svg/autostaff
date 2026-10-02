import type { TemplateRole } from "./config.js";

/** Telegram channel scripts are permanently disabled — never auto-send. */
export const DISABLED_OUTBOUND_SCRIPT_KEYS = new Set([
  "08_tg_invite",
  "09_tg_link",
  "10_tg_invite",
  "10_tg_link",
  "11_tg_link",
  "11_tg_invite",
]);

export const DISABLED_OUTBOUND_TEMPLATE_ROLES = new Set<TemplateRole>(["telegram_handoff"]);

export function isDisabledOutboundScriptKey(scriptKey: string): boolean {
  const normalized = scriptKey.trim().toLowerCase();
  if (DISABLED_OUTBOUND_SCRIPT_KEYS.has(normalized)) {
    return true;
  }
  return /(?:^|_)tg_(?:invite|link)/i.test(normalized) || normalized.includes("telegram");
}

export function isDisabledOutboundTemplateRole(role: TemplateRole): boolean {
  return DISABLED_OUTBOUND_TEMPLATE_ROLES.has(role);
}

export function filterDisabledScriptKeys(scriptKeys: string[]): string[] {
  return scriptKeys.filter((key) => !isDisabledOutboundScriptKey(key));
}
