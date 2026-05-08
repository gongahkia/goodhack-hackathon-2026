"use client";

import { useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { DatesSetArg, EventContentArg } from "@fullcalendar/core";
import { useRouter } from "next/navigation";
import { Clock, Download, Minus, Plus } from "lucide-react";
import { clsx } from "clsx";
import type { KgNode } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { formatDate } from "@/lib/format";

type CalendarMode = "month" | "week" | "day" | "range";

const viewByMode: Record<CalendarMode, string> = {
  month: "dayGridMonth",
  week: "timeGridWeek",
  day: "timeGridDay",
  range: "timeGridRange"
};

export function CalendarView({ events }: { events: KgNode[] }) {
  const router = useRouter();
  const { t, dateLocale } = useI18n();
  const [mode, setMode] = useState<CalendarMode>("month");
  const [rangeDays, setRangeDays] = useState(3);
  const [selectedDate, setSelectedDate] = useState(() => localDayKey(new Date()));
  const [visibleRange, setVisibleRange] = useState<{ start: Date; end: Date } | null>(null);
  const currentView = viewByMode[mode];
  const calendarMinWidth = mode === "week" ? 760 : mode === "range" ? Math.max(390, rangeDays * 126 + 78) : 0;
  const calendarEvents = useMemo(
    () =>
      events.map((node) => ({
        id: node.id,
        title: node.payload.title,
        start: node.payload.start_at,
        end: node.payload.end_at,
        backgroundColor: eventColor(node),
        borderColor: eventColor(node),
        textColor: "#ffffff",
        extendedProps: {
          status: node.status,
          actionType: node.payload.action_type
        }
      })),
    [events]
  );
  const agendaEvents = useMemo(() => {
    const sorted = [...events].sort((a, b) => new Date(a.payload.start_at).getTime() - new Date(b.payload.start_at).getTime());
    if (mode === "month") {
      return sorted.filter((event) => dayKey(event.payload.start_at) === selectedDate);
    }
    if (mode === "day") {
      return sorted.filter((event) => dayKey(event.payload.start_at) === selectedDate);
    }
    if (!visibleRange) {
      return sorted.slice(0, 4);
    }
    return sorted.filter((event) => {
      const start = new Date(event.payload.start_at);
      return start >= visibleRange.start && start < visibleRange.end;
    });
  }, [events, mode, selectedDate, visibleRange]);

  function handleDatesSet(arg: DatesSetArg) {
    setVisibleRange({ start: arg.start, end: arg.end });
    if (mode !== "month") {
      setSelectedDate(arg.startStr.slice(0, 10));
    }
  }

  return (
    <div className="space-y-3">
      <div className="no-print space-y-2">
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-[#eef3ef] p-1">
          {(["month", "week", "day", "range"] as CalendarMode[]).map((item) => (
            <button
              className={clsx(
                "min-h-9 rounded-md px-2 text-xs font-semibold transition",
                mode === item ? "bg-moss text-white" : "text-[#536159] hover:bg-white"
              )}
              key={item}
              onClick={() => setMode(item)}
            >
              {t(`calendar.${item}`)}
            </button>
          ))}
        </div>

        <button
          className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss"
          onClick={() => window.print()}
        >
          <Download className="h-4 w-4" /> {t("calendar.exportPdf")}
        </button>
      </div>

      {mode === "range" ? (
        <div className="flex items-center justify-between rounded-lg border border-[#dfe8e2] bg-white px-2 py-2">
          <button
            aria-label={t("calendar.decreaseDays")}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[#cbd8cf] text-moss disabled:opacity-40"
            disabled={rangeDays <= 1}
            onClick={() => setRangeDays((days) => Math.max(1, days - 1))}
          >
            <Minus className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold text-[#34423a]">{t("calendar.daysCount").replace("{count}", String(rangeDays))}</span>
          <button
            aria-label={t("calendar.increaseDays")}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[#cbd8cf] text-moss disabled:opacity-40"
            disabled={rangeDays >= 7}
            onClick={() => setRangeDays((days) => Math.min(7, days + 1))}
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      <div className="schedule-calendar-scroll overflow-x-auto pb-1">
        <div style={calendarMinWidth ? { minWidth: calendarMinWidth } : undefined}>
          <FullCalendar
            key={`${currentView}-${rangeDays}`}
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
            initialView={currentView}
            views={{
              timeGridRange: {
                type: "timeGrid",
                duration: { days: rangeDays },
                buttonText: t("calendar.range")
              }
            }}
            headerToolbar={{ left: "prev,next", center: "title", right: "" }}
            buttonIcons={false}
            buttonText={{ prev: "<", next: ">" }}
            height={mode === "month" ? "auto" : 620}
            allDaySlot={mode !== "month"}
            nowIndicator
            scrollTime="07:00:00"
            slotMinTime="06:00:00"
            slotMaxTime="22:00:00"
            slotDuration="00:30:00"
            eventTimeFormat={{ hour: "numeric", minute: "2-digit", meridiem: "short" }}
            displayEventEnd
            dayMaxEventRows={mode === "month" ? 3 : false}
            moreLinkClick="popover"
            events={calendarEvents}
            dateClick={(info) => setSelectedDate(info.dateStr)}
            datesSet={handleDatesSet}
            eventContent={renderEventContent}
            eventClick={(info) => router.push(`/event/${info.event.id}`)}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px] font-bold text-[#536159]">
        {(["medication", "therapy", "appointment", "grant"] as const).map((type) => (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f5f8f6] px-2 py-1" key={type}>
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colorByActionType(type) }} />
            {t(`eventType.${type}`)}
          </span>
        ))}
      </div>

      <section className="rounded-xl border border-[#dfe8e2] bg-[#fbfdfb] p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase text-moss">{t("calendar.agenda")}</p>
            <h3 className="mt-0.5 text-sm font-bold text-ink">{agendaTitle(mode, selectedDate, visibleRange, dateLocale)}</h3>
          </div>
          <span className="rounded-full bg-mint px-2.5 py-1 text-xs font-bold text-moss">{agendaEvents.length}</span>
        </div>
        <div className="mt-3 space-y-2">
          {agendaEvents.length === 0 ? <p className="rounded-lg bg-white p-3 text-sm text-[#66726a]">{t("calendar.noAgendaEvents")}</p> : null}
          {agendaEvents.map((event) => (
            <button
              className="grid w-full grid-cols-[4px_1fr] overflow-hidden rounded-lg border border-[#dfe8e2] bg-white text-left shadow-sm"
              key={event.id}
              onClick={() => router.push(`/event/${event.id}`)}
            >
              <span className="h-full" style={{ backgroundColor: eventColor(event) }} />
              <span className="min-w-0 p-3">
                <span className="block truncate text-sm font-bold text-ink">{event.payload.title}</span>
                <span className="mt-1 flex items-center gap-1.5 text-xs text-[#66726a]">
                  <Clock className="h-3.5 w-3.5" />
                  {formatDate(event.payload.start_at, dateLocale)}
                </span>
                {event.status === "pending_review" ? (
                  <span className="mt-2 inline-flex rounded-full bg-[#fff3c4] px-2 py-0.5 text-[11px] font-bold text-[#7a5b00]">
                    {t("status.pending_review")}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function dayKey(value: string) {
  return value.slice(0, 10);
}

function localDayKey(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function eventColor(node: KgNode) {
  if (node.status === "dismissed") {
    return "#8a928d";
  }
  const typeColor = colorByActionType(node.payload.action_type);
  if (typeColor) {
    return typeColor;
  }
  return node.status === "pending_review" ? "#b6654b" : "#405b48";
}

function colorByActionType(actionType: string | undefined) {
  if (actionType === "medication") {
    return "#2f80ed";
  }
  if (actionType === "therapy") {
    return "#7c6cf2";
  }
  if (actionType === "appointment") {
    return "#1f8a70";
  }
  if (actionType === "grant") {
    return "#c08a1c";
  }
  return "";
}

function renderEventContent(info: EventContentArg) {
  return (
    <div className="min-w-0 px-1 py-0.5">
      {info.timeText ? <span className="block truncate text-[10px] font-black leading-tight">{info.timeText}</span> : null}
      <span className="block truncate text-[11px] font-bold leading-tight">{info.event.title}</span>
    </div>
  );
}

function agendaTitle(mode: CalendarMode, selectedDate: string, visibleRange: { start: Date; end: Date } | null, locale: string) {
  if ((mode === "week" || mode === "range") && visibleRange) {
    const end = new Date(visibleRange.end);
    end.setDate(end.getDate() - 1);
    return `${shortAgendaDate(visibleRange.start, locale)} - ${shortAgendaDate(end, locale)}`;
  }
  return shortAgendaDate(new Date(`${selectedDate}T00:00:00`), locale);
}

function shortAgendaDate(date: Date, locale: string) {
  return new Intl.DateTimeFormat(locale, { weekday: "short", month: "short", day: "numeric" }).format(date);
}
