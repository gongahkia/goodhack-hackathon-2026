export function formatDate(value?: string, locale = "en-SG") {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function shortDate(value?: string, locale = "en-SG") {
  if (!value) return "";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

export function recordTitle(payload: Record<string, any>) {
  return payload.title || payload.content?.title || payload.record_type || "Record";
}
