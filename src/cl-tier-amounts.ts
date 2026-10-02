/**
 * Chile 04_tier: deposit levels 500 / 800 / 1000 / 1500 XAF → CLP at ~1.65 CLP/XAF.
 * Profit XAF follows CM-style 140× on deposit (1000→140k, 1500→190k); 500→70k, 800→112k.
 * Profit CLP = profit XAF × 16_500 / 140_000 (anchor 1000/140k → 1650/16500 CLP).
 */
export const CLP_PER_XAF = 1.65;

export const CM_DEPOSIT_TIER_CFA = [500, 800, 1000, 1500] as const;
export const CM_PROFIT_TIER_CFA = [70_000, 112_000, 140_000, 190_000] as const;

function roundDepositClp(cfa: number): number {
  if (cfa === 500) return 825;
  if (cfa === 800) return 1320;
  if (cfa === 1000) return 1650;
  if (cfa === 1500) return 2500;
  return Math.round((cfa * CLP_PER_XAF) / 10) * 10;
}

function roundProfitClp(profitCfa: number): number {
  if (profitCfa === 70_000) return 8250;
  if (profitCfa === 112_000) return 13_200;
  if (profitCfa === 140_000) return 16_500;
  if (profitCfa === 190_000) return 22_400;
  const raw = (profitCfa / 140_000) * 16_500;
  return Math.round(raw / 50) * 50;
}

export const CL_DEPOSIT_TIER_CLP: readonly [number, number, number, number] = [
  roundDepositClp(CM_DEPOSIT_TIER_CFA[0]),
  roundDepositClp(CM_DEPOSIT_TIER_CFA[1]),
  roundDepositClp(CM_DEPOSIT_TIER_CFA[2]),
  roundDepositClp(CM_DEPOSIT_TIER_CFA[3]),
];

export const CL_PROFIT_TIER_CLP: readonly [number, number, number, number] = [
  roundProfitClp(CM_PROFIT_TIER_CFA[0]),
  roundProfitClp(CM_PROFIT_TIER_CFA[1]),
  roundProfitClp(CM_PROFIT_TIER_CFA[2]),
  roundProfitClp(CM_PROFIT_TIER_CFA[3]),
];

export type ClTierIndex = 0 | 1 | 2 | 3;

export function clDepositClpForCmTier(index: ClTierIndex): number {
  return CL_DEPOSIT_TIER_CLP[index];
}

export function clProfitClpForTier(index: ClTierIndex): number {
  return CL_PROFIT_TIER_CLP[index];
}

export function clTierDepositAmountNeedles(): string[] {
  const out = new Set<string>();
  for (const cfa of CM_DEPOSIT_TIER_CFA) {
    out.add(String(cfa));
  }
  for (const clp of CL_DEPOSIT_TIER_CLP) {
    out.add(String(clp));
  }
  return [...out];
}
