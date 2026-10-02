import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_JO_LINK = "https://tinyurl.com/JOR77";

/** Bundled fallbacks if `scripts/jo/*.txt` is missing on the host. */
const EMBEDDED_JO_SCRIPTS: Record<string, string> = {
  "01_intro": `مرحبًا! أريد أن أريكم كيف أعمل مع منصات الكازينو. أنا أستخدم الأنظمة التحليلية وأدوات الذكاء الاصطناعي لتحديد أفضل اللحظات للدخول في اللعبة.
هذه ليست لعبة قمار عشوائية. هذا أسلوب يعتمد على البيانات، الإحصائيات، الانضباط والاستراتيجية. يقوم الذكاء الاصطناعي بتحليل العديد من جلسات اللعب والإحصائيات للعثور على أفضل الفرص، في حين أن خبرتي تساعد في فهم كيفية عمل المنصة.
بالنسبة لي، هذا بمثابة عمل تجاري: أنت تدخل في اللحظة المناسبة، تتبع التعليمات وتخرج في الوقت المناسب. أنا أعمل فقط مع الأشخاص الجادين المستعدين لاتباع التعليمات والعمل بمسؤولية. إذا كنت مهتمًا، يمكنني أن أشرح لك خطوة بخطوة كيف يعمل هذا وكيف يمكنك البدء.`,
  "02_how_it_works": `كيف يعمل الأمر:
1) تقوم بإنشاء حساب في الكازينو من خلال النقر على الرابط الخاص بي وإدخال الرمز الترويجي الخاص بي
2) تقوم بإيداع مبلغ لا يقل عن 2 دينار أردني $
3) سأرسل لك تعليمات واضحة (لقطات شاشة وتفسيرات مفصلة). تم التحقق من كل شيء من قبل فريقي: الموثوقية مضمونة! ✅
4) مهمتك هي اتباع التعليمات بدقة، دون اتخاذ أي مبادرة خاصة من جانبك. ستلعب فقط الألعاب التي قمنا باختبارها بدقة والتي تحقق أرباحًا 💰`,
  "03_jod_table": `إليك ما يمكنك الحصول عليه بمساعدتي:
المبلغ الأول هو إيداعك 💵
المبلغ الثاني هو ربحك 💰
2 دينار أردني – 30 دينار أردني
5 دينار أردني – 75 دينار أردني
15 دينار أردني – 120 دينار أردني
ماذا ستختار يا صديقي؟`,
  "04_registration": `سأرسل لك رابطًا خاصًا للتسجيل.
أوقف تشغيل VPN، وانسخ الرابط وألصقه في متصفح Google Chrome.
انقر على «التسجيل».
يمكنك التسجيل «بنقرة واحدة» أو عبر البريد الإلكتروني.
أثناء التسجيل، حدد بلدك والعملة التي تفضلها.
استخدم الرمز الترويجي JOR778
بعد التسجيل، أرسل لي رسالة هنا.
إليك الرابط:`,
  "05_link": DEFAULT_JO_LINK,
};

const cache = new Map<string, string>();

function resolveJoScriptsDir(): string {
  const moduleDir = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(moduleDir, "..", "scripts", "jo"),
    join(process.cwd(), "scripts", "jo"),
    join(process.cwd(), "dist", "scripts", "jo"),
  ];
  for (const dir of candidates) {
    if (existsSync(join(dir, "01_intro.txt"))) {
      return dir;
    }
  }
  return candidates[0]!;
}

export function loadLocalJoScript(scriptKey: string): string | undefined {
  const cached = cache.get(scriptKey);
  if (cached) {
    return cached;
  }

  const path = join(resolveJoScriptsDir(), `${scriptKey}.txt`);
  if (existsSync(path)) {
    const text = readFileSync(path, "utf8").trim();
    if (text) {
      cache.set(scriptKey, text);
      return text;
    }
  }

  const embedded = EMBEDDED_JO_SCRIPTS[scriptKey]?.trim();
  if (embedded) {
    cache.set(scriptKey, embedded);
    return embedded;
  }

  return undefined;
}

export function joDefaultRegistrationLink(): string {
  return loadLocalJoScript("05_link")?.trim() || DEFAULT_JO_LINK;
}

export function joEmbeddedScriptKeys(): string[] {
  return Object.keys(EMBEDDED_JO_SCRIPTS);
}
