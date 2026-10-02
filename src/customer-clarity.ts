/** Doubt, confusion, skepticism — customer needs a human-like reply before the next script step. */

const CLARITY_PATTERNS = [
  // Arabic
  /مش\s*فاهم|مش\s*عارف|مش\s*مقتنع|هل\s*ده\s*حق|هل\s*هذا\s*حق|ممكن\s*تشرح|اشرح\s*لي|ازاي\s*بالظبط|إزاي\s*بالظبط|مش\s*واضح|مش\s*متاك|متأكد|مضمون|نصب|احتيال|حقيق|واثق/i,
  // French
  /pas\s*compris|je\s*ne\s*comprends|vraiment\s*vrai|est-ce\s*(que\s*)?(vrai|s[eé]rieux|sûr|sur)|arnaque|escroc|comment\s*faire|explique|pas\s*clair/i,
  // English
  /don'?t\s*understand|do\s*not\s*understand|not\s*clear|is\s*this\s*(real|true|legit|a\s*scam|scam)|are\s*you\s*sure|how\s*exactly|what\s*do\s*i\s*need|confus|scam|trust|fraud|fake|legit/i,
  // Russian / Ukrainian (common in operator chats)
  /не\s*понима|не\s*понят|точно\s*ли|правда\s*ли|это\s*правда|как\s*именно|как\s*надо|обман|развод|не\s*верю|это\s*скам|скам\??|мошен/i,
  /\?/,
];

const SHORT_REG_TECH_HELP =
  /(sms|код|code|otp|chrome|линк|link|url|tinyurl|eg011|cash056|zam577|zam777|promo)/i;

/** True when the customer needs reassurance or explanation, not the next funnel preset yet. */
export function isCustomerClarificationMessage(text: string): boolean {
  const t = (text || "").trim();
  if (!t || t.length < 3) {
    return false;
  }
  if (t.length > 400) {
    return false;
  }
  if (!CLARITY_PATTERNS.some((pattern) => pattern.test(t))) {
    return false;
  }
  // Pure "send link / promo code" tech requests stay on script path.
  if (SHORT_REG_TECH_HELP.test(t) && !/(مش|pas|don'?t|не\s*пон)/i.test(t)) {
    return false;
  }
  return true;
}

/** Link / operator / Wi‑Fi issues — agent advises; scripts stay for funnel steps. */
export function isLinkAccessProblemMessage(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return /(j['']arrive pas|pas acc[eè]s|acc[eè]der|acc[eè]s|wifi|wi-fi|sans wifi|no wifi|donn[eé]es mobile|op[eé]rateur|operateur|\bmtn\b|\borange\b|lien.*(marche|ouvre|fonctionne)|link.*(work|open|load)|tinyurl|page.*(blanche|vide)|ne s['']ouvre pas)/i.test(
    t,
  );
}
export function isScamOrTrustQuestion(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  return /(scam|скам|мошен|развод|обман|arnaque|escroc|fraude|fake|n'?est\s*pas\s*vrai|احتيال|نصب|نصبة|هل\s*.*نصب|حقيق)/i.test(t);
}

/** Customer says they are not registered / have no account yet — funnel must resend reg+link, not ID/deposit. */
export function isCustomerSaysNotRegisteredYet(text: string): boolean {
  const t = (text || "").trim();
  if (!t) {
    return false;
  }
  // Bare "no" is ambiguous (declining offer vs not registered) — handled in funnel intent, not here.
  if (/\b(no i am not|not yet|no not yet|no i haven'?t|no i have not)\b/i.test(t)) {
    return true;
  }
  if (
    /\b(not|still|never)\s+(registered|registed|regestered|inscrit|inscri)\b/i.test(t) ||
    /\bhaven'?t\s+registered\b/i.test(t) ||
    /\bdidn'?t\s+register\b/i.test(t) ||
    /\b(don'?t|do not|dont|dono?t)\s+have\s+(an?\s+)?accounts?\b/i.test(t) ||
    /\b(no|without)\s+accounts?\b/i.test(t) ||
    /\b(i\s+)?do\s+not\s+have\s+(an?\s+)?accounts?\b/i.test(t) ||
    /\b(pas encore|pas fini|pas inscrit|pas de compte|je n['']ai pas de compte|j['']ai pas de compte|pas de compte)\b/i.test(t) ||
    /\b(je ne suis pas inscrit|pas encore inscrit|pas encore enregistr)\b/i.test(t)
  ) {
    return true;
  }
  if (
    /(مش\s*مسجل|لسه\s*مسجل|ما\s*سجلت|لم\s*أسجل|لم\s*اسجل|مش\s*عملت\s*حساب|معنديش\s*حساب|مفيش\s*حساب|لا\s*.*?حساب|مش\s*خلصت\s*التسجيل)/i.test(t)
  ) {
    return true;
  }
  return (
    /\b(still registering|trying to register|its not registering|it'?s not registering|failing to register|couldn'?t manage|in progress)\b/i.test(
      t,
    ) ||
    /\b(pas encore|je m'inscris|j['']?inscr|en cours d['']inscription)\b/i.test(t) ||
    /(لسه|لسا|مش خلصت|بحاول|جاري التسجيل|not yet registering)/i.test(t)
  );
}

export function recentTextsIndicateNotRegistered(texts: string[]): boolean {
  return texts.some((line) => isCustomerSaysNotRegisteredYet(line));
}
