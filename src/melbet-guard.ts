/**
 * This bot is the Melbet project. Registration links and promo codes from the
 * other Pager bot (1xbet) must never be sent, even if an old script still has them.
 */
const LEGACY_ONEXBET_MARKERS = [
  "1xbet",
  "1x bet",
  "bji777",
  "cmr056",
  "cash056",
  "camerun01",
  "zam577",
  "zam777",
  "zambia777",
  "egypt0011",
  "eg011",
  "cle333",
  "cle577",
  "mdg56",
  "mad778",
  "jor778",
  "jor77",
  "rund555",
  "rnd555",
  "slotsofwin",
] as const;

export function legacyOneXbetMarker(text: string): string | undefined {
  const folded = text.toLowerCase();
  if (!folded.trim()) {
    return undefined;
  }
  const compact = folded.replace(/[\s._/-]+/g, "");
  for (const marker of LEGACY_ONEXBET_MARKERS) {
    const needle = marker.replace(/[\s._/-]+/g, "");
    if (folded.includes(marker) || compact.includes(needle)) {
      return marker;
    }
  }
  return undefined;
}
