"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, ExternalLink, FileCheck, Files, Gauge, HeartHandshake, Home, Landmark, SearchCheck, Wrench } from "lucide-react";
import { clsx } from "clsx";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { ForecastItem } from "@/lib/types";

const filters = ["all", "grant", "equipment", "care_service", "home_modification"] as const;

export default function ForecastPage() {
  const { t, dateLocale } = useI18n();
  const [items, setItems] = useState<ForecastItem[]>([]);
  const [activeFilter, setActiveFilter] = useState<(typeof filters)[number]>("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .forecast()
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const visible = useMemo(
    () => items.filter((item) => activeFilter === "all" || item.category === activeFilter),
    [activeFilter, items]
  );

  return (
    <>
      <AppHeader title={t("forecast.title")} />
      <section className="flex-1 space-y-4 px-4 pb-28">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <div className="flex gap-2 overflow-x-auto pb-1">
          {filters.map((filter) => (
            <button
              aria-pressed={activeFilter === filter}
              className={clsx(
                "min-h-10 shrink-0 rounded-full border px-4 text-sm font-bold",
                activeFilter === filter ? "border-moss bg-moss text-white" : "border-[#cbd8cf] bg-white text-[#536159]"
              )}
              key={filter}
              onClick={() => setActiveFilter(filter)}
              type="button"
            >
              {t(`forecast.${filter}`)}
            </button>
          ))}
        </div>
        {visible.length === 0 ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("forecast.empty")}</p> : null}
        <div className="space-y-3">
          {visible.map((item) => (
            <ForecastCard item={item} locale={dateLocale} key={item.id} />
          ))}
        </div>
      </section>
      <BottomNav />
    </>
  );
}

function ForecastCard({ item, locale }: { item: ForecastItem; locale: string }) {
  const { t } = useI18n();
  const Icon = categoryIcon(item.category);
  return (
    <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-2 text-xs font-bold uppercase text-moss">
            <Icon className="h-4 w-4" /> {t(`forecast.${item.category}`)}
          </p>
          <h2 className="mt-2 text-lg font-bold text-ink">{item.title}</h2>
          <p className="mt-1 text-sm text-[#66726a]">{formatDate(item.target_date || undefined, locale)}</p>
        </div>
        <StatusBadge status={item.status} />
      </div>
      {item.summary ? <p className="mt-3 text-sm text-[#34423a]">{item.summary}</p> : null}
      {item.agency ? <p className="mt-2 text-sm font-semibold text-moss">{item.agency}</p> : null}
      <div className="mt-4 grid gap-2">
        <InsightRow icon={Files} title={t("forecast.documents")} items={item.missing_documents} empty={t("forecast.noMissingDocuments")} />
        <InsightRow icon={AlertTriangle} title={t("forecast.deadlines")} items={item.deadline_conflicts} empty={t("forecast.noDeadlineConflicts")} />
        <div className="rounded-lg border border-[#dfe8e2] bg-[#fbfdfb] p-3">
          <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
            <Gauge className="h-4 w-4 text-moss" /> {t("forecast.capacity")}
          </p>
          <p className="mt-1 text-sm text-[#34423a]">
            {t("forecast.capacitySummary")
              .replace("{count}", String(item.capacity?.weekly_action_count ?? 0))
              .replace("{risk}", item.capacity?.risk || "low")}
          </p>
          {item.capacity?.note ? <p className="mt-1 text-xs text-[#66726a]">{item.capacity.note}</p> : null}
          {item.capacity?.rest_conflicts?.length ? (
            <ul className="mt-2 space-y-1 text-xs font-semibold text-[#8d3d29]">
              {item.capacity.rest_conflicts.map((conflict) => (
                <li key={conflict}>{conflict}</li>
              ))}
            </ul>
          ) : null}
          {item.capacity?.suggested_windows?.length ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {item.capacity.suggested_windows.slice(0, 3).map((window) => (
                <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-moss" key={`${window.label}-${window.start}-${window.end}`}>
                  {window.label}: {window.start}-{window.end}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className="mt-4 rounded-lg border border-[#dfe8e2] bg-[#f5f8f6] p-3">
        <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
          <FileCheck className="h-4 w-4 text-moss" /> {t("forecast.timeline")}
        </p>
        <div className="mt-3 space-y-3">
          {item.timeline.map((step) => (
            <div className="grid grid-cols-[7rem_1fr] gap-3 text-sm" key={`${item.id}-${step.label}`}>
              <p className="font-bold text-moss">{step.label}</p>
              <p className="text-[#34423a]">{step.detail}</p>
            </div>
          ))}
        </div>
      </div>
      {item.evidence.length > 0 ? (
        <div className="mt-3">
          <p className="text-xs font-bold uppercase text-moss">{t("forecast.evidence")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {item.evidence.map((evidence) => (
              <span className="rounded-full bg-mint px-3 py-1.5 text-xs font-semibold text-moss" key={evidence.id}>
                {evidence.title || evidence.type}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {item.research_sources?.length ? <ResearchSourcesPanel sources={item.research_sources} /> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss" href={`/event/${item.id}`}>
          {t("forecast.openAction")} <ArrowRight className="h-4 w-4" />
        </Link>
        {item.apply_url ? (
          <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white" href={item.apply_url} target="_blank" rel="noreferrer">
            {t("forecast.apply")} <ExternalLink className="h-4 w-4" />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function ResearchSourcesPanel({
  sources
}: {
  sources: NonNullable<ForecastItem["research_sources"]>;
}) {
  const { t } = useI18n();
  return (
    <div className="mt-4 rounded-lg border border-[#dfe8e2] bg-[#fbfdfb] p-3">
      <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
        <SearchCheck className="h-4 w-4 text-moss" /> {t("forecast.researchSources")}
      </p>
      <p className="mt-1 text-xs text-[#66726a]">{t("forecast.researchSourcesDescription")}</p>
      <div className="mt-3 grid gap-2">
        {sources.slice(0, 4).map((source, index) => (
          <article className="rounded-lg border border-[#dfe8e2] bg-white p-3" key={`${source.url || source.title || "source"}-${index}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-bold text-ink">{source.title || source.source || t("forecast.researchSource")}</p>
                <p className="mt-0.5 text-xs text-[#66726a]">{source.source || source.verification_status || t("common.noneYet")}</p>
              </div>
              {source.url ? (
                <a className="shrink-0 rounded-lg p-2 text-moss hover:bg-mint" href={source.url} target="_blank" rel="noreferrer" aria-label={t("common.openResource")}>
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
            </div>
            {source.snippet ? <p className="mt-2 line-clamp-3 text-sm text-[#34423a]">{source.snippet}</p> : null}
            {source.retrieved_at ? <p className="mt-2 text-xs text-[#66726a]">{source.retrieved_at}</p> : null}
          </article>
        ))}
      </div>
    </div>
  );
}

function InsightRow({
  icon: Icon,
  title,
  items,
  empty
}: {
  icon: typeof Files;
  title: string;
  items: string[];
  empty: string;
}) {
  return (
    <div className="rounded-lg border border-[#dfe8e2] bg-[#fbfdfb] p-3">
      <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
        <Icon className="h-4 w-4 text-moss" /> {title}
      </p>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm text-[#34423a]">
          {items.slice(0, 4).map((item) => (
            <li className="flex gap-2" key={item}>
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-moss" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-[#66726a]">{empty}</p>
      )}
    </div>
  );
}

function categoryIcon(category: string) {
  if (category === "grant") {
    return Landmark;
  }
  if (category === "equipment") {
    return Wrench;
  }
  if (category === "home_modification") {
    return Home;
  }
  return HeartHandshake;
}
