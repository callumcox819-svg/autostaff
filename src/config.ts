import { readFileSync } from "node:fs";
import { parse as parseYaml } from "yaml";
import { z } from "zod";

export const PROOF_KINDS = [
  "registration_screenshot",
  "id_screenshot",
  "deposit_balance_screenshot",
  "unclear_screenshot",
 ] as const;

export const proofKindSchema = z.enum(PROOF_KINDS);

export type ProofKind = z.infer<typeof proofKindSchema>;

export const COUNTRIES = ["ZM", "CM", "EG"] as const;

const countrySchema = z.enum(COUNTRIES);

export const STAGES = [
  "new_lead",
  "engaged",
  "registered",
  "deposit_pending",
  "waiting_id",
  "post_deposit",
  "completed",
  "no_money",
  "dormant",
  "not_ready",
 ] as const;

const stageSchema = z.enum(STAGES);

export type Stage = z.infer<typeof stageSchema>;
export type CountryCode = z.infer<typeof countrySchema>;

export const TEMPLATE_ROLES = [
  "intro",
  "details",
  "registration",
  "deposit",
  "ask_id",
  "ask_clear_screenshot",
  "telegram_handoff",
  "no_money",
  "reactivation",
 ] as const;

const templateRoleSchema = z.enum(TEMPLATE_ROLES);

export type TemplateRole = z.infer<typeof templateRoleSchema>;

const templateBankSchema = z.object({
  name: z.string().min(1),
  roles: z.record(templateRoleSchema, z.string().min(1)),
});

const statusMapSchema = z.record(stageSchema, z.string().min(1));

const proofRuleSchema = z.object({
  kind: proofKindSchema,
  nextStage: stageSchema,
  nextTemplateRole: templateRoleSchema.optional(),
});

const textRuleSchema = z.object({
  name: z.string().min(1),
  matchAny: z.array(z.string().min(1)).min(1),
  nextStage: stageSchema,
  nextTemplateRole: templateRoleSchema.optional(),
});

const playbookSchema = z.object({
  country: countrySchema,
  language: z.string().min(1),
  promoCode: z.string().optional(),
  telegramLink: z.string().url(),
  registrationKeywords: z.array(z.string()).default([]),
  depositKeywords: z.array(z.string()).default([]),
  noMoneyKeywords: z.array(z.string()).default([]),
  notReadyKeywords: z.array(z.string()).default([]),
  proofRules: z.array(proofRuleSchema).min(1),
  textRules: z.array(textRuleSchema).min(1),
});

const channelSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  enabled: z.boolean(),
  country: countrySchema,
  templateBank: z.string().min(1),
  statusMap: statusMapSchema,
});

const botConfigSchema = z.object({
  bot: z.object({
    pollIntervalSeconds: z.number().int().positive(),
    preventDuplicateReplyWindowMinutes: z.number().int().positive(),
    requireCustomerLastMessage: z.boolean(),
    skipIfHumanRepliedRecentlyMinutes: z.number().int().nonnegative(),
  }),
  channels: z.array(channelSchema).min(1),
  templateBanks: z.array(templateBankSchema).min(1),
  playbooks: z.array(playbookSchema).min(1),
});

export type BotConfig = z.infer<typeof botConfigSchema>;
export type ChannelConfig = z.infer<typeof channelSchema>;
export type PlaybookConfig = z.infer<typeof playbookSchema>;
export type TemplateBankConfig = z.infer<typeof templateBankSchema>;

export function loadConfig(configPath: string): BotConfig {
  const raw = readFileSync(configPath, "utf8");
  const parsed = parseYaml(raw);
  return botConfigSchema.parse(parsed);
}

export function getChannelConfig(
  config: BotConfig,
  channelId: string,
): ChannelConfig | undefined {
  return config.channels.find((channel) => channel.id === channelId);
}

export function getPlaybook(
  config: BotConfig,
  country: CountryCode,
): PlaybookConfig {
  const playbook = config.playbooks.find((item) => item.country === country);
  if (!playbook) {
    throw new Error(`Missing playbook for country ${country}`);
  }
  return playbook;
}

export function getTemplateBank(
  config: BotConfig,
  templateBankName: string,
): TemplateBankConfig {
  const bank = config.templateBanks.find((item) => item.name === templateBankName);
  if (!bank) {
    throw new Error(`Missing template bank ${templateBankName}`);
  }
  return bank;
}

export function resolveYamlTemplateBankName(
  config: BotConfig,
  country: CountryCode | "RW" | "CL" | "MG" | "DJ" | "JO",
  channelId?: string,
): string {
  if (country === "RW") {
    if (channelId) {
      const channel = getChannelConfig(config, channelId);
      if (channel?.templateBank) {
        return channel.templateBank;
      }
    }
    return "rw-observe";
  }
  if (country === "CL") {
    if (channelId) {
      const channel = getChannelConfig(config, channelId);
      if (channel?.templateBank) {
        return channel.templateBank;
      }
    }
    return "cl-default";
  }
  if (country === "MG") {
    if (channelId) {
      const channel = getChannelConfig(config, channelId);
      if (channel?.templateBank) {
        return channel.templateBank;
      }
    }
    return "mg-default";
  }
  if (country === "DJ") {
    if (channelId) {
      const channel = getChannelConfig(config, channelId);
      if (channel?.templateBank) {
        return channel.templateBank;
      }
    }
    return "dj-default";
  }
  if (country === "JO") {
    if (channelId) {
      const channel = getChannelConfig(config, channelId);
      if (channel?.templateBank) {
        return channel.templateBank;
      }
    }
    return "jo-default";
  }
  if (channelId) {
    const channel = getChannelConfig(config, channelId);
    if (channel?.templateBank) {
      return channel.templateBank;
    }
  }
  return `${country.toLowerCase()}-default`;
}

export function getConfigEnabledChannelIds(config: BotConfig): string[] {
  return config.channels.filter((channel) => channel.enabled).map((channel) => channel.id);
}

export function isChannelConfigured(config: BotConfig, channelId: string): boolean {
  return Boolean(getChannelConfig(config, channelId));
}

export function statusMapForCountry(
  config: BotConfig,
  country: CountryCode | "RW" | "CL" | "MG" | "DJ" | "JO",
): ChannelConfig["statusMap"] {
  if (country === "RW" || country === "CL" || country === "MG" || country === "DJ") {
    return statusMapForCountry(config, "CM");
  }
  if (country === "JO") {
    return statusMapForCountry(config, "EG");
  }
  const channel = config.channels.find((item) => item.country === country);
  if (channel) {
    return channel.statusMap;
  }
  const fallback = config.channels[0];
  if (!fallback) {
    throw new Error("No channels found in config");
  }
  return fallback.statusMap;
}

export function getDefaultEnabledChannel(config: BotConfig): ChannelConfig {
  const channel = config.channels.find((item) => item.enabled) ?? config.channels[0];
  if (!channel) {
    throw new Error("No channels found in config");
  }
  return channel;
}
