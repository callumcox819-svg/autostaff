import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import pg from "pg";
import type { AppEnv } from "./env.js";

export interface AppMetaStore {
  get(key: string): Promise<string | undefined>;
  set(key: string, value: string): Promise<void>;
}

export async function createAppMetaStore(env: AppEnv): Promise<AppMetaStore> {
  if (env.DATABASE_URL) {
    const store = new PostgresAppMetaStore(env.DATABASE_URL);
    await store.init();
    return store;
  }
  return new FileAppMetaStore(resolve(process.cwd(), "data/app-meta.json"));
}

class FileAppMetaStore implements AppMetaStore {
  constructor(private readonly filePath: string) {}

  async get(key: string): Promise<string | undefined> {
    const data = this.read();
    return data[key];
  }

  async set(key: string, value: string): Promise<void> {
    const data = this.read();
    data[key] = value;
    this.write(data);
  }

  private read(): Record<string, string> {
    try {
      return JSON.parse(readFileSync(this.filePath, "utf8")) as Record<string, string>;
    } catch {
      return {};
    }
  }

  private write(payload: Record<string, string>): void {
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(payload, null, 2));
  }
}

class PostgresAppMetaStore implements AppMetaStore {
  private readonly pool: pg.Pool;

  constructor(databaseUrl: string) {
    this.pool = new pg.Pool({
      connectionString: databaseUrl,
      ssl: shouldUseSsl(databaseUrl) ? { rejectUnauthorized: false } : undefined,
    });
  }

  async init(): Promise<void> {
    await this.pool.query(`
      CREATE TABLE IF NOT EXISTS bot_app_meta (
        meta_key TEXT PRIMARY KEY,
        meta_value TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);
  }

  async get(key: string): Promise<string | undefined> {
    const result = await this.pool.query<{ meta_value: string }>(
      "SELECT meta_value FROM bot_app_meta WHERE meta_key = $1",
      [key],
    );
    return result.rows[0]?.meta_value;
  }

  async set(key: string, value: string): Promise<void> {
    await this.pool.query(
      `
        INSERT INTO bot_app_meta (meta_key, meta_value, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (meta_key)
        DO UPDATE SET meta_value = EXCLUDED.meta_value, updated_at = NOW()
      `,
      [key, value],
    );
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
