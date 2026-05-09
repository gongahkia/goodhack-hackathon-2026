"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FileSearch, ListChecks } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { ReasoningLog } from "@/lib/types";

export default function AuditPage() {
  const { t, dateLocale } = useI18n();
  const [logs, setLogs] = useState<ReasoningLog[]>([]);
  const [selected, setSelected] = useState<ReasoningLog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.audit()
      .then((items) => {
        setLogs(items);
        setSelected(items[0] || null);
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <AppHeader title={t("audit.title")} subtitle={t("audit.subtitle")} />
      <section className="flex-1 space-y-3 px-4 pb-4">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <div className="flex gap-2 overflow-x-auto pb-1">
          {logs.map((log) => (
            <button
              className={`shrink-0 rounded-lg border px-3 py-2 text-left text-xs ${selected?.id === log.id ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] bg-white text-[#536159]"}`}
              key={log.id}
              onClick={() => setSelected(log)}
            >
              <span className="block font-bold">{log.trigger.split(":")[0]}</span>
              <span>{formatDate(log.created_at, dateLocale)}</span>
            </button>
          ))}
        </div>
        {!selected ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("audit.empty")}</p> : null}
        {selected ? (
          <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
            <ToolEvidencePanel log={selected} />
            <p className="text-xs font-bold uppercase text-moss">{t("audit.conclusion")}</p>
            <p className="mt-2 text-sm text-[#34423a]">{selected.conclusion || "No conclusion recorded."}</p>
            <div className="mt-5 space-y-3 border-l-2 border-mint pl-4">
              {selected.steps.map((step, index) => (
                <div className="relative rounded-lg border border-[#e4ebe6] bg-[#fbfdfb] p-3" key={`${selected.id}-${index}`}>
                  <span className="absolute -left-[23px] top-4 h-3 w-3 rounded-full border-2 border-moss bg-white" />
                  <p className="text-xs font-bold uppercase text-[#66726a]">{step.kind || "step"}</p>
                  {step.text ? <p className="mt-1 text-sm">{step.text}</p> : null}
                  {step.tool ? <p className="mt-1 text-sm font-semibold">{step.tool}</p> : null}
                  {step.input ? <pre className="mt-2 overflow-auto rounded bg-[#eef3ef] p-2 text-xs">{JSON.stringify(step.input, null, 2)}</pre> : null}
                  {step.result ? <pre className="mt-2 max-h-48 overflow-auto rounded bg-[#eef3ef] p-2 text-xs">{JSON.stringify(step.result, null, 2)}</pre> : null}
                  {step.message ? <p className="mt-1 text-sm text-[#8d3d29]">{step.message}</p> : null}
                </div>
              ))}
            </div>
          </article>
        ) : null}
      </section>
      <BottomNav />
    </>
  );
}

const externalToolNames = new Set([
  "exa_search",
  "tinyfish_search",
  "tinyfish_fetch",
  "jina_read_url",
  "jina_rerank",
  "openalex_search",
  "semantic_scholar_search",
  "sealion_regional_review",
  "sealion_guard_check",
  "web_search"
]);

type ToolEvidence = {
  tool: string;
  provider?: string;
  configured?: boolean;
  count: number;
  rows: Array<{ title: string; source?: string; url?: string; snippet?: string; score?: string }>;
};

function ToolEvidencePanel({ log }: { log: ReasoningLog }) {
  const { t } = useI18n();
  const evidence = toolEvidence(log);
  if (evidence.length === 0) {
    return null;
  }
  return (
    <section className="mb-5 rounded-lg border border-[#dfe8e2] bg-[#fbfdfb] p-3">
      <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
        <FileSearch className="h-4 w-4 text-moss" /> {t("audit.toolEvidence")}
      </p>
      <p className="mt-1 text-xs text-[#66726a]">{t("audit.toolEvidenceDescription")}</p>
      <div className="mt-3 grid gap-2">
        {evidence.map((item, index) => (
          <article className="rounded-lg border border-[#dfe8e2] bg-white p-3" key={`${item.tool}-${index}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
                  <ListChecks className="h-4 w-4 text-moss" /> {item.provider || item.tool}
                </p>
                <p className="mt-0.5 text-xs text-[#66726a]">
                  {item.tool} · {item.count} {t("audit.toolResults")} · {item.configured === false ? t("audit.notConfigured") : t("audit.configured")}
                </p>
              </div>
            </div>
            {item.rows.length > 0 ? (
              <div className="mt-3 grid gap-2">
                {item.rows.slice(0, 4).map((row, rowIndex) => (
                  <div className="rounded-lg bg-[#f5f8f6] p-3" key={`${row.title}-${rowIndex}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-ink">{row.title}</p>
                        <p className="mt-0.5 text-xs text-[#66726a]">{[row.source, row.score].filter(Boolean).join(" · ")}</p>
                      </div>
                      {row.url ? (
                        <a className="shrink-0 rounded-lg p-2 text-moss hover:bg-mint" href={row.url} target="_blank" rel="noreferrer" aria-label={t("common.openResource")}>
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      ) : null}
                    </div>
                    {row.snippet ? <p className="mt-2 line-clamp-3 text-sm text-[#34423a]">{row.snippet}</p> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function toolEvidence(log: ReasoningLog): ToolEvidence[] {
  return log.steps
    .filter((step) => step.kind === "tool_result" && externalToolNames.has(String(step.tool || "")))
    .map((step) => {
      const result = step.result || {};
      const rows = normalizeToolRows(result);
      return {
        tool: String(step.tool || "tool"),
        provider: typeof result.provider === "string" ? result.provider : undefined,
        configured: typeof result.configured === "boolean" ? result.configured : undefined,
        count: Array.isArray(result.results) ? result.results.length : rows.length,
        rows
      };
    });
}

function normalizeToolRows(result: Record<string, any>): ToolEvidence["rows"] {
  if (Array.isArray(result.results)) {
    return result.results.map((item: Record<string, any>) => normalizeToolRow(item));
  }
  if (Array.isArray(result)) {
    return result.map((item: Record<string, any>) => normalizeToolRow(item));
  }
  if (typeof result.result === "string") {
    return [{ title: "Model review", snippet: result.result }];
  }
  if (typeof result.text === "string") {
    return [{ title: result.url || result.provider || "Fetched text", url: result.url, snippet: result.text }];
  }
  return [];
}

function normalizeToolRow(item: Record<string, any>): ToolEvidence["rows"][number] {
  const source = typeof item.source === "object" && item.source ? item.source : {};
  const document = typeof item.document === "object" && item.document ? item.document : {};
  const title = item.title || document.title || source.title || item.paper_id || item.url || "Evidence result";
  const snippet = item.snippet || item.abstract || item.tldr || document.snippet || document.text || item.text;
  const sourceLabel = typeof item.source === "string" ? item.source : item.source_name || source.source || source.url || item.provider || item.venue;
  const score =
    typeof item.relevance_score === "number"
      ? `score ${item.relevance_score.toFixed(2)}`
      : typeof item.citation_count === "number"
        ? `${item.citation_count} citations`
        : undefined;
  return {
    title: String(title),
    source: sourceLabel ? String(sourceLabel) : undefined,
    url: item.url || item.pdf_url || document.url || source.url,
    snippet: typeof snippet === "string" ? snippet : undefined,
    score
  };
}
