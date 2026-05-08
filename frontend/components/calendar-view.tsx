"use client";

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import { useRouter } from "next/navigation";
import type { KgNode } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

export function CalendarView({ events }: { events: KgNode[] }) {
  const router = useRouter();
  const { t } = useI18n();
  return (
    <FullCalendar
      plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
      initialView="dayGridMonth"
      headerToolbar={{ left: "prev,next", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" }}
      buttonIcons={false}
      buttonText={{ prev: "<", next: ">", dayGridMonth: t("calendar.month"), timeGridWeek: t("calendar.week"), timeGridDay: t("calendar.day") }}
      height="auto"
      events={events.map((node) => ({
        id: node.id,
        title: node.payload.title,
        start: node.payload.start_at,
        end: node.payload.end_at,
        color: node.status === "pending_review" ? "#b6654b" : "#405b48"
      }))}
      eventClick={(info) => router.push(`/event/${info.event.id}`)}
    />
  );
}
