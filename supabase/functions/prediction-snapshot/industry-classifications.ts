import type { MarketScope } from "./types.ts";

// Exchange industry codes are presentation metadata only. They must never be
// substituted for the point-in-time industry used by the model.
const COMMON_INDUSTRIES: Readonly<Record<string, string>> = Object.freeze({
  "01": "水泥工業",
  "02": "食品工業",
  "03": "塑膠工業",
  "04": "紡織纖維",
  "05": "電機機械",
  "06": "電器電纜",
  "08": "玻璃陶瓷",
  "09": "造紙工業",
  "10": "鋼鐵工業",
  "11": "橡膠工業",
  "12": "汽車工業",
  "14": "建材營造",
  "15": "航運業",
  "16": "觀光餐旅",
  "17": "金融保險",
  "18": "貿易百貨",
  "19": "綜合",
  "20": "其他",
  "21": "化學工業",
  "22": "生技醫療業",
  "23": "油電燃氣業",
  "24": "半導體業",
  "25": "電腦及週邊設備業",
  "26": "光電業",
  "27": "通信網路業",
  "28": "電子零組件業",
  "29": "電子通路業",
  "30": "資訊服務業",
  "31": "其他電子業",
  "35": "綠能環保",
  "36": "數位雲端",
  "37": "運動休閒",
  "38": "居家生活",
});

const TPEX_INDUSTRY_OVERRIDES: Readonly<Record<string, string>> = Object.freeze(
  {
    "17": "金融業",
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務",
    "80": "管理股票",
  },
);

export const CURRENT_INDUSTRY_CLASSIFICATION_BASIS =
  "TW_EXCHANGE_LATEST_SECURITY_SNAPSHOT_2026_V1";

export function resolveCurrentIndustryName(
  market: MarketScope,
  industryCode: string | null,
  storedName: string | null,
): string | null {
  const normalizedName = storedName?.trim();
  if (normalizedName) return normalizedName;
  const normalizedCode = industryCode?.trim().padStart(2, "0");
  if (!normalizedCode) return null;
  return market === "TPEX"
    ? TPEX_INDUSTRY_OVERRIDES[normalizedCode] ??
      COMMON_INDUSTRIES[normalizedCode] ?? null
    : COMMON_INDUSTRIES[normalizedCode] ?? null;
}
