/**
 * jp-phone-opendata lookup API.
 *
 * GET /lookup?number=<any format>
 *   -> { number, type, verdict, carrier, region, name, label }
 *
 * `carrier` comes from MIC (Soumu) open-data number allocation.
 * `verdict` is "legit" for a known allocation, "unknown" otherwise.
 * "spam" is reserved for a future crowd-sourced list.
 *
 * Consumed by the FOSS Android app SpamBlocker via its Query API workflow
 * (see ../../spamblocker/query_api.json).
 */

export interface Env {
  DB: D1Database;
}

const TYPE_LABEL: Record<string, string> = {
  mobile: "携帯",
  ip: "IP電話",
  freedial: "フリーダイヤル",
  navi: "ナビダイヤル",
  intl: "国際",
  fixed: "固定電話",
  unknown: "不明",
};

/** Reduce any input to domestic digits (drop +, spaces, hyphens; +81 -> 0). */
function normalize(raw: string): string {
  let d = (raw || "").replace(/[^\d]/g, "");
  if (d.startsWith("81") && d.length >= 11) d = "0" + d.slice(2);
  return d;
}

function classify(d: string): string {
  if (d.startsWith("0120") || d.startsWith("0800")) return "freedial";
  if (d.startsWith("0570")) return "navi";
  if (d.startsWith("050")) return "ip";
  if (/^0[6789]0/.test(d)) return "mobile";
  if (d.startsWith("010") || d.startsWith("00")) return "intl";
  if (d.startsWith("0")) return "fixed";
  return "unknown";
}

async function carrierOf(db: D1Database, d: string): Promise<string | null> {
  const p6 = d.slice(0, 6);
  const p7 = d.slice(0, 7);
  const { results } = await db
    .prepare("SELECT prefix, carrier FROM prefixes WHERE prefix IN (?1, ?2)")
    .bind(p7, p6)
    .all<{ prefix: string; carrier: string }>();
  if (!results?.length) return null;
  // longest prefix wins
  results.sort((a, b) => b.prefix.length - a.prefix.length);
  return results[0].carrier;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== "/lookup") {
      return new Response("jp-phone-opendata: GET /lookup?number=...", {
        status: url.pathname === "/" ? 200 : 404,
      });
    }

    const raw = url.searchParams.get("number") ?? "";
    const d = normalize(raw);
    const type = classify(d);
    const carrier = type === "mobile" || type === "ip"
      ? await carrierOf(env.DB, d)
      : null;

    const verdict = carrier ? "legit" : "unknown";
    const label = carrier ? `${TYPE_LABEL[type]} / ${carrier}` : TYPE_LABEL[type];

    const body = JSON.stringify({
      number: d,
      type,
      verdict,
      carrier,
      region: null, // TODO: fixed-line area-code -> region
      name: null,   // TODO: business name from 推奨データセット / Wikidata
      label,
    });

    return new Response(body, {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "public, max-age=86400",
      },
    });
  },
};
