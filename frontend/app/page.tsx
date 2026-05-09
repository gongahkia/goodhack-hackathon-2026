"use client";

import { useEffect, useRef, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { CalendarView } from "@/components/calendar-view";
import { useNotifications } from "@/components/notifications-provider";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { CarePlanReview, KgNode, PatientSummary } from "@/lib/types";

const CARE_REVIEW_CACHE_KEY = "caregiver-companion-care-review";

export default function DashboardPage() {
  const { t } = useI18n();
  const { notify } = useNotifications();
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [events, setEvents] = useState<KgNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const notifiedReviewId = useRef<string | null>(null);

  async function load() {
    setError(null);
    const [summary, scheduled, careReview] = await Promise.all([api.summary(), api.events(), api.carePlanReview()]);
    setPatient(summary);
    setEvents(scheduled);
    window.localStorage.setItem(CARE_REVIEW_CACHE_KEY, JSON.stringify(careReview));
    showCareBriefNotification(careReview);
    setLoading(false);
  }

  function showCareBriefNotification(careReview: CarePlanReview) {
    const id = `care-brief:${careReview.generated_at}`;
    if (notifiedReviewId.current === id || window.sessionStorage.getItem(id)) {
      return;
    }
    notifiedReviewId.current = id;
    window.sessionStorage.setItem(id, "shown");
    notify({
      id,
      title: t("careBrief.title"),
      body: careReview.narrative.slice(0, 2).join(" "),
      kind: "system",
      href: "/notifications"
    });
  }

  useEffect(() => {
    load().catch((err) => {
      setError(err.message);
      setLoading(false);
    });
  }, []);

  return (
    <>
      <AppHeader title={t("calendar.title")} />
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

        <div className="rounded-xl border border-[#dfe8e2] bg-white p-3">
          {loading ? <p className="p-6 text-center text-sm text-[#66726a]">{t("common.loadingCalendar")}</p> : <CalendarView events={events} />}
        </div>
      </section>
      <BottomNav />
    </>
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
