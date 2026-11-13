/** ISO 3166-1 alpha-2 codes offered in the sign-up form. Labels come from Intl.DisplayNames. */
export const COUNTRY_CODES = (
  "AD AE AF AG AL AM AO AR AT AU AZ BA BB BD BE BF BG BH BI BJ BN BO BR BS BT BW BY BZ CA CD CF CG CH CI CL CM CN CO CR CU CV CY CZ " +
  "DE DJ DK DM DO DZ EC EE EG ER ES ET FI FJ FR GA GB GD GE GH GM GN GQ GR GT GW GY HK HN HR HT HU ID IE IL IN IQ IR IS IT JM JO JP " +
  "KE KG KH KI KM KN KR KW KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MK ML MM MN MO MR MT MU MV MW MX MY MZ NA NE NG NI NL " +
  "NO NP NZ OM PA PE PG PH PK PL PR PT PY QA RO RS RU RW SA SB SC SD SE SG SI SK SL SM SN SO SR SS ST SV SY SZ TD TG TH TJ TL TM TN " +
  "TO TR TT TW TZ UA UG US UY UZ VC VE VN VU WS YE ZA ZM ZW"
).split(" ");

export function countryOptions(locale: string): { code: string; label: string }[] {
  const names = new Intl.DisplayNames([locale], { type: "region" });
  return COUNTRY_CODES.map((code) => ({ code, label: names.of(code) ?? code })).sort((a, b) =>
    a.label.localeCompare(b.label, locale),
  );
}

export function countryName(code: string | null | undefined, locale = "en"): string {
  if (!code) return "—";
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}
