import type { ProofKind } from "./config.js";

export function looksLikeZmDepositBalanceScreenshot(combinedText: string): boolean {
  const blob = (combinedText || "").trim();
  if (!blob) {
    return false;
  }
  const lower = blob.toLowerCase();
  const hasBalance =
    /\b\d+\s*zmw\b/i.test(blob) ||
    /\bk\s?\d{1,4}\b/i.test(blob) ||
    /\b(zmw|kwacha)\b/i.test(lower);
  const hasApp =
    /1xbet|xbet|make a deposit|withdraw funds|personal profile|my bets/i.test(blob);
  return hasBalance && hasApp;
}

export function resolveZmProofScriptAfterDeposit(
  proofKind: ProofKind | undefined,
  combinedText: string,
  options: { depositScriptSent: boolean; gameIdScriptSent: boolean },
): "07_game_id" | null {
  if (!options.depositScriptSent || options.gameIdScriptSent) {
    return null;
  }
  const depositProof =
    proofKind === "deposit_balance_screenshot" ||
    looksLikeZmDepositBalanceScreenshot(combinedText);
  if (!depositProof) {
    return null;
  }
  return "07_game_id";
}
