import tesseract from "tesseract.js";
import type { PlaybookConfig, CountryCode, ProofKind } from "./config.js";
import { extractCmClientLoginId17, isCmRegistrationSuccessProof, resolveCmProofScriptAction, type CmProofScriptAction } from "./cm-proof.js";

const { recognize } = tesseract;

export type ProofClassification = {
  proofKind: ProofKind;
  combinedText: string;
  reason: string;
};

export async function classifyProofFromImage(
  playbook: PlaybookConfig,
  image: Buffer,
  options?: {
    caption?: string;
    ocrEnabled?: boolean;
    ocrLang?: string;
    country?: CountryCode;
  },
): Promise<ProofClassification> {
  const ocrText =
    options?.ocrEnabled === false
      ? ""
      : (
          await recognize(image, options?.ocrLang ?? "eng", {
            logger: () => undefined,
          })
        ).data.text;

  return classifyProofFromText(playbook, [options?.caption ?? "", ocrText].join("\n"), options?.country);
}

export function classifyProofFromText(
  playbook: PlaybookConfig,
  inputText: string,
  country?: CountryCode,
): ProofClassification {
  const normalized = normalize(inputText);

  if (!normalized) {
    return {
      proofKind: "unclear_screenshot",
      combinedText: inputText,
      reason: "No OCR or caption text available",
    };
  }

  const hasRegistrationUiMarker =
    playbook.registrationKeywords.some((keyword) => normalized.includes(normalize(keyword))) ||
    /(inscription|1xbet|xbet|melbet|betwinner|paris sportifs|cr[eé]er un compte|cree un compte|t[eé]l[eé]charger|telecharger|installer|apk|promo|code promo|limite d.?age|phone number|num[eé]ro de t[eé]l[eé]phone|cameroun|cash056|eg011|egypt0011)/i.test(
      inputText,
    ) ||
    /(تسجيل|حساب|انشاء|إنشاء|1xbet|xbet|تحميل|تطبيق|رابط|promo|كود)/i.test(inputText);

  const hasIdMarker =
    hasRegistrationUiMarker ||
    /(id|client|account|uid|رقم|عميل|identifiant|compte|joueur|player|profil|profile|mon compte)/i.test(
      inputText,
    );

  const hasLongDigits = /\b\d{5,}\b/.test(inputText);
  const login17 = country === "CM" ? extractCmClientLoginId17(inputText) : undefined;
  const hasClientGameId =
    country === "CM"
      ? Boolean(login17)
      : /\b(17\d{6,}|16\d{6,})\b/.test(inputText);

  if (country === "CM" && login17 && isCmRegistrationSuccessProof(inputText)) {
    return {
      proofKind: "registration_screenshot",
      combinedText: inputText,
      reason: `CM inscription réussie login ${login17}`,
    };
  }

  if (country === "CM" && login17 && /inscription|r[eé]ussie|successful|login\s*:/i.test(inputText)) {
    return {
      proofKind: "registration_screenshot",
      combinedText: inputText,
      reason: `CM registration login ${login17}`,
    };
  }

  if (hasClientGameId && (hasIdMarker || hasLongDigits) && country !== "CM") {
    return {
      proofKind: "id_screenshot",
      combinedText: inputText,
      reason: "Detected ZM game/account id starting with 16/17",
    };
  }

  if (hasClientGameId && (hasIdMarker || hasLongDigits) && country === "CM" && login17) {
    return {
      proofKind: "id_screenshot",
      combinedText: inputText,
      reason: `CM client login id ${login17}`,
    };
  }

  const hasDepositMarker =
    playbook.depositKeywords.some((keyword) => normalized.includes(normalize(keyword))) ||
    /(balance|deposit|funded|egp|usd|zar|ksh|kes|fcfa|zmw|kwacha|رصيد|ايداع|إيداع|solde|recharger|retrait)/i.test(
      inputText,
    ) ||
    (country === "CM" && /\b\d{2,5}\s*F\b/i.test(inputText) && /(1xbet|xbet)/i.test(inputText));

  if (hasDepositMarker) {
    return {
      proofKind: "deposit_balance_screenshot",
      combinedText: inputText,
      reason: "Detected balance or deposit markers",
    };
  }

  if (hasIdMarker && hasLongDigits) {
    return {
      proofKind: "id_screenshot",
      combinedText: inputText,
      reason: "Detected account or client identifier markers",
    };
  }

  if (hasIdMarker || hasLongDigits || hasRegistrationUiMarker) {
    return {
      proofKind: "registration_screenshot",
      combinedText: inputText,
      reason: "Detected registration-like account details",
    };
  }

  return {
    proofKind: "unclear_screenshot",
    combinedText: inputText,
    reason: "Could not confidently classify screenshot",
  };
}

/** Re-classify OCR/AI text and pick CM deposit or game-id script (Login IDs starting with 17 only). */
export function resolveCmProofScriptFromCombinedText(
  playbook: PlaybookConfig,
  combinedText: string,
  outgoingTexts: string[],
): CmProofScriptAction | undefined {
  const classification = classifyProofFromText(playbook, combinedText, "CM");
  return resolveCmProofScriptAction(
    classification.proofKind,
    classification.combinedText,
    outgoingTexts,
  );
}

function normalize(value?: string): string {
  return value?.toLowerCase().trim() ?? "";
}
