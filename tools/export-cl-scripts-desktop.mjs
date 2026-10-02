import { cpSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const root = join(process.cwd(), "scripts", "cl");
const desktop = join(homedir(), "Desktop", "Chile-Bot-Scripts");

mkdirSync(desktop, { recursive: true });
for (const lang of ["es", "en", "fr"]) {
  cpSync(join(root, lang), join(desktop, lang), { recursive: true });
}

const readme = `CHILE (CL) — шаблоны бота
Регистрация: https://tinyurl.com/CLE333
Промокод: CLE577

Папки:
  es/ — испанский (по умолчанию)
  en/ — английский
  fr/ — французский

Порядок воронки:
  01_intro → 01_intro_2 → 02_age → 03_steps → 04_tier
  → 05_registration → 06_link → 07_chrome (3 сообщения)
  → 09_deposit → 08_game_id

04_tier (CLP):
  825 — 8250
  1320 — 13200
  1650 — 16500
  2500 — 22400

Источник в проекте: scripts/cl/
Обновление: node tools/gen-cl-scripts.mjs && node tools/export-cl-scripts-desktop.mjs
`;

writeFileSync(join(desktop, "README.txt"), readme, "utf8");
console.log("Exported to:", desktop);
