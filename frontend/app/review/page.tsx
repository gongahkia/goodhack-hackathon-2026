"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ClipboardList, ExternalLink, Minus, Plus, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { clsx } from "clsx";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useNotifications } from "@/components/notifications-provider";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { EventDetail, KgNode } from "@/lib/types";

type ReviewEvent = KgNode | EventDetail;

export default function ReviewPage() {
  const { t, dateLocale } = useI18n();
  const { notify, refreshNotifications } = useNotifications();
  const [events, setEvents] = useState<ReviewEvent[]>([]);
  const [feedback, setFeedback] = useState<Record<string, { score: number; steer: string; note: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const scheduled = await api.events();
    const enriched = await Promise.all(
      scheduled.map(async (event) => {
        const shouldEnrich =
          event.payload.action_type === "grant" ||
          event.payload.action_type === "appointment" ||
          String(event.payload.title || "").toLowerCase().includes("apply");
        if (!shouldEnrich) {
          return event;
        }
        return api.event(event.id).catch(() => event);
      })
    );
    setEvents(enriched);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  const pendingEvents = useMemo(
    () =>
      events
        .filter((event) => event.status === "pending_review")
        .sort((a, b) => new Date(a.payload.start_at).getTime() - new Date(b.payload.start_at).getTime()),
    [events]
  );

  function eventFeedback(eventId: string) {
    return feedback[eventId] || { score: 3, steer: "same", note: "" };
  }

  function updateFeedback(eventId: string, patch: Partial<{ score: number; steer: string; note: string }>) {
    setFeedback((current) => ({ ...current, [eventId]: { ...eventFeedback(eventId), ...patch } }));
  }

  async function setStatus(event: KgNode, status: "approved" | "dismissed") {
    setBusy(`${event.id}:${status}`);
    setError(null);
    const currentFeedback = eventFeedback(event.id);
    try {
      const updated = await api.status(event.id, status, {
        usefulness_score: currentFeedback.score,
        steer: currentFeedback.steer === "same" ? undefined : currentFeedback.steer,
        feedback_note: currentFeedback.note || undefined
      });
      await load();
      await refreshNotifications({ suppressToasts: true });
      notify({
        title: t("notifications.statusSaved"),
        body: `${updated.payload.title || event.payload.title} · ${t("review.feedbackSaved")}`,
        kind: status,
        href: `/event/${event.id}`
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <AppHeader title={t("review.title")} subtitle={t("review.subtitle")} />
      <section className="flex-1 space-y-3 px-4 pb-28">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {pendingEvents.length === 0 ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("review.empty")}</p> : null}
        {pendingEvents.map((event) => (
          <article className="rounded-xl border border-[#dfe8e2] bg-white p-4" key={event.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase text-moss">{event.payload.action_type || t("event.careAction")}</p>
                <h2 className="mt-1 text-lg font-bold text-ink">{event.payload.title}</h2>
                <p className="mt-1 text-sm text-[#66726a]">{formatDate(event.payload.start_at, dateLocale)}</p>
              </div>
              <StatusBadge status={event.status} />
            </div>
            <p className="mt-3 text-sm text-[#34423a]">{event.payload.description}</p>
            {appointmentPrep(event) ? <ReviewPrepBlock event={event} /> : null}
            <div className="mt-4 rounded-lg border border-[#dfe8e2] bg-[#f5f8f6] p-3">
              <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
                <Sparkles className="h-4 w-4 text-moss" /> {t("review.scoreTitle")}
              </p>
              <div className="mt-3 grid grid-cols-5 gap-1">
                {[1, 2, 3, 4, 5].map((score) => {
                  const active = eventFeedback(event.id).score === score;
                  return (
                    <button
                      aria-pressed={active}
                      className={clsx(
                        "min-h-9 rounded-md border text-sm font-bold",
                        active ? "border-moss bg-moss text-white" : "border-[#cbd8cf] bg-white text-[#536159]"
                      )}
                      key={score}
                      onClick={() => updateFeedback(event.id, { score })}
                      type="button"
                    >
                      {score}
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {[
                  { key: "more", label: t("review.steerMore"), icon: Plus },
                  { key: "less", label: t("review.steerLess"), icon: Minus },
                  { key: "simpler", label: t("review.steerSimpler"), icon: Sparkles }
                ].map((item) => {
                  const active = eventFeedback(event.id).steer === item.key;
                  const Icon = item.icon;
                  return (
                    <button
                      aria-pressed={active}
                      className={clsx(
                        "inline-flex min-h-10 items-center justify-center gap-1 rounded-lg border px-2 text-xs font-bold",
                        active ? "border-moss bg-mint text-moss" : "border-[#cbd8cf] bg-white text-[#536159]"
                      )}
                      key={item.key}
                      onClick={() => updateFeedback(event.id, { steer: active ? "same" : item.key })}
                      type="button"
                    >
                      <Icon className="h-3.5 w-3.5" /> {item.label}
                    </button>
                  );
                })}
              </div>
              <textarea
                className="mt-3 min-h-16 w-full rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm text-ink"
                onChange={(changeEvent) => updateFeedback(event.id, { note: changeEvent.target.value })}
                placeholder={t("review.feedbackPlaceholder")}
                value={eventFeedback(event.id).note}
              />
            </div>
            {grantApplyUrl(event) ? (
              <a
                className="mt-4 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white"
                href={grantApplyUrl(event)}
                target="_blank"
                rel="noreferrer"
              >
                {t("common.apply")} <ExternalLink className="h-4 w-4" />
              </a>
            ) : null}
            {appointmentRescheduleUrl(event) ? (
              <a
                className="mt-4 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white"
                href={appointmentRescheduleUrl(event)}
                target="_blank"
                rel="noreferrer"
              >
                {t("common.reschedule")} <ExternalLink className="h-4 w-4" />
              </a>
            ) : null}
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Button onClick={() => setStatus(event, "approved")} disabled={Boolean(busy)}>
                <ThumbsUp className="h-4 w-4" /> {t("event.approve")}
              </Button>
              <Button variant="danger" onClick={() => setStatus(event, "dismissed")} disabled={Boolean(busy)}>
                <ThumbsDown className="h-4 w-4" /> {t("event.dismiss")}
              </Button>
            </div>
            <Link href={`/event/${event.id}`} className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-moss">
              {t("review.openDetail")} <ArrowRight className="h-4 w-4" />
            </Link>
          </article>
        ))}
      </section>
      <BottomNav />
    </>
  );
}

function appointmentPrep(event: ReviewEvent) {
  return "appointment_prep" in event ? event.appointment_prep : null;
}

function ReviewPrepBlock({ event }: { event: ReviewEvent }) {
  const { t } = useI18n();
  const prep = appointmentPrep(event);
  if (!prep) {
    return null;
  }
  const items = [...prep.symptoms_to_mention.slice(0, 2), ...prep.questions_for_clinician.slice(0, 2)];
  return (
    <div className="mt-4 rounded-lg border border-[#dfe8e2] bg-[#f5f8f6] p-3">
      <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
        <ClipboardList className="h-4 w-4 text-moss" /> {t("review.appointmentPrep")}
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-[#34423a]">
        {items.map((item) => (
          <li className="flex gap-2" key={item}>
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-moss" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function grantApplyUrl(event: ReviewEvent) {
  if (!("related_nodes" in event)) {
    return event.payload.url || event.payload.apply_url || null;
  }
  const grant = event.related_nodes.find((node) => node.type === "grant_opportunity");
  return grant?.payload.url || event.payload.url || event.payload.apply_url || null;
}

function appointmentRescheduleUrl(event: ReviewEvent) {
  if (event.payload.action_type !== "appointment") {
    return null;
  }
  return event.payload.scheduling_url || event.payload.reschedule_url || inferSchedulingUrl(event.payload.location || event.payload.title);
}

function inferSchedulingUrl(value?: string) {
  const text = String(value || "").toLowerCase();
  if (text.includes("tan tock seng") || text.includes("ttsh") || text.includes("neurology")) {
    return "https://www.ttsh.com.sg/Patients-and-Visitors/Your-Clinic-Visit/Pages/Appointments.aspx";
  }
  return "https://www.healthhub.sg/programmes/healthhub-health-appointment-system";
}
