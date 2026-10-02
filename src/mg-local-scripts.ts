import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_MG_LINK = "https://tinyurl.com/MDG56";

/** Bundled fallbacks if `scripts/mg/*.txt` is missing on the host (Railway cwd, etc.). */
const EMBEDDED_MG_SCRIPTS: Record<string, string> = {
  "01_intro": `Vous cherchez un moyen d'augmenter vos revenus? Je sais comment exploiter les plateformes de casino! Je travaille avec des personnes sérieuses, car cette méthode repose sur l'analyse, les statistiques, la discipline et la stratégie : il ne s'agit pas de jeu au hasard! L'intelligence artificielle analyse de nombreuses sessions de jeu et des statistiques afin d'identifier les meilleurs moments dans le jeu. Je peux vous aider à réaliser vos premiers gains et à comprendre le fonctionnement de la plateforme. C’est comme une activité commerciale: vous arrivez au bon moment et vous partez au bon moment. Si cela vous intéresse, je vais vous guider à travers quelques étapes simples et vous expliquer le processus étape par étape pour que vous puissiez commencer dès aujourd’hui!`,
  "02_how_it_works": `Comment ça marche :
1. Vous créez un compte sur le casino en utilisant mon lien.
2. Le dépôt minimum n’est que de 5000 MGA.
3. Je vous enverrai des instructions claires (captures d’écran et explications détaillées), basées sur une analyse par intelligence artificielle. Mon équipe teste régulièrement cette méthode: la fiabilité est garantie!
4. Votre tâche consiste à suivre les instructions à la lettre. Vous ne jouerez qu’aux jeux que nous testons personnellement et qui sont garantis de générer des bénéfices!`,
  "03_mga_table": `Voici ce que vous pourrez obtenir grâce à mon aide :
Le premier montant correspond à votre dépôt.
Le deuxième montant correspond à vos bénéfices.
5000 MGA - 20000 MGA
8000 MGA - 40000 MGA
15000 MGA - 120000 MGA
30000 MGA - 240000 MGA
Lequel préférez-vous?)`,
  "04_registration": `Je vais t'envoyer un lien d'inscription spécial.
Copie-le et colle-le dans ton navigateur Google Chrome.
Appuie sur « Inscription ».
Tu peux t'inscrire en un seul clic ou par e-mail.
Lors de ton inscription, sélectionne ton pays et ta devise.
Utilise le code promo MAD778
Une fois inscrit, envoie-moi un message ici.
Voici le lien :`,
  "05_link": DEFAULT_MG_LINK,
  "06_deposit": `Connecte-toi, clique sur «Déposer» ou le bouton vert « $ » en haut à droite. Choisis un mode de paiement pratique .Après le dépôt, envoie-moi une capture d'écran pour confirmation.Je t'attends`,
  "07_game_id": `Envoyez-moi votre identifiant de jeu ; vous le trouverez dans votre profil (dans le coin droit). il commence par les chiffres 17.`,
};

const cache = new Map<string, string>();

function resolveMgScriptsDir(): string {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "scripts", "mg"),
    join(process.cwd(), "scripts", "mg"),
    join(process.cwd(), "dist", "scripts", "mg"),
  ];
  for (const dir of candidates) {
    if (existsSync(join(dir, "01_intro.txt"))) {
      return dir;
    }
  }
  return candidates[0]!;
}

export function loadLocalMgScript(scriptKey: string): string | undefined {
  const cached = cache.get(scriptKey);
  if (cached) {
    return cached;
  }

  const path = join(resolveMgScriptsDir(), `${scriptKey}.txt`);
  if (existsSync(path)) {
    const text = readFileSync(path, "utf8").trim();
    if (text) {
      cache.set(scriptKey, text);
      return text;
    }
  }

  const embedded = EMBEDDED_MG_SCRIPTS[scriptKey]?.trim();
  if (embedded) {
    cache.set(scriptKey, embedded);
    return embedded;
  }

  return undefined;
}

export function mgDefaultRegistrationLink(): string {
  return loadLocalMgScript("05_link")?.trim() || DEFAULT_MG_LINK;
}

export function mgEmbeddedScriptKeys(): string[] {
  return Object.keys(EMBEDDED_MG_SCRIPTS);
}
