import type { CountryCode } from "./config.js";
import type { AppEnv } from "./env.js";
import type { SupportSnapshot } from "./ai-support-phase.js";
import { describeSupportPhase } from "./ai-support-phase.js";
import {
  aiReplyLooksWrongLanguage,
  buildAiLanguageLockRule,
  describeAiMarketLanguage,
} from "./ai-country-language.js";

export type AiAgentTrigger =
  | "deposit_script_just_sent"
  | "registration_proof_ack";

export type AiAssistContext = {
  country: CountryCode;
  customerText: string;
  recentCustomerTexts: string[];
  recentOutgoingTexts: string[];
  funnelStep: number;
  intent: string;
  scriptKeys?: string[];
  support?: SupportSnapshot;
  agentTrigger?: AiAgentTrigger;
  /** Bypass routing — support agent must reply (post «в процессе»). */
  forceSupportAgent?: boolean;
};

export type AiVisionContext = {
  country: CountryCode;
  caption: string;
  funnelStep: number;
  outgoingTexts: string[];
  proofKind: string;
  imageBase64: string;
  mimeType: string;
  support?: SupportSnapshot;
  ocrCombinedText?: string;
};

const SERVICE_FRAMING = [
  "Business context: we OFFER A LEGITIMATE SERVICE — personal step-by-step guidance on using the platform (registration, deposit, gameplay). You are a service assistant, not a random spammer.",
  "If they ask «is this a scam?» / fraud / trust: answer calmly and realistically — this is a real service, you walk them through official steps on the platform, you are here to help them succeed with clear instructions. Do not dodge the question.",
  "Never ask them to send money to a personal wallet or unknown account in chat. Deposits happen only on the official platform as explained in scripts.",
  "Do not guarantee specific profits or «100% win». Say results depend on following the steps; your role is to guide.",
].join(" ");

const COUNTRY_RULES: Record<CountryCode, string> = {
  EG: [
    buildAiLanguageLockRule("EG"),
    SERVICE_FRAMING,
    "SUPPORT AGENT mode after scripts: warm, patient, like a real operator.",
    "Guide first deposit (green + / deposit), mobile wallet if discussed in thread — do not invent new amounts.",
    "Registration proof: congratulate, ask for deposit then balance screenshot.",
    "Link will not open: Wi‑Fi, different network, open in browser — calm steps, NEVER paste a new URL.",
    "On «هل ده نصب»: calm reassurance, official platform, step-by-step help.",
    "Do not repeat deposit script bullets verbatim — human follow-up only.",
    "If they say NOT registered yet / no account / «لا» to finishing registration — do NOT ask for ID or deposit; registration link scripts handle that.",
    "Max 4 short sentences. No markdown. No URLs.",
    buildAiLanguageLockRule("EG"),
  ].join(" "),
  CM: [
    buildAiLanguageLockRule("CM"),
    SERVICE_FRAMING,
    "SUPPORT AGENT mode after scripts: warm, patient, like a real operator in Telegram.",
    "Guide first deposit on 1xBET (green $ / Déposer, MTN or Orange). Minimum in thread is often 1 000 CFA — do not invent promos unless the customer said them.",
    "Registration proof: congratulate, ask for balance screenshot after top-up.",
    "Acknowledge «Ok boss», «j'ai déjà fait», waiting for screenshot — brief and friendly.",
    "Link/MTN/Orange issues: Wi‑Fi, other operator, Google Chrome — no new URL.",
    "On «arnaque»: calm reassurance.",
    "Do not repeat deposit script verbatim.",
    "If they say NOT registered yet / no account / «Non» or «No» to finishing registration — do NOT ask for ID or deposit; registration link scripts handle that.",
    "Max 4 short sentences. No markdown. No URLs.",
    buildAiLanguageLockRule("CM"),
  ].join(" "),
  ZM: [
    buildAiLanguageLockRule("ZM"),
    SERVICE_FRAMING,
    "SUPPORT AGENT mode after scripts: warm, patient, like a real operator.",
    "Guide first deposit (Deposit button / green +), mobile money as in thread — do not invent amounts.",
    "Registration proof: congratulate, ask for deposit screenshot when ready.",
    "If they say NOT registered yet / no account — do NOT ask for ID or deposit; registration link scripts handle that.",
    "If they say they are NOT registered yet or have no account: do NOT coach deposit or ask for ID — registration link scripts handle that.",
    "Link or network issues: Wi‑Fi, try again in Chrome, different network — no new URL.",
    "On «scam»: calm reassurance.",
    "Do not repeat deposit script verbatim.",
    "Max 4 short sentences. No markdown. No URLs.",
    buildAiLanguageLockRule("ZM"),
  ].join(" "),
};

function buildSystemPrompt(country: CountryCode, ctx?: AiAssistContext): string {
  const supportMode =
    ctx?.support?.active ||
    ctx?.agentTrigger === "deposit_script_just_sent" ||
    ctx?.agentTrigger === "registration_proof_ack";

  const supportBlock =
    supportMode && ctx?.support
      ? [
          `MODE: SUPPORT AGENT (${country}, post-scripts, «в процессе регистрации»).`,
          describeSupportPhase(ctx.support),
          "Automated scripts sent mechanical steps; YOU coach deposit, handle doubts, operator/network issues, waiting for screenshots.",
        ].join(" ")
      : supportMode
        ? `MODE: SUPPORT AGENT (${country}) — short human follow-up after an automated script.`
        : "";

  const baseRole = supportMode
    ? "You are the SUPPORT AGENT on a Pager inbox bot. Scripts already sent intro, link, and deposit instructions where applicable."
    : "You are the AI AGENT layer on a Pager inbox bot. Preset SCRIPTS send funnel messages.";

  const baseJob = supportMode
    ? "Your job: human follow-up until deposit screenshot and game/account ID — all complex or emotional messages."
    : "Your job when routed: vague, complex, skeptical, or trust questions. Scripts handle mechanical funnel steps.";

  return [
    baseRole,
    baseJob,
    supportBlock,
    COUNTRY_RULES[country],
    supportMode ? "" : "Max 5 short sentences. No markdown. No JSON. No URLs.",
  ]
    .filter(Boolean)
    .join(" ");
}

function buildUserPrompt(ctx: AiAssistContext): string {
  const parts = [
    `Country: ${ctx.country}`,
    `Required reply language: ${describeAiMarketLanguage(ctx.country)}`,
    `Funnel step: ${ctx.funnelStep}`,
    `Classifier intent: ${ctx.intent}`,
  ];
  if (ctx.support?.active) {
    parts.push(`Support phase: ${ctx.support.phase}`);
  }
  if (ctx.agentTrigger === "deposit_script_just_sent") {
    parts.push(
      "Trigger: deposit instruction script was just sent automatically. Short operator follow-up: motivate deposit, ask for screenshot when done. Do not repeat the full step list.",
    );
  }
  if (ctx.agentTrigger === "registration_proof_ack") {
    parts.push(
      "Trigger: registration screenshot recognized. Acknowledge and guide to deposit + screenshot.",
    );
  }
  parts.push(
    `Planned script keys (do not duplicate verbatim): ${ctx.scriptKeys?.join(", ") || "none"}`,
  );
  if (ctx.customerText.trim()) {
    parts.push(`Latest customer message: ${ctx.customerText}`);
  }
  if (ctx.recentCustomerTexts.length > 1) {
    parts.push(`Recent customer lines:\n${ctx.recentCustomerTexts.slice(0, 5).join("\n")}`);
  }
  if (ctx.recentOutgoingTexts.length) {
    parts.push(
      `Recent operator/bot outgoings (context only — do NOT reply to these unless the customer quoted them):\n${ctx.recentOutgoingTexts.slice(-4).join("\n---\n")}`,
    );
  }
  parts.push(
    "Reply ONLY to the latest customer message above. Scripts already sent mechanical steps — do not echo or expand our own script text.",
  );
  return parts.join("\n\n");
}

function buildLanguageRetryUserPrompt(country: CountryCode): string {
  return `Your previous reply used the wrong language. Rewrite from scratch. ${buildAiLanguageLockRule(country)}`;
}

async function completeWithLanguageGuard(
  env: AppEnv,
  country: CountryCode,
  system: string,
  user: string | Array<{ type: string; text?: string; image_url?: { url: string } }>,
  model?: string,
): Promise<string | undefined> {
  const apiKey = env.AI_API_KEY!.trim();
  const resolvedModel = model?.trim() || env.AI_MODEL;
  let reply = sanitizeAiReply(
    await openAiChatCompletion(env, resolvedModel, system, user),
    country,
  );
  if (reply && aiReplyLooksWrongLanguage(country, reply)) {
    console.warn(`AI assist wrong language for ${country}, retrying once`);
    reply = sanitizeAiReply(
      await openAiChatCompletion(
        env,
        resolvedModel,
        system,
        typeof user === "string"
          ? `${user}\n\n${buildLanguageRetryUserPrompt(country)}`
          : [
              ...(user as Array<{ type: string; text?: string; image_url?: { url: string } }>),
              { type: "text", text: buildLanguageRetryUserPrompt(country) },
            ],
      ),
      country,
    );
  }
  if (reply && aiReplyLooksWrongLanguage(country, reply)) {
    console.warn(`AI assist still wrong language for ${country} — dropping reply`);
    return undefined;
  }
  return reply;
}

function buildVisionSystemPrompt(country: CountryCode, support?: SupportSnapshot): string {
  const supportHint = support?.active
    ? "SUPPORT AGENT: praise registration proof, guide deposit + screenshot; thank for balance shot; ask for clearer image if needed."
    : "Describe briefly what you see if relevant, then reply to the customer.";
  return [
    "You see a customer screenshot (registration / app / deposit proof).",
    "If the image shows a Telegram/chat thread: ignore operator/bot bubbles (our scripts) — only react to the customer's new app screenshot or their caption.",
    "Do not reply to or repeat text visible from our own automated messages in the screenshot.",
    buildSystemPrompt(country, support ? { country, support } as AiAssistContext : undefined),
    supportHint,
    "Plain text reply only. No URLs.",
  ].join(" ");
}

async function openAiChatCompletion(
  env: AppEnv,
  model: string,
  system: string,
  user: string | Array<{ type: string; text?: string; image_url?: { url: string } }>,
): Promise<string | undefined> {
  const apiKey = env.AI_API_KEY!.trim();
  const userContent =
    typeof user === "string"
      ? user
      : user.map((part) => {
          if (part.type === "text") {
            return { type: "text" as const, text: part.text ?? "" };
          }
          return {
            type: "image_url" as const,
            image_url: { url: part.image_url?.url ?? "", detail: "low" as const },
          };
        });

  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
  };
  if (env.AI_HTTP_REFERER?.trim()) {
    headers["HTTP-Referer"] = env.AI_HTTP_REFERER.trim();
  }
  if (env.AI_APP_TITLE?.trim()) {
    headers["X-Title"] = env.AI_APP_TITLE.trim();
  }

  const response = await fetch(env.AI_BASE_URL, {
    method: "POST",
    headers,
    body: JSON.stringify({
      model,
      temperature: 0.35,
      max_tokens: 500,
      messages: [
        { role: "system", content: system },
        {
          role: "user",
          content: userContent,
        },
      ],
    }),
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const hint =
      env.AI_API_KEY?.startsWith("sk-or-") && env.AI_BASE_URL.includes("api.openai.com")
        ? " (OpenRouter key requires AI_BASE_URL=https://openrouter.ai/api/v1/chat/completions)"
        : "";
    console.warn(`AI assist HTTP ${response.status}${hint}: ${body.slice(0, 280)}`);
    return undefined;
  }
  const payload = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const text = payload.choices?.[0]?.message?.content?.trim();
  return text || undefined;
}

function sanitizeAiReply(
  reply: string | undefined,
  country?: CountryCode,
): string | undefined {
  if (!reply?.trim()) {
    return undefined;
  }
  if (/https?:\/\/\S+/i.test(reply)) {
    console.warn("AI assist rejected reply containing URL");
    return undefined;
  }
  const trimmed = reply.trim();
  if (country && aiReplyLooksWrongLanguage(country, trimmed)) {
    return undefined;
  }
  return trimmed;
}

/** OpenAI call — invoked only via ai-agent routing. */
export async function maybeAiAssistReply(
  env: AppEnv,
  ctx: AiAssistContext,
): Promise<string | undefined> {
  if (!env.AI_ENABLED || !env.AI_API_KEY?.trim()) {
    return undefined;
  }
  if (!ctx.customerText.trim() && !ctx.agentTrigger && !ctx.forceSupportAgent) {
    return undefined;
  }

  try {
    return await completeWithLanguageGuard(
      env,
      ctx.country,
      buildSystemPrompt(ctx.country, ctx),
      buildUserPrompt(ctx),
    );
  } catch (error) {
    console.warn("AI assist failed:", error instanceof Error ? error.message : error);
    return undefined;
  }
}

export async function maybeAiAssistVision(
  env: AppEnv,
  ctx: AiVisionContext,
): Promise<string | undefined> {
  if (!env.AI_ENABLED || !env.AI_API_KEY?.trim()) {
    return undefined;
  }
  const model = env.AI_VISION_MODEL?.trim() || env.AI_MODEL;
  const dataUrl = `data:${ctx.mimeType};base64,${ctx.imageBase64}`;
  const userParts = [
    {
      type: "text",
      text: [
        `Country: ${ctx.country}`,
        `Required reply language: ${describeAiMarketLanguage(ctx.country)}`,
        `Funnel step: ${ctx.funnelStep}`,
        `OCR/proof classifier: ${ctx.proofKind}`,
        `Caption: ${ctx.caption || "(none)"}`,
        ctx.support?.active ? `Support phase: ${ctx.support.phase}` : "",
      ]
        .filter(Boolean)
        .join("\n"),
    },
    { type: "image_url", image_url: { url: dataUrl } },
  ];

  try {
    return await completeWithLanguageGuard(
      env,
      ctx.country,
      buildVisionSystemPrompt(ctx.country, ctx.support),
      userParts,
      model,
    );
  } catch (error) {
    console.warn("AI vision failed:", error instanceof Error ? error.message : error);
    return undefined;
  }
}

export function detectImageMimeType(image: Buffer): string {
  if (image[0] === 0xff && image[1] === 0xd8) {
    return "image/jpeg";
  }
  if (image[0] === 0x89 && image[1] === 0x50) {
    return "image/png";
  }
  if (image[0] === 0x47 && image[1] === 0x49) {
    return "image/gif";
  }
  if (image[0] === 0x52 && image[1] === 0x49) {
    return "image/webp";
  }
  return "image/jpeg";
}

export type CmVisionExtract = {
  ocrText: string;
  login17?: string;
  screen: "registration_success" | "app_balance" | "other";
};

/** Read CM proof fields from a screenshot when Tesseract misses Login 17 or balance. */
export async function maybeAiVisionExtractCmProof(
  env: AppEnv,
  options: {
    imageBase64: string;
    mimeType: string;
    caption: string;
    depositScriptAlreadySent: boolean;
  },
): Promise<CmVisionExtract | undefined> {
  if (!env.AI_ENABLED || !env.AI_API_KEY?.trim()) {
    return undefined;
  }
  const model = env.AI_VISION_MODEL?.trim() || env.AI_MODEL;
  const dataUrl = `data:${options.mimeType};base64,${options.imageBase64}`;
  const system = [
    "You read customer screenshots for a Cameroon (CM) 1xBET onboarding funnel.",
    "Our client Login IDs ALWAYS start with 17 (ten digits typical). Ignore IDs starting with 16.",
    "Reply with ONE JSON object only, no markdown:",
    '{"ocrText":"all visible text you can read","login17":"17xxxxxxxx or empty","screen":"registration_success|app_balance|other"}',
    "registration_success = Inscription réussie / login password screen.",
    "app_balance = 1xBET home with balance like 1020 F in the header.",
  ].join(" ");
  const userParts = [
    {
      type: "text",
      text: [
        `Caption: ${options.caption || "(none)"}`,
        `Deposit script already sent in chat: ${options.depositScriptAlreadySent ? "yes" : "no"}`,
      ].join("\n"),
    },
    { type: "image_url", image_url: { url: dataUrl } },
  ];

  try {
    const raw = await openAiChatCompletion(env, model, system, userParts);
    if (!raw?.trim()) {
      return undefined;
    }
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return undefined;
    }
    const parsed = JSON.parse(jsonMatch[0]) as {
      ocrText?: string;
      login17?: string;
      screen?: string;
    };
    const ocrText = (parsed.ocrText || "").trim();
    let login17 = (parsed.login17 || "").replace(/\D/g, "");
    if (login17 && !/^17\d{5,}$/.test(login17)) {
      login17 = "";
    }
    const screen =
      parsed.screen === "registration_success" || parsed.screen === "app_balance"
        ? parsed.screen
        : "other";
    if (!ocrText && !login17) {
      return undefined;
    }
    return { ocrText, login17: login17 || undefined, screen };
  } catch (error) {
    console.warn("CM AI vision extract failed:", error instanceof Error ? error.message : error);
    return undefined;
  }
}

export function cmVisionExtractToCombinedText(
  extract: CmVisionExtract,
  caption: string,
): string {
  const parts = [caption, extract.ocrText];
  if (extract.login17) {
    parts.push(`Login: ${extract.login17}`);
  }
  if (extract.screen === "registration_success") {
    parts.push("Inscription réussie");
  }
  if (extract.screen === "app_balance") {
    parts.push("1xbet balance F");
  }
  return parts.filter(Boolean).join("\n");
}
