import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_DJ_LINK = "https://tinyurl.com/BJI777";

/** Bundled fallbacks if `scripts/dj/*.txt` is missing on the host (Railway cwd, etc.). */
const EMBEDDED_DJ_SCRIPTS: Record<string, string> = {
  "01_intro": `Bonjour ! Je suis ici pour t’apprendre à gagner de l’argent dans les casinos en ligne. Ce n’est ni du hasard ni un jeu basé sur l’intuition.
C’est une approche fondée sur les données, les calculs, la discipline et le contrôle.
Je travaille uniquement avec des personnes sérieuses, qui valorisent la transparence et une approche responsable.
Dans mon activité, j’utilise des systèmes analytiques basés sur l’analyse du marché.
Si tu es prêt, je vais t’expliquer étape par étape comment cela fonctionne et comment nous pouvons gagner ensemble.✅`,
  "02_how_it_works": `Je t’explique tous les détails de comment cela va se passer étape par étape :
1) Tu crées un compte dans le casino via mon lien et tu entres mon code promo (je vais t’aider).
2) Tu fais un dépôt minimum 40 DJF.
3) Tu m’envoies une capture d’écran pour que je voie que tout est fait.
4) Je t’ajoute dans un groupe privé où je t’envoie des instructions claires (captures d’écran et explications détaillées). Tout a été testé par mon équipe- fiabilité garantie!
5) Après avoir obtenu des gains, tu me transfères un petit pourcentage.
6) Le résultat dépend uniquement de ta discipline et du respect exact de toutes les étapes.`,
  "03_djf_table": `Voici ce que vous pouvez obtenir avec mon aide :
Le premier montant est votre dépôt.
Le deuxième montant est votre profit.
100 DJF - 1000 DJF
200 DJF - 5000 DJF
500 DJF - 12000 DJF
1000 DJF - 35000 DJF
Que choisiras-tu, mon ami?`,
  "04_ready_ask": `Pour commencer, il nous faut seulement quelques minutes.
Es-tu prêt à démarrer avec 300 DJF?`,
  "05_registration": `Je vais t'envoyer un lien d'inscription spécial.
Clique sur ce lien.
Appuie sur « Inscription ».
Tu peux t'inscrire en un seul clic ou par e-mail.
Lors de ton inscription, sélectionne ton pays et ta devise.
Utilise le code promo BJI777
Une fois inscrit, envoie-moi un message ici.
Voici le lien :`,
  "06_link": DEFAULT_DJ_LINK,
  "07_promo": `code promo
BJI777`,
};

const cache = new Map<string, string>();

function resolveDjScriptsDir(): string {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "scripts", "dj"),
    join(process.cwd(), "scripts", "dj"),
    join(process.cwd(), "dist", "scripts", "dj"),
  ];
  for (const dir of candidates) {
    if (existsSync(join(dir, "01_intro.txt"))) {
      return dir;
    }
  }
  return candidates[0]!;
}

export function loadLocalDjScript(scriptKey: string): string | undefined {
  const cached = cache.get(scriptKey);
  if (cached) {
    return cached;
  }

  const path = join(resolveDjScriptsDir(), `${scriptKey}.txt`);
  if (existsSync(path)) {
    const text = readFileSync(path, "utf8").trim();
    if (text) {
      cache.set(scriptKey, text);
      return text;
    }
  }

  const embedded = EMBEDDED_DJ_SCRIPTS[scriptKey]?.trim();
  if (embedded) {
    cache.set(scriptKey, embedded);
    return embedded;
  }

  return undefined;
}

export function djDefaultRegistrationLink(): string {
  return loadLocalDjScript("06_link")?.trim() || DEFAULT_DJ_LINK;
}

export function djEmbeddedScriptKeys(): string[] {
  return Object.keys(EMBEDDED_DJ_SCRIPTS);
}
