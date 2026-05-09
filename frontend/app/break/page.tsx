"use client";

import Link from "next/link";
import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, BatteryCharging, Clock, Coffee, Droplets, ShieldCheck } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useI18n } from "@/lib/i18n";

export default function BreakPage() {
  return (
    <Suspense fallback={<BreakFallback />}>
      <BreakContent />
    </Suspense>
  );
}

function BreakContent() {
  const params = useSearchParams();
  const { dateLocale } = useI18n();
  const start = useMemo(() => parseDate(params.get("start")), [params]);
  const end = useMemo(() => parseDate(params.get("end")), [params]);
  const after = params.get("after") || "";
  const before = params.get("before") || "";
  const minutes = start && end ? Math.max(0, Math.round((end.getTime() - start.getTime()) / 60000)) : 0;
  const windowLabel = start && end ? `${shortTime(start, dateLocale)} - ${shortTime(end, dateLocale)}` : "Rest window";
  const recommendations = restRecommendations(minutes, before);

  return (
    <>
      <AppHeader title="Rest break" subtitle={windowLabel} />
      <section className="flex-1 space-y-4 px-4 pb-28">
        <Link className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss" href="/">
          <ArrowLeft className="h-4 w-4" /> Calendar
        </Link>

        <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase text-moss">Protected recovery</p>
              <h2 className="mt-1 text-xl font-bold text-ink">{windowLabel}</h2>
              <p className="mt-1 text-sm text-[#66726a]">{minutes > 0 ? `${minutes} minutes available` : "Timing details unavailable"}</p>
            </div>
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-mint text-moss">
              <Coffee className="h-6 w-6" />
            </span>
          </div>
          {after || before ? (
            <div className="mt-4 grid gap-2 text-sm">
              {after ? <ContextLine label="After" value={after} /> : null}
              {before ? <ContextLine label="Before" value={before} /> : null}
            </div>
          ) : null}
        </article>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <h2 className="inline-flex items-center gap-2 font-bold text-ink">
            <ShieldCheck className="h-4 w-4 text-moss" /> Recommended rest plan
          </h2>
          <div className="mt-3 space-y-3">
            {recommendations.map((item) => (
              <div className="grid grid-cols-[2rem_1fr] gap-3 rounded-lg bg-[#f5f8f6] p-3" key={item.title}>
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white text-moss">{item.icon}</span>
                <span>
                  <span className="block text-sm font-bold text-ink">{item.title}</span>
                  <span className="mt-0.5 block text-sm text-[#536159]">{item.detail}</span>
                </span>
              </div>
            ))}
          </div>
        </section>
      </section>
      <BottomNav />
    </>
  );
}

function ContextLine({ label, value }: { label: string; value: string }) {
  return (
    <p className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-[#536159]">
      <span className="font-bold text-moss">{label}: </span>
      {value}
    </p>
  );
}

function BreakFallback() {
  return (
    <>
      <AppHeader title="Rest break" />
      <section className="flex-1 px-4 pb-28">
        <p className="rounded-xl border border-[#dfe8e2] bg-white p-4 text-sm text-[#66726a]">Loading break details...</p>
      </section>
      <BottomNav />
    </>
  );
}

function restRecommendations(minutes: number, nextAction: string) {
  const first =
    minutes >= 45
      ? "Use the first 20 minutes for a real pause before doing any household or admin work."
      : minutes >= 20
        ? "Keep this as a quiet seated break instead of filling it with another task."
        : "Treat this as a short reset: sit down, breathe steadily, and avoid rushing into the next action.";
  return [
    { title: "Start with stillness", detail: first, icon: <BatteryCharging className="h-4 w-4" /> },
    { title: "Hydrate and check comfort", detail: "Offer water, check dizziness or fatigue, and keep walking paths clear before moving again.", icon: <Droplets className="h-4 w-4" /> },
    {
      title: "Prepare five minutes before",
      detail: nextAction ? `At the end of the break, prepare only what is needed for ${nextAction}.` : "Use the final five minutes to prepare only the next required care item.",
      icon: <Clock className="h-4 w-4" />
    }
  ];
}

function parseDate(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function shortTime(date: Date, locale: string) {
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(date);
}
