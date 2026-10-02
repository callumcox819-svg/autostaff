export type CustomDepositRules = {
  min: number;
  max: number;
  currencyPattern: RegExp;
  depositIntentPattern: RegExp;
  /** Bare number picks below this need currency or deposit-intent words. */
  bareMin?: number;
};

export function normalizeDepositText(text: string): string {
  return (text || "")
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['']/g, "'");
}

function parseCompactAmount(raw: string): number | null {
  const digitsOnly = raw.replace(/[^\d]/g, "");
  if (!digitsOnly || digitsOnly.length > 6) {
    return null;
  }
  if (/^17\d{6,}$/.test(digitsOnly)) {
    return null;
  }
  const amount = Number(digitsOnly);
  return Number.isFinite(amount) ? amount : null;
}

function amountInRange(amount: number, rules: CustomDepositRules): boolean {
  return amount >= rules.min && amount <= rules.max;
}

/** Custom deposit amount not in tier table — must look like a real money pick, not random digits. */
export function isCustomMarketDepositAmount(text: string, rules: CustomDepositRules): boolean {
  const t = normalizeDepositText(text);
  if (!t || t.length > 120) {
    return false;
  }
  if (/\b(17\d{6,}|otp|verification code|whatsapp|phone number|game id)\b/i.test(t)) {
    return false;
  }
  if (/\b(j'ai|jai|ai)\s*\d{1,2}\s*an[s]?\b/i.test(t)) {
    return false;
  }
  if (/\b\d{1,2}\s*an[s]?\b/i.test(t) && !rules.currencyPattern.test(t)) {
    return false;
  }
  if (/^202[4-9]$|^203[0-9]$/.test(t.replace(/\s+/g, ""))) {
    return false;
  }

  const hasCurrency = rules.currencyPattern.test(t);
  const hasIntent = rules.depositIntentPattern.test(t);
  const compact = t.replace(/\s+/g, "");
  const wordCount = t.split(/\s+/).filter(Boolean).length;
  const bareMin = rules.bareMin ?? rules.min;

  const bareAmountMatch = compact.match(
    /^(\d{1,3}(?:[.,]\d{3})*|\d+)(?:zmw|kwacha|k|clp|pesos?|cfa|frs?|f|fc|mga|ariary|ar)?\.?$/i,
  );
  if (bareAmountMatch) {
    const amount = parseCompactAmount(compact);
    if (amount === null || !amountInRange(amount, rules)) {
      return false;
    }
    if (!hasCurrency && !hasIntent) {
      if (amount < bareMin) {
        return false;
      }
      if (wordCount > 6) {
        return false;
      }
    }
    return true;
  }

  if (wordCount <= 14 && (hasIntent || hasCurrency) && /\d/.test(t)) {
    const match = t.match(
      /\b(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(?:zmw|kwacha|k|clp|pesos?|cfa|frs?|f|fc|mga|ariary|ar)?\b|(?:^|[^\d])(\d{3,6})(?:mga|ariary|ar)\b/i,
    );
    if (match) {
      const rawAmount = (match[1] || match[2] || "").replace(/[^\d]/g, "");
      const amount = parseCompactAmount(rawAmount);
      if (amount !== null && amountInRange(amount, rules)) {
        return true;
      }
    }
  }

  return false;
}

export const ZM_CUSTOM_DEPOSIT_RULES: CustomDepositRules = {
  min: 15,
  max: 5_000,
  bareMin: 30,
  currencyPattern: /\b(zmw|kwacha|\bk\b)\b/i,
  depositIntentPattern:
    /\b(deposit|depot|start with|begin with|invest|put in|with|can i start|want to start|ready to start|mets|mettre|investir|avec|pour)\b/i,
};

export const CL_CUSTOM_DEPOSIT_RULES: CustomDepositRules = {
  min: 200,
  max: 50_000,
  bareMin: 200,
  currencyPattern: /\b(clp|pesos?|\$)\b/i,
  depositIntentPattern:
    /\b(deposit|depot|depósito|start with|begin with|invest|put in|with|can i start|want to start|ready to start|mets|mettre|investir|invertir|con|para|pour|elijo|escojo)\b/i,
};
