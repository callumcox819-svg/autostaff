import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = join(process.cwd(), "scripts", "cl");
const link = "https://tinyurl.com/CLE333";
const promo = "CLE577";

/** CM rows → CLP at ~1.65 CLP/XAF (1000/140k XAF → 1650/16500 CLP). */
const CLP_PER_XAF = 1.65;
const CL_DEPOSIT = [825, 1320, 1650, 2500];
const CL_PROFIT = [8250, 13_200, 16_500, 22_400];

function fmtEs(n) {
  return n.toLocaleString("es-CL");
}
function fmtEn(n) {
  return n.toLocaleString("en-US");
}
function fmtFr(n) {
  return n.toLocaleString("fr-FR").replace(/\u202f/g, " ");
}

const tierEs = CL_DEPOSIT.map((d, i) => `${fmtEs(d)} CLP — ${fmtEs(CL_PROFIT[i])} CLP`).join("\n");
const tierEn = CL_DEPOSIT.map((d, i) => `${fmtEn(d)} CLP — ${fmtEn(CL_PROFIT[i])} CLP`).join("\n");
const tierFr = CL_DEPOSIT.map((d, i) => `${fmtFr(d)} CLP — ${fmtFr(CL_PROFIT[i])} CLP`).join("\n");

const packs = {
  es: {
    "01_intro": `¡Hola! ¿Eres de Chile?

Quiero mostrarte cómo trabajo con los casinos.

Llevo mucho tiempo en este sector y conozco bien cómo funciona — no es suerte ni impulsos, sino experiencia, análisis y disciplina.`,
    "01_intro_2": `Mi equipo suma años de experiencia en el terreno. Sabemos detectar los buenos momentos y actuar con método.

Para mí es un negocio como otro: entras en el momento correcto, sigues las instrucciones y sales a tiempo.

Trabajo solo con personas serias, que valoran la transparencia y una actitud responsable.

Si estás listo, te explicaré paso a paso cómo funciona y cómo podemos ganar juntos.`,
    "02_age": `¿Cuántos años tienes?`,
    "03_steps": `De acuerdo, así funciona:

1️⃣ Crea tu cuenta en el casino con mi enlace e ingresa mi código promocional.
2️⃣ Haz un depósito mínimo de ${fmtEs(CL_DEPOSIT[0])} pesos chilenos (CLP).
3️⃣ Te envío instrucciones claras (capturas y explicaciones) — todo está probado por el equipo ✅
4️⃣ Sigue los pasos al pie de la letra, sin improvisar. Juegas solo a los juegos que hemos validado 💰`,
    "04_tier": `Esto es lo que puedes obtener con mi ayuda:

El primer monto es tu inversión.
El segundo monto es tu beneficio.

${tierEs}

¿Qué vas a elegir, amigo?`,
    "05_registration": `Te envío el enlace para descargar la aplicación 👇

Copia este enlace y pégalo en el navegador Google Chrome.

Luego descarga la app, instálala y regístrate.

Es sencillo.

Selecciona tu país y tu moneda.

No olvides el código promocional: ${promo}

Después envíame una captura de pantalla y te ayudo con los siguientes pasos.

Aquí está el enlace:`,
    "06_link": link,
    "07_chrome": `¡Copia este enlace y pégalo en tu navegador Google Chrome!`,
    "08_game_id": `¡Genial! Envía una captura de tu ID de jugador en tu perfil 1xBET (Mi cuenta) — el número empieza por 17.`,
    "09_deposit": `Inicia sesión en 1xBET:
→ «Depositar» o el botón verde «$» arriba a la derecha
→ Elige tu método de pago
→ Deposita el monto elegido

Envía la captura — verifico y seguimos.`,
  },
  en: {
    "01_intro": `Hello! Are you from Chile?

I want to show you how I work with casinos.

I've been in this field for a long time and I know how it works very well — it's not luck or impulse, but experience, analysis and discipline.`,
    "01_intro_2": `My team has years of experience on the ground. We know how to spot the right moments and act with method.

For me it's a business like any other: you enter at the right time, follow the instructions and exit at the right time.

I only work with serious people who value transparency and a responsible approach.

If you're ready, I'll explain step by step how it works and how we can win together.`,
    "02_age": `How old are you?`,
    "03_steps": `Alright, here's how it works:

1️⃣ Create your casino account with my link and enter my promo code.
2️⃣ Make a minimum deposit of ${fmtEn(CL_DEPOSIT[0])} CLP.
3️⃣ I'll send you clear instructions (screenshots and explanations) — everything is tested by the team ✅
4️⃣ Follow the steps exactly. You only play the games we've validated 💰`,
    "04_tier": `Here's what you can get with my help:

The first amount is your investment.
The second amount is your profit.

${tierEn}

What will you choose, my friend?`,
    "05_registration": `I'm sending you the link to download the app 👇

Copy this link and paste it into Google Chrome.

Then download the app, install it and register.

It's simple.

Select your country and currency.

Don't forget the promo code: ${promo}

Then send me a screenshot and I'll help you with the next steps.

Here is the link:`,
    "06_link": link,
    "07_chrome": `Copy this link and paste it into your Google Chrome browser!`,
    "08_game_id": `Great! Send a screenshot of your player ID from your 1xBET profile (My account) — the number starts with 17.`,
    "09_deposit": `Log in to 1xBET:
→ «Deposit» or the green «$» button top right
→ Choose your payment method
→ Deposit the amount you chose

Send the screenshot — I'll verify and we continue!`,
  },
  fr: {
    "01_intro": `Bonjour ! Tu es du Chili ?

Je souhaite te montrer comment je travaille dans les casinos.

Je suis dans ce domaine depuis longtemps et je maîtrise très bien son fonctionnement — ce n'est ni du hasard ni du jeu impulsif, mais une approche fondée sur l'expérience, l'analyse et la discipline.`,
    "01_intro_2": `Mon équipe cumule des années d'expérience sur le terrain. Nous savons repérer les bons moments et comment agir avec méthode.

Pour moi, c'est un business comme un autre : tu entres au bon moment, tu suis les instructions et tu sors au moment opportun.

Je travaille uniquement avec des personnes sérieuses, qui valorisent la transparence et une approche responsable.

Si tu es prêt, je t'expliquerai étape par étape comment cela fonctionne et comment nous pouvons gagner ensemble.`,
    "02_age": `Quel âge avez-vous ?`,
    "03_steps": `D'accord, voici comment ça fonctionne :

1️⃣ Crée ton compte casino via mon lien et saisis mon code promo.
2️⃣ Fais un dépôt minimum de ${fmtFr(CL_DEPOSIT[0])} pesos chiliens (CLP).
3️⃣ Je t'envoie des instructions claires (captures d'écran et explications détaillées) — tout est testé par l'équipe ✅
4️⃣ Suis les étapes à la lettre, sans improviser. Tu joues uniquement aux jeux que nous avons validés 💰`,
    "04_tier": `Voici ce que tu peux obtenir avec mon aide :

Le premier montant correspond à ton investissement.
Le deuxième montant correspond à ton bénéfice.

${tierFr}

Que vas-tu choisir, mon ami ?`,
    "05_registration": `Je vous envoie le lien pour télécharger l'application 👇

Copiez ce lien et collez-le dans le navigateur Google Chrome.

Téléchargez ensuite l'application, installez-la et inscrivez-vous.

C'est simple.

Sélectionnez votre pays et votre devise.

N'oubliez pas le code promo : ${promo}

Envoyez-moi ensuite une capture d'écran et je vous aiderai pour les étapes suivantes.

Voici le lien :`,
    "06_link": link,
    "07_chrome": `Copiez ce lien et collez-le dans votre navigateur Google Chrome !`,
    "08_game_id": `Super ! Envoie une capture d'écran de ton ID joueur depuis ton profil 1xBET (Mon compte) — le numéro commence par 17.`,
    "09_deposit": `Connecte-toi sur 1xBET :
→ « Déposer » ou le bouton vert « $ » en haut à droite
→ Choisis ton moyen de paiement
→ Dépose le montant choisi

Envoie la capture d'écran — je vérifie et on continue !`,
  },
};

for (const [lang, files] of Object.entries(packs)) {
  const dir = join(root, lang);
  mkdirSync(dir, { recursive: true });
  for (const [key, text] of Object.entries(files)) {
    writeFileSync(join(dir, `${key}.txt`), `${text}\n`, "utf8");
  }
}
console.log("CL scripts written:", root);
