import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import pg from "pg";
import type { Stage } from "./config.js";
import type { AppEnv } from "./env.js";
import type { RwLearningState, WorkerCountry } from "./rw-learn.js";
import type { StatusFolderState } from "./status-folders.js";

export type PendingAction =
  | "await_pager_email"
  | "await_pager_password"
  | "await_pager_cookies";

export type PagerAccountState = {
  authMode: "credentials" | "cookies";
  email?: string;
  password?: string;
  cookies?: string;
  organizationId?: string;
  organizationName?: string;
  organizationSlug?: string;
  liveChannels?: Array<{
    id: string;
    name: string;
    channelSource?: string | null;
  }>;
  liveTemplateBanks?: Array<{
    id: string;
    name: string;
    replyCount?: number;
  }>;
  pagerUserId?: string;
  connectedAt: string;
};

export type ChannelRuntimeState = {
  enabled: boolean;
  country: WorkerCountry;
  templateBank?: string;
  templateBankId?: string;
};

export type ConversationRuntimeState = {
  conversationId: string;
  channelId: string;
  currentStage: Stage;
  lastCustomerMessageId?: string;
  lastCustomerMessageAt?: string;
  lastReplyAt?: string;
  lastReplyRole?: string;
  funnelStep?: number;
  sendFailures?: number;
  /** Set when the bot moves the chat to «в процессе регистрации» (not legacy folder rows). */
  inProgressEnteredAt?: string;
  /** Reg link went out but folder move failed — worker retries until cleared. */
  pendingInProgressMoveAt?: string;
  inProgressFollowUpDueAt?: string;
  inProgressFollowUpVariant?: 0 | 1;
  inProgressFollowUpSentAt?: string;
  /** Throttle failed send retries for in-progress follow-up. */
  inProgressFollowUpLastAttemptAt?: string;
  /** After «already registered?» → customer said not yet → bot asked when they plan to register. */
  inProgressPlanAskSentAt?: string;
  /** Operator took over, or follow-up flow finished (yes / after plan ask / other) — bot stays silent. */
  inProgressMutedAt?: string;
  /** Moved to «ИГНОР» — no scripts, no AI. */
  ignoredAt?: string;
  /** Chile funnel reply language (es/en/fr). */
  clReplyLanguage?: "es" | "en" | "fr";
};

export type ChatState = {
  chatId: number;
  channelId: string;
  currentStage: Stage;
  templateBankOverride?: string;
  pendingAction?: PendingAction;
  draftPagerEmail?: string;
  pagerAccount?: PagerAccountState;
  /** Source of truth for which Pager channels the worker polls. */
  enabledChannelIds?: string[];
  channels?: Record<string, ChannelRuntimeState>;
  conversations?: Record<string, ConversationRuntimeState>;
  statusFolders?: StatusFolderState[];
  /** Survives relogin/redeploy — source of truth for worker processing. */
  operatorSettings?: {
    enabledChannelIds: string[];
    statusFolders?: StatusFolderState[];
  };
  /** When true, worker skips auto-replies for this Telegram operator. */
  paused?: boolean;
  /** One-shot / timed «догнать чаты»: re-process read threads within the window. */
  catchUpRead?: {
    activeUntil: string;
    requestedAt?: string;
    windowHours?: number;
    notifiedAt?: string;
  };
  /** Наблюдение за оператором (Руанда): без take/send, только лог событий. */
  rwLearning?: RwLearningState;
  /** 1xPartners quick report cache + refresh interval for «Статистика». */
  partnerStats?: {
    refreshIntervalHours: 1 | 3 | 5;
    cachedAt?: string;
    byCountry?: Partial<
      Record<
        "CM" | "EG" | "ZM" | "RW",
        {
          registrations: number;
          newAccountsWithDeposits: number;
          fetchedAt: string;
          siteLabel: string;
        }
      >
    >;
  };
  updatedAt: string;
};

export interface StateStore {
  get(chatId: number): Promise<ChatState | undefined>;
  listAll(): Promise<ChatState[]>;
  upsert(nextState: ChatState): Promise<ChatState>;
  patch(chatId: number, patch: Partial<Omit<ChatState, "chatId">>): Promise<ChatState | undefined>;
  delete(chatId: number): Promise<void>;
}

type StatePayload = {
  chats: Record<string, ChatState>;
};

export async function createStateStore(env: AppEnv): Promise<StateStore> {
  if (env.DATABASE_URL) {
    const store = new PostgresStateStore(env.DATABASE_URL);
    await store.init();
    await migrateFileStateIfNeeded(store, env);
    console.log("State store: PostgreSQL");
    return store;
  }

  console.log("State store: local JSON file");
  return new FileStateStore(resolve(process.cwd(), env.BOT_STATE_PATH));
}

class FileStateStore implements StateStore {
  constructor(private readonly filePath: string) {}

  async get(chatId: number): Promise<ChatState | undefined> {
    const data = this.read();
    return data.chats[String(chatId)];
  }

  async listAll(): Promise<ChatState[]> {
    const data = this.read();
    return Object.values(data.chats);
  }

  async upsert(nextState: ChatState): Promise<ChatState> {
    const data = this.read();
    data.chats[String(nextState.chatId)] = nextState;
    this.write(data);
    return nextState;
  }

  async patch(chatId: number, patch: Partial<Omit<ChatState, "chatId">>): Promise<ChatState | undefined> {
    const current = await this.get(chatId);
    if (!current) {
      return undefined;
    }

    const nextState = mergeChatState(current, patch);
    return this.upsert(nextState);
  }

  async delete(chatId: number): Promise<void> {
    const data = this.read();
    delete data.chats[String(chatId)];
    this.write(data);
  }

  private read(): StatePayload {
    try {
      const raw = readFileSync(this.filePath, "utf8");
      return JSON.parse(raw) as StatePayload;
    } catch {
      return { chats: {} };
    }
  }

  private write(payload: StatePayload): void {
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(payload, null, 2));
  }
}

class PostgresStateStore implements StateStore {
  private readonly pool: pg.Pool;

  constructor(databaseUrl: string) {
    this.pool = new pg.Pool({
      connectionString: databaseUrl,
      ssl: shouldUseSsl(databaseUrl) ? { rejectUnauthorized: false } : undefined,
    });
  }

  async init(): Promise<void> {
    await this.pool.query(`
      CREATE TABLE IF NOT EXISTS bot_chat_states (
        chat_id BIGINT PRIMARY KEY,
        state JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);
  }

  async get(chatId: number): Promise<ChatState | undefined> {
    const result = await this.pool.query<{ state: ChatState }>(
      "SELECT state FROM bot_chat_states WHERE chat_id = $1",
      [chatId],
    );
    return result.rows[0]?.state;
  }

  async listAll(): Promise<ChatState[]> {
    const result = await this.pool.query<{ state: ChatState }>(
      "SELECT state FROM bot_chat_states ORDER BY updated_at DESC",
    );
    return result.rows.map((row) => row.state);
  }

  async upsert(nextState: ChatState): Promise<ChatState> {
    await this.pool.query(
      `
        INSERT INTO bot_chat_states (chat_id, state, updated_at)
        VALUES ($1, $2::jsonb, $3::timestamptz)
        ON CONFLICT (chat_id)
        DO UPDATE SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at
      `,
      [nextState.chatId, JSON.stringify(nextState), nextState.updatedAt],
    );
    return nextState;
  }

  async patch(chatId: number, patch: Partial<Omit<ChatState, "chatId">>): Promise<ChatState | undefined> {
    const current = await this.get(chatId);
    if (!current) {
      return undefined;
    }

    const nextState = mergeChatState(current, patch);
    return this.upsert(nextState);
  }

  async delete(chatId: number): Promise<void> {
    await this.pool.query("DELETE FROM bot_chat_states WHERE chat_id = $1", [chatId]);
  }
}

async function migrateFileStateIfNeeded(store: PostgresStateStore, env: AppEnv): Promise<void> {
  const filePath = resolve(process.cwd(), env.BOT_STATE_PATH);
  let payload: StatePayload;

  try {
    payload = JSON.parse(readFileSync(filePath, "utf8")) as StatePayload;
  } catch {
    return;
  }

  const chats = Object.values(payload.chats ?? {});
  if (!chats.length) {
    return;
  }

  let migrated = 0;
  for (const chat of chats) {
    const existing = await store.get(chat.chatId);
    if (existing) {
      continue;
    }
    await store.upsert(chat);
    migrated += 1;
  }

  if (migrated > 0) {
    console.log(`Migrated ${migrated} chat state(s) from ${env.BOT_STATE_PATH} into PostgreSQL`);
  }
}

function shouldUseSsl(databaseUrl: string): boolean {
  const normalized = databaseUrl.toLowerCase();
  return (
    normalized.includes("sslmode=require") ||
    normalized.includes("railway.app") ||
    normalized.includes("neon.tech") ||
    normalized.includes("supabase.co")
  );
}

export function mergeChatState(
  current: ChatState,
  patch: Partial<Omit<ChatState, "chatId">>,
): ChatState {
  const nextChannels = patch.channels
    ? { ...(current.channels ?? {}), ...patch.channels }
    : current.channels;

  const nextConversations = patch.conversations
    ? { ...(current.conversations ?? {}), ...patch.conversations }
    : current.conversations;

  const nextPagerAccount = patch.pagerAccount
    ? { ...(current.pagerAccount ?? { authMode: "cookies", connectedAt: current.updatedAt }), ...patch.pagerAccount }
    : current.pagerAccount;

  const nextOperatorSettings = patch.operatorSettings
    ? { ...(current.operatorSettings ?? { enabledChannelIds: [] }), ...patch.operatorSettings }
    : current.operatorSettings;

  let enabledChannelIds = patch.enabledChannelIds ?? current.enabledChannelIds;
  if (!enabledChannelIds?.length && nextOperatorSettings?.enabledChannelIds?.length) {
    enabledChannelIds = nextOperatorSettings.enabledChannelIds;
  }
  if (!enabledChannelIds?.length && nextChannels) {
    enabledChannelIds = Object.entries(nextChannels)
      .filter(([, runtime]) => runtime.enabled)
      .map(([channelId]) => channelId);
  }

  const statusFolders = patch.statusFolders ?? nextOperatorSettings?.statusFolders ?? current.statusFolders;

  return {
    ...current,
    ...patch,
    channels: nextChannels,
    conversations: nextConversations,
    pagerAccount: nextPagerAccount,
    operatorSettings: nextOperatorSettings,
    enabledChannelIds,
    statusFolders,
    updatedAt: new Date().toISOString(),
  };
}
