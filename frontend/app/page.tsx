"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { CalendarView } from "@/components/calendar-view";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { CarePlanReview, KgNode, PatientSummary } from "@/lib/types";

const CARE_REVIEW_CACHE_KEY = "caregiver-companion-care-review";

export default function DashboardPage() {
  const { t } = useI18n();
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [events, setEvents] = useState<KgNode[]>([]);
  const [review, setReview] = useState<CarePlanReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const cached = readCachedReview();
    if (cached) {
      setReview(cached);
    }
    const [summary, scheduled, careReview] = await Promise.all([api.summary(), api.events(), api.carePlanReview()]);
    setPatient(summary);
    setEvents(scheduled);
    setReview(careReview);
    window.localStorage.setItem(CARE_REVIEW_CACHE_KEY, JSON.stringify(careReview));
    setLoading(false);
  }

  useEffect(() => {
    load().catch((err) => {
      setError(err.message);
      setLoading(false);
    });
  }, []);

  return (
    <>
      <AppHeader title={t("calendar.title")} subtitle={t("calendar.subtitle")} />
      <section className="flex-1 space-y-4 px-4 pb-28">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <div className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm text-[#66726a]">{t("common.patient")}</p>
              <h2 className="text-xl font-bold">{patient?.name || "Mdm Tan Siew Lan"}</h2>
              <p className="mt-1 text-sm text-[#66726a]">
                {patient?.age || 78} {t("common.yearsOld")} · {patient?.citizenship || "Singapore Citizen"}
              </p>
            </div>
            <StatusBadge status="approved" />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(patient?.key_conditions || ["Hypertension"]).map((condition) => (
              <span className="rounded-full bg-mint px-2.5 py-1 text-xs font-semibold text-moss" key={condition}>
                {condition}
              </span>
            ))}
          </div>
          <p className="mt-3 text-sm text-[#536159]">{patient?.living_arrangement || "Lives with daughter in Toa Payoh"}</p>
        </div>

        {review ? <CareBrief review={review} /> : null}

        <div className="rounded-xl border border-[#dfe8e2] bg-white p-3">
          {loading ? <p className="p-6 text-center text-sm text-[#66726a]">{t("common.loadingCalendar")}</p> : <CalendarView events={events} />}
        </div>
      </section>
      <BottomNav />
    </>
  );
}

function CareBrief({ review }: { review: CarePlanReview }) {
  const { t, dateLocale } = useI18n();
  return (
    <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase text-moss">{t("careBrief.eyebrow")}</p>
          <h2 className="mt-1 text-lg font-bold text-ink">{t("careBrief.title")}</h2>
        </div>
        <span className="rounded-full bg-mint px-2.5 py-1 text-xs font-bold text-moss">{review.pending_review_count}</span>
      </div>
      <div className="mt-3 space-y-2">
        {review.narrative.slice(0, 3).map((line, index) => (
          <p className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm text-[#34423a]" key={index}>
            {line}
          </p>
        ))}
      </div>
      {review.next_actions.length > 0 ? (
        <div className="mt-3 space-y-2">
          {review.next_actions.slice(0, 2).map((action) => (
            <a className="flex items-center justify-between gap-3 rounded-lg border border-[#dfe8e2] px-3 py-2" href={`/event/${action.id}`} key={action.id}>
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-ink">{action.title}</span>
                <span className="text-xs text-[#66726a]">{formatDate(action.start_at, dateLocale)}</span>
              </span>
              <span className="text-lg text-moss" aria-hidden="true">
                ›
              </span>
            </a>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function readCachedReview() {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const stored = window.localStorage.getItem(CARE_REVIEW_CACHE_KEY);
    return stored ? (JSON.parse(stored) as CarePlanReview) : null;
  } catch {
    return null;
  }
}
