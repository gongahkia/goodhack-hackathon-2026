"use client";

import { useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { DatesSetArg, EventContentArg, EventDropArg } from "@fullcalendar/core";
import type { EventResizeDoneArg } from "@fullcalendar/interaction";
import { useRouter } from "next/navigation";
import { AlertTriangle, Clock, Coffee, Download, GripVertical, Minus, Plus, ShieldCheck } from "lucide-react";
import { clsx } from "clsx";
import type { KgNode } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { formatDate } from "@/lib/format";
import { api } from "@/lib/api";

type CalendarMode = "month" | "week" | "day" | "range" | "agenda";
type RestWindow = { id: string; label: string; start: string; end: string; enabled: boolean };
const PREFERENCES_KEY = "caregiver-companion-preferences";
const defaultRestWindows: RestWindow[] = [{ id: "midday", label: "Protected rest", start: "12:00", end: "18:00", enabled: true }];

const viewByMode: Record<Exclude<CalendarMode, "agenda">, string> = {
  month: "dayGridMonth",
  week: "timeGridWeek",
  day: "timeGridDay",
  range: "timeGridRange"
};

export function CalendarView({ events }: { events: KgNode[] }) {
  const router = useRouter();
  const { t, dateLocale } = useI18n();
  const [localEvents, setLocalEvents] = useState(events);
  const [mode, setMode] = useState<CalendarMode>("day");
  const [rangeDays, setRangeDays] = useState(3);
  const [bufferMinutes, setBufferMinutes] = useState(10);
  const [restWindows, setRestWindows] = useState<RestWindow[]>(defaultRestWindows);
  const [scheduleMessage, setScheduleMessage] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState(() => localDayKey(new Date()));
  const [visibleRange, setVisibleRange] = useState<{ start: Date; end: Date } | null>(null);
  const currentView = mode === "agenda" ? "timeGridDay" : viewByMode[mode];
  const calendarMinWidth = mode === "week" ? 760 : mode === "range" ? Math.max(390, rangeDays * 126 + 78) : 0;
  const calendarBreakEvents = useMemo(() => buildCalendarBreakEvents(localEvents, bufferMinutes), [bufferMinutes, localEvents]);
  const calendarEvents = useMemo(
    () => [
      ...localEvents.map((node) => ({
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
      ...calendarBreakEvents
    ],
    [calendarBreakEvents, localEvents]
  );
  const agendaEvents = useMemo(() => {
    const sorted = [...localEvents].sort((a, b) => new Date(a.payload.start_at).getTime() - new Date(b.payload.start_at).getTime());
    if (mode === "month" || mode === "agenda") {
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
  }, [localEvents, mode, selectedDate, visibleRange]);
  const agendaBlocks = useMemo(
    () => buildAgendaBlocks(agendaEvents, mode, bufferMinutes, dateLocale, restWindows, selectedDate),
    [agendaEvents, bufferMinutes, dateLocale, mode, restWindows, selectedDate]
  );

  useEffect(() => {
    setLocalEvents(events);
  }, [events]);

  useEffect(() => {
    function loadSchedulePreferences() {
      try {
        const stored = window.localStorage.getItem(PREFERENCES_KEY);
        const parsed = stored ? (JSON.parse(stored) as { breakBufferMinutes?: number; restWindows?: RestWindow[] }) : {};
        if (typeof parsed.breakBufferMinutes === "number") {
          setBufferMinutes(Math.max(0, Math.min(60, parsed.breakBufferMinutes)));
        }
        if (Array.isArray(parsed.restWindows) && parsed.restWindows.length > 0) {
          setRestWindows(parsed.restWindows);
        } else {
          setRestWindows(defaultRestWindows);
        }
      } catch {
        setBufferMinutes(10);
        setRestWindows(defaultRestWindows);
      }
    }
    loadSchedulePreferences();
    window.addEventListener("storage", loadSchedulePreferences);
    window.addEventListener("caregiver-companion-preferences-change", loadSchedulePreferences);
    return () => {
      window.removeEventListener("storage", loadSchedulePreferences);
      window.removeEventListener("caregiver-companion-preferences-change", loadSchedulePreferences);
    };
  }, []);

  function handleDatesSet(arg: DatesSetArg) {
    setVisibleRange({ start: arg.start, end: arg.end });
    if (mode !== "month") {
      setSelectedDate(arg.startStr.slice(0, 10));
    }
  }

  async function rescheduleEvent(arg: EventDropArg | EventResizeDoneArg) {
    if (arg.event.extendedProps.synthetic) {
      arg.revert();
      return;
    }
    const startAt = arg.event.start?.toISOString();
    if (!startAt) {
      arg.revert();
      return;
    }
    const endAt = arg.event.end?.toISOString();
    const eventId = arg.event.id;
    const original = localEvents.find((event) => event.id === eventId) || events.find((event) => event.id === eventId);
    if (!original) {
      arg.revert();
      return;
    }
    const candidate: KgNode = {
      ...original,
      payload: {
        ...original.payload,
        start_at: startAt,
        ...(endAt ? { end_at: endAt } : {})
      }
    };
    if (overlapsProtectedRest(candidate, restWindows) && !candidate.payload.rest_interrupt_allowed) {
      arg.revert();
      setScheduleMessage(t("calendar.restMoveBlocked"));
      window.setTimeout(() => setScheduleMessage(null), 4500);
      return;
    }
    setLocalEvents((current) =>
      current.map((event) =>
        event.id === eventId
          ? {
              ...event,
              payload: {
                ...event.payload,
                start_at: startAt,
                ...(endAt ? { end_at: endAt } : {})
              }
            }
          : event
      )
    );
    try {
      await api.editNode(eventId, {
        start_at: startAt,
        ...(endAt ? { end_at: endAt } : {}),
        caregiver_order_signal: {
          moved_at: new Date().toISOString(),
          previous_start_at: original.payload.start_at,
          preferred_block: preferredBlockForDate(new Date(startAt), restWindows)
        }
      });
      setScheduleMessage(t("calendar.scheduleUpdated"));
      window.setTimeout(() => setScheduleMessage(null), 3500);
    } catch {
      arg.revert();
      setLocalEvents(events);
    }
  }

  function shiftSelectedDate(days: number) {
    const date = new Date(`${selectedDate}T00:00:00`);
    date.setDate(date.getDate() + days);
    setSelectedDate(localDayKey(date));
  }

  return (
    <div className="space-y-3">
      {scheduleMessage ? <p className="rounded-lg border border-[#dfe8e2] bg-[#f5f8f6] px-3 py-2 text-sm font-semibold text-moss">{scheduleMessage}</p> : null}
      <div className="no-print space-y-2">
        <div className="grid grid-cols-5 gap-1 rounded-lg bg-[#eef3ef] p-1">
          {(["month", "week", "day", "range", "agenda"] as CalendarMode[]).map((item) => (
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

      {mode === "agenda" ? (
        <div className="flex items-center justify-between rounded-lg border border-[#dfe8e2] bg-white px-2 py-2">
          <button aria-label={t("calendar.previousDay")} className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[#cbd8cf] text-moss" onClick={() => shiftSelectedDate(-1)}>
            {"<"}
          </button>
          <span className="text-sm font-bold text-ink">{shortAgendaDate(new Date(`${selectedDate}T00:00:00`), dateLocale)}</span>
          <button aria-label={t("calendar.nextDay")} className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[#cbd8cf] text-moss" onClick={() => shiftSelectedDate(1)}>
            {">"}
          </button>
        </div>
      ) : (
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
              editable
              eventDurationEditable
              eventStartEditable
              dayMaxEventRows={mode === "month" ? 3 : false}
              moreLinkClick="popover"
              events={calendarEvents}
              dateClick={(info) => setSelectedDate(info.dateStr)}
              datesSet={handleDatesSet}
              eventContent={renderEventContent}
              eventClick={(info) => {
                if (info.event.extendedProps.synthetic && info.event.extendedProps.breakHref) {
                  router.push(info.event.extendedProps.breakHref);
                } else if (!info.event.extendedProps.synthetic) {
                  router.push(`/event/${info.event.id}`);
                }
              }}
              eventDrop={rescheduleEvent}
              eventResize={rescheduleEvent}
            />
          </div>
        </div>
      )}

      {mode !== "agenda" ? (
        <div className="flex flex-wrap gap-2 text-[11px] font-bold text-[#536159]">
          {(["medication", "therapy", "appointment", "grant"] as const).map((type) => (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f5f8f6] px-2 py-1" key={type}>
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colorByActionType(type) }} />
              {t(`eventType.${type}`)}
            </span>
          ))}
        </div>
      ) : null}

      {mode === "agenda" ? (
        <section className="rounded-xl border border-[#dfe8e2] bg-[#fbfdfb] p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase text-moss">{t("calendar.agenda")}</p>
              <h3 className="mt-0.5 text-sm font-bold text-ink">{agendaTitle(mode, selectedDate, visibleRange, dateLocale)}</h3>
            </div>
            <span className="rounded-full bg-mint px-2.5 py-1 text-xs font-bold text-moss">{agendaBlocks.length}</span>
          </div>
          <div className="mt-3 space-y-3">
            {agendaEvents.length === 0 ? <p className="rounded-lg bg-white p-3 text-sm text-[#66726a]">{t("calendar.noAgendaEvents")}</p> : null}
            {agendaBlocks.map((block) => (
              <div
                className={clsx("rounded-lg border border-[#dfe8e2] bg-white p-3", block.href && "cursor-pointer transition hover:border-moss")}
                key={block.id}
                onClick={() => {
                  if (block.href) {
                    router.push(block.href);
                  }
                }}
                onKeyDown={(event) => {
                  if (block.href && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    router.push(block.href);
                  }
                }}
                role={block.href ? "button" : undefined}
                tabIndex={block.href ? 0 : undefined}
              >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="inline-flex items-center gap-2 text-sm font-bold text-ink">
                    {block.break ? <Coffee className="h-4 w-4 text-moss" /> : null}
                    {block.protected && !block.break ? <ShieldCheck className="h-4 w-4 text-moss" /> : null}
                    {block.title || t(block.labelKey)}
                  </p>
                  <p className="mt-0.5 text-xs text-[#66726a]">{block.window}</p>
                </div>
                {block.break ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-mint px-2 py-1 text-[11px] font-bold text-moss">
                    <Coffee className="h-3.5 w-3.5" /> {bufferMinutes}m
                  </span>
                ) : block.protected ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-mint px-2 py-1 text-[11px] font-bold text-moss">
                    <ShieldCheck className="h-3.5 w-3.5" /> {t("calendar.protected")}
                  </span>
                ) : (
                  <span className="rounded-full bg-[#eef3ef] px-2 py-1 text-[11px] font-bold text-[#536159]">{block.events.length}</span>
                )}
              </div>
              {block.events.length === 0 ? (
                <p className="mt-2 text-sm text-[#66726a]">{block.break ? t("calendar.breakDescription") : block.protected ? t("calendar.protectedRestDescription") : t("calendar.noBlockTasks")}</p>
              ) : (
                <div className="mt-3 space-y-2">
                  {block.events.map((event) => (
                    <AgendaEventButton event={event} key={event.id} onOpen={() => router.push(`/event/${event.id}`)} restWindows={restWindows} />
                  ))}
                </div>
              )}
            </div>
          ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function AgendaEventButton({ event, onOpen, restWindows }: { event: KgNode; onOpen: () => void; restWindows: RestWindow[] }) {
  const { t, dateLocale } = useI18n();
  const restConflict = overlapsProtectedRest(event, restWindows) && !event.payload.rest_interrupt_allowed;
  return (
    <button
      className={clsx(
        "grid w-full grid-cols-[4px_1fr] overflow-hidden rounded-lg border bg-[#fbfdfb] text-left shadow-sm",
        restConflict ? "border-[#d79a86]" : "border-[#dfe8e2]"
      )}
      onClick={onOpen}
    >
      <span className="h-full" style={{ backgroundColor: eventColor(event) }} />
      <span className="min-w-0 p-3">
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="block truncate text-sm font-bold text-ink">{event.payload.title}</span>
            <span className="mt-1 flex items-center gap-1.5 text-xs text-[#66726a]">
              <Clock className="h-3.5 w-3.5" />
              {formatDate(event.payload.start_at, dateLocale)}
            </span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white px-2 py-1 text-[11px] font-bold text-[#536159]">
            {isFixedTiming(event) ? <Clock className="h-3 w-3" /> : <GripVertical className="h-3 w-3" />}
            {t(isFixedTiming(event) ? "calendar.fixedTiming" : "calendar.flexibleWithinBlock")}
          </span>
        </span>
        {event.status === "pending_review" ? (
          <span className="mt-2 inline-flex rounded-full bg-[#fff3c4] px-2 py-0.5 text-[11px] font-bold text-[#7a5b00]">
            {t("status.pending_review")}
          </span>
        ) : null}
        <span className="mt-2 block text-xs text-[#66726a]">
          {event.payload.scheduling_reason || t(isFixedTiming(event) ? "calendar.fixedTimingReason" : "calendar.flexibleTimingReason")}
        </span>
        {restConflict ? (
          <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-[#f4e5df] px-2 py-0.5 text-[11px] font-bold text-[#8d3d29]">
            <AlertTriangle className="h-3 w-3" /> {t("calendar.restConflict")}
          </span>
        ) : null}
      </span>
    </button>
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

type AgendaBlock = {
  id: string;
  labelKey: string;
  title?: string;
  window: string;
  startMs?: number;
  break?: boolean;
  protected?: boolean;
  href?: string;
  events: KgNode[];
};

function buildAgendaBlocks(events: KgNode[], mode: CalendarMode, bufferMinutes: number, locale: string, restWindows: RestWindow[], selectedDate: string): AgendaBlock[] {
  if (mode === "day" || mode === "agenda") {
    return buildDailyAgendaBlocks(events, bufferMinutes, locale, restWindows, selectedDate);
  }
  const blocks: AgendaBlock[] = [
    { id: "morning", labelKey: "calendar.morningBlock", window: "06:00-12:00", events: [] },
    { id: "afternoon", labelKey: "calendar.afternoonBlock", window: "12:00-18:00", events: [] },
    { id: "evening", labelKey: "calendar.eveningBlock", window: "18:00-22:00", events: [] },
    { id: "other", labelKey: "calendar.otherBlock", window: "Outside care windows", events: [] }
  ];
  for (const rest of restWindows.filter((window) => window.enabled)) {
    blocks.splice(1, 0, { id: `rest:${rest.id}`, labelKey: "calendar.restBlock", title: rest.label, window: `${rest.start}-${rest.end}`, protected: true, events: [] });
  }
  for (const event of events) {
    const start = new Date(event.payload.start_at);
    const hour = start.getHours();
    const restBlock = blocks.find((block) => block.id.startsWith("rest:") && pointInWindow(start, block.window));
    if (restBlock) {
      restBlock.events.push(event);
    } else if (hour >= 6 && hour < 12) {
      blocks.find((block) => block.id === "morning")?.events.push(event);
    } else if (hour >= 12 && hour < 18) {
      blocks.find((block) => block.id === "afternoon")?.events.push(event);
    } else if (hour >= 18 && hour < 22) {
      blocks.find((block) => block.id === "evening")?.events.push(event);
    } else {
      blocks.find((block) => block.id === "other")?.events.push(event);
    }
  }
  return blocks.filter((block) => block.protected || block.events.length > 0);
}

function buildDailyAgendaBlocks(events: KgNode[], bufferMinutes: number, locale: string, restWindows: RestWindow[], selectedDate: string): AgendaBlock[] {
  const sorted = [...events].sort(agendaEventSort);
  const blocks: AgendaBlock[] = [];
  for (const rest of restWindows.filter((window) => window.enabled)) {
    const start = dateForTime(selectedDate, rest.start);
    const end = dateForTime(selectedDate, rest.end);
    blocks.push({
      id: `rest:${rest.id}:${selectedDate}`,
      labelKey: "calendar.restBlock",
      title: rest.label,
      window: `${shortTime(start, locale)} - ${shortTime(end, locale)}`,
      startMs: start.getTime(),
      protected: true,
      events: []
    });
  }
  for (const [index, event] of sorted.entries()) {
    const eventStart = new Date(event.payload.start_at);
    blocks.push({
      id: `event:${event.id}`,
      labelKey: "calendar.careTask",
      title: event.payload.title,
      window: formatEventWindow(event, locale),
      startMs: eventStart.getTime(),
      events: [event]
    });
    const next = sorted[index + 1];
    if (!next) {
      continue;
    }
    const currentEnd = new Date(event.payload.end_at || event.payload.start_at);
    const nextStart = new Date(next.payload.start_at);
    const breakStart = new Date(currentEnd.getTime() + bufferMinutes * 60_000);
    const breakEnd = new Date(nextStart.getTime() - bufferMinutes * 60_000);
    if (breakEnd.getTime() > breakStart.getTime()) {
      blocks.push({
        id: `break:${event.id}:${next.id}`,
        labelKey: "calendar.breakBlock",
        window: `${shortTime(breakStart, locale)} - ${shortTime(breakEnd, locale)}`,
        startMs: breakStart.getTime(),
        break: true,
        protected: true,
        href: breakHref(breakStart, breakEnd, event.payload.title, next.payload.title),
        events: []
      });
    }
  }
  return blocks.sort((a, b) => (a.startMs || 0) - (b.startMs || 0));
}

function buildCalendarBreakEvents(events: KgNode[], bufferMinutes: number) {
  const grouped = new Map<string, KgNode[]>();
  for (const event of events) {
    const key = dayKey(event.payload.start_at);
    grouped.set(key, [...(grouped.get(key) || []), event]);
  }
  const breaks = [];
  for (const [day, dayEvents] of grouped.entries()) {
    const sorted = dayEvents.sort((a, b) => new Date(a.payload.start_at).getTime() - new Date(b.payload.start_at).getTime());
    for (const [index, event] of sorted.entries()) {
      const next = sorted[index + 1];
      if (!next) {
        continue;
      }
      const currentEnd = new Date(event.payload.end_at || event.payload.start_at);
      const nextStart = new Date(next.payload.start_at);
      const breakStart = new Date(currentEnd.getTime() + bufferMinutes * 60_000);
      const breakEnd = new Date(nextStart.getTime() - bufferMinutes * 60_000);
      if (breakEnd.getTime() <= breakStart.getTime()) {
        continue;
      }
      breaks.push({
        id: `break:${day}:${event.id}:${next.id}`,
        title: "Break",
        start: breakStart.toISOString(),
        end: breakEnd.toISOString(),
        backgroundColor: "#dff3e7",
        borderColor: "#b8d8c1",
        textColor: "#405b48",
        editable: false,
        durationEditable: false,
        startEditable: false,
        extendedProps: {
          synthetic: true,
          actionType: "break",
          breakHref: breakHref(breakStart, breakEnd, event.payload.title, next.payload.title)
        }
      });
    }
  }
  return breaks;
}

function agendaEventSort(a: KgNode, b: KgNode) {
  const aStart = new Date(a.payload.start_at).getTime();
  const bStart = new Date(b.payload.start_at).getTime();
  if (aStart !== bStart) {
    return aStart - bStart;
  }
  const aFixed = isFixedTiming(a) ? 0 : 1;
  const bFixed = isFixedTiming(b) ? 0 : 1;
  if (aFixed !== bFixed) {
    return aFixed - bFixed;
  }
  return Number(b.payload.estimated_effort_minutes || 0) - Number(a.payload.estimated_effort_minutes || 0);
}

function preferredBlockForDate(date: Date, restWindows: RestWindow[]) {
  const rest = restWindows.find((window) => window.enabled && pointInWindow(date, `${window.start}-${window.end}`));
  if (rest) {
    return `rest:${rest.id}`;
  }
  const hour = date.getHours();
  if (hour >= 6 && hour < 12) {
    return "morning";
  }
  if (hour >= 18 && hour < 22) {
    return "evening";
  }
  return "daytime";
}

function formatEventWindow(event: KgNode, locale: string) {
  const start = new Date(event.payload.start_at);
  const end = event.payload.end_at ? new Date(event.payload.end_at) : null;
  return end ? `${shortTime(start, locale)} - ${shortTime(end, locale)}` : shortTime(start, locale);
}

function shortTime(date: Date, locale: string) {
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(date);
}

function isFixedTiming(event: KgNode) {
  return event.payload.timing_type === "fixed_time" || event.payload.timing_type === "deadline" || event.payload.action_type === "medication" || event.payload.action_type === "appointment";
}

function overlapsProtectedRest(event: KgNode, restWindows: RestWindow[]) {
  const start = new Date(event.payload.start_at);
  const end = event.payload.end_at ? new Date(event.payload.end_at) : new Date(start.getTime() + Number(event.payload.estimated_effort_minutes || 20) * 60_000);
  const eventStart = start.getHours() * 60 + start.getMinutes();
  const eventEnd = end.getHours() * 60 + end.getMinutes();
  return restWindows.filter((window) => window.enabled).some((window) => rangesOverlap(eventStart, eventEnd, minutesOfDay(window.start), minutesOfDay(window.end)));
}

function rangesOverlap(startA: number, endA: number, startB: number, endB: number) {
  return startA < endB && startB < endA;
}

function pointInWindow(date: Date, window: string) {
  const [start, end] = window.split("-");
  if (!start || !end) {
    return false;
  }
  const minute = date.getHours() * 60 + date.getMinutes();
  return minute >= minutesOfDay(start.trim()) && minute < minutesOfDay(end.trim());
}

function minutesOfDay(value: string) {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function dateForTime(day: string, time: string) {
  return new Date(`${day}T${time}:00`);
}

function breakHref(start: Date, end: Date, after?: string, before?: string) {
  const params = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
    after: String(after || ""),
    before: String(before || "")
  });
  return `/break?${params.toString()}`;
}

function renderEventContent(info: EventContentArg) {
  if (info.event.extendedProps.synthetic) {
    return (
      <div className="flex min-w-0 cursor-pointer items-center gap-1 overflow-hidden px-1 py-0.5 leading-none text-[#405b48]">
        {info.timeText ? <span className="min-w-0 shrink truncate text-[10px] font-black">{info.timeText}</span> : null}
        <span className="min-w-0 flex-1 truncate text-[10px] font-bold">Break</span>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1 overflow-hidden px-1 py-0.5 leading-none">
      {info.timeText ? <span className="min-w-0 shrink truncate text-[10px] font-black">{info.timeText}</span> : null}
      <span className="min-w-0 flex-1 truncate text-[10px] font-bold">{info.event.title}</span>
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
