import type { Lang } from "./api";

export function formatDate(value: string, lang: Lang): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(value);
  if (!match) return value;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (date.getUTCFullYear() !== Number(match[1]) || date.getUTCMonth() !== Number(match[2]) - 1 || date.getUTCDate() !== Number(match[3])) return value;
  return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", {
    year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
  }).format(date);
}

const months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
const spanishMonths = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
function fromParts(year: string, month: number, day: string, lang: Lang) {
  return formatDate(`${year}-${String(month + 1).padStart(2, "0")}-${day.padStart(2, "0")}`, lang);
}

/** Localize dates within API prose without changing source data or request values. */
export function formatDatesInText(text: string, lang: Lang): string {
  return text
    .replace(/\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)?\b/g, value => formatDate(value, lang))
    .replace(/\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b/gi,
      (_, month: string, day: string, year: string) => fromParts(year, months.findIndex(m => m.startsWith(month.toLowerCase().replace(/\.$/, ""))), day, lang))
    .replace(/\b(\d{1,2}) de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre) de (\d{4})\b/gi,
      (_, day: string, month: string, year: string) => fromParts(year, spanishMonths.indexOf(month.toLowerCase()), day, lang));
}