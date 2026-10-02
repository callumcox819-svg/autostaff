#!/usr/bin/env node
import "dotenv/config";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PagerClient } from "../dist/pager-client.js";
import { parseCookieHeader, enrichPagerCookies } from "../dist/clerk-auth.js";

const ROOT = process.cwd();
const COOKIE_FILE = join(ROOT, "tools", ".pager-cookie");

const FOLDER_HINTS = {
  ZM: ["замб", "zamb", "zambia"],
  RW: ["ruand", "rwand", "rw", "руанд"],
};

const ZM_KEYS = [
  "01_intro",
  "02_how_it_works",
  "03_zmw_table",
  "04_registration",
  "05_link",
  "06_deposit",
  "07_game_id",
  "08_tg_invite",
  "09_tg_link",
  "10_reg_screenshot",
  "11_fb_link",
];

const RW_KEYS = [
  "01_intro",
  "02_how_it_works",
  "03_deposit_table",
  "04_registration",
  "05_link",
  "06_deposit",
  "07_game_id",
  "08_tg_invite",
  "09_tg_link",
  "10_reg_screenshot",
  "11_fb_link",
];

const RW_ALIASES = {
  "03_deposit_table": ["03_zmw_table"],
};

function scriptNameMatchesKey(name, scriptKey) {
  const normalized = (name || "").trim().toLowerCase().replace(/\.txt$/, "");
  const key = scriptKey.trim().toLowerCase();
  return normalized === key || normalized.endsWith(`/${key}`) || normalized.includes(key);
}

function keysForLookup(scriptKey, country) {
  if (country === "RW") {
    return [scriptKey, ...(RW_ALIASES[scriptKey] ?? [])];
  }
  return [scriptKey];
}

function pickReply(replies, scriptKey, country) {
  for (const key of keysForLookup(scriptKey, country)) {
    const exact = replies.find((reply) => scriptNameMatchesKey(reply.name, key) && reply.text?.trim());
    if (exact) {
      return exact;
    }
  }
  return undefined;
}

function findFolder(banks, hints) {
  return banks.find((bank) => {
    const name = bank.name.toLowerCase();
    return hints.some((hint) => name.includes(hint));
  });
}

function writeScripts(country, keys, replies, outDir) {
  mkdirSync(outDir, { recursive: true });
  let written = 0;
  for (const key of keys) {
    const reply = pickReply(replies, key, country);
    if (!reply?.text?.trim()) {
      console.warn(`[${country}] miss ${key}`);
      continue;
    }
    const path = join(outDir, `${key}.txt`);
    writeFileSync(path, `${reply.text.trim()}\n`, "utf8");
    console.log(`[${country}] wrote ${key}.txt (${reply.text.trim().length} chars)`);
    written += 1;
  }
  return written;
}

async function main() {
  const cookieRaw =
    process.argv[2]?.trim() ||
    process.env.PAGER_COOKIE?.trim() ||
    (existsSync(COOKIE_FILE) ? readFileSync(COOKIE_FILE, "utf8").trim() : "");
  if (!cookieRaw) {
    console.error("Add cookie one of:");
    console.error("  PAGER_COOKIE in .env");
    console.error("  tools/.pager-cookie");
    console.error("  node tools/sync-pager-scripts.mjs \"<cookie header>\"");
    process.exit(1);
  }

  const enriched = enrichPagerCookies(cookieRaw, {
    organizationId: process.env.PAGER_ORG_ID,
    pagerUserId: process.env.PAGER_USER_ID,
  });
  const cookies = parseCookieHeader(enriched);
  const client = new PagerClient({
    baseUrl: process.env.PAGER_BASE_URL || "https://www.pager.co.ua",
    cookieHeader: enriched,
    orgId: process.env.PAGER_ORG_ID || cookies._pager_org_id,
    orgSlug: process.env.PAGER_ORG_SLUG || cookies._pager_org_slug,
    locale: "uk",
    sessionUserId: process.env.PAGER_USER_ID || cookies._pager_user_id,
  });

  await client.validateSession();
  const banks = await client.getTemplateBanks();
  console.log(
    "folders:",
    banks.map((bank) => `${bank.name} (${bank.replyCount})`).join(", "),
  );

  const zmFolder = findFolder(banks, FOLDER_HINTS.ZM);
  const rwFolder = findFolder(banks, FOLDER_HINTS.RW);
  if (!zmFolder) {
    console.error("Zambia folder not found");
  }
  if (!rwFolder) {
    console.error("Rwanda folder not found");
  }

  let total = 0;
  if (zmFolder) {
    const replies = await client.getSavedReplies(zmFolder.id);
    console.log(`ZM folder: ${zmFolder.name} · ${replies.length} replies`);
    total += writeScripts("ZM", ZM_KEYS, replies, join(ROOT, "scripts", "zm"));
  }
  if (rwFolder) {
    const replies = await client.getSavedReplies(rwFolder.id);
    console.log(`RW folder: ${rwFolder.name} · ${replies.length} replies`);
    total += writeScripts("RW", RW_KEYS, replies, join(ROOT, "scripts", "rw"));
  }

  if (!total) {
    process.exit(1);
  }
  console.log(`done: ${total} files`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
