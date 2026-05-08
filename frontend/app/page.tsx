"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { CalendarView } from "@/components/calendar-view";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { KgNode, PatientSummary } from "@/lib/types";

export default function DashboardPage() {
  const { t } = useI18n();
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [events, setEvents] = useState<KgNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const [summary, scheduled] = await Promise.all([api.summary(), api.events()]);
    setPatient(summary);
    setEvents(scheduled);
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
      <section className="flex-1 space-y-4 px-4 pb-4">
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

        <div className="space-y-2">
          <h3 className="px-1 text-sm font-bold text-[#536159]">{t("calendar.needsReview")}</h3>
          {events.slice(0, 3).map((event) => (
            <a href={`/event/${event.id}`} className="block rounded-lg border border-[#dfe8e2] bg-white p-3" key={event.id}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-semibold">{event.payload.title}</p>
                  <p className="mt-1 text-xs text-[#66726a]">{formatDate(event.payload.start_at, dateLocale)}</p>
                </div>
                <StatusBadge status={event.status} />
              </div>
            </a>
          ))}
        </div>
      </section>
      <BottomNav />
    </>
  );
}
