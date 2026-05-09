"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ExternalLink, FileCheck, HeartHandshake, Home, Landmark, Wrench } from "lucide-react";
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
      <AppHeader title={t("forecast.title")} subtitle={t("forecast.subtitle")} />
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
