"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, BellRing, CalendarPlus, Check, Copy, Database, Download, FileClock, MonitorSmartphone, Moon, RefreshCw, RotateCcw, ShieldCheck, Smartphone, Sun, UserRound, Wifi } from "lucide-react";
import { clsx } from "clsx";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useNotifications } from "@/components/notifications-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { languages, useI18n, type Language } from "@/lib/i18n";
import { useTheme, type ThemeMode } from "@/lib/theme";
import type { CarePlanReview, PatientSummary, VerifiedContent } from "@/lib/types";

type AppPreferences = {
  criticalAlerts: boolean;
  notificationBadges: boolean;
  offlineCache: boolean;
};

const PREFERENCES_KEY = "caregiver-companion-preferences";
const CARE_REVIEW_CACHE_KEY = "caregiver-companion-care-review";
const defaultPreferences: AppPreferences = {
  criticalAlerts: true,
  notificationBadges: true,
  offlineCache: true
};

const themeOptions = [
  { mode: "light", labelKey: "settings.theme.light", icon: Sun },
  { mode: "dark", labelKey: "settings.theme.dark", icon: Moon },
  { mode: "adaptive", labelKey: "settings.theme.adaptive", icon: MonitorSmartphone }
] satisfies Array<{ mode: ThemeMode; labelKey: string; icon: typeof Sun }>;

export default function SettingsPage() {
  const { language, setLanguage, t } = useI18n();
  const { mode, resolvedTheme, setMode } = useTheme();
  const { notify, refreshNotifications } = useNotifications();
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; store: string } | null>(null);
  const [review, setReview] = useState<CarePlanReview | null>(null);
  const [verifiedContent, setVerifiedContent] = useState<VerifiedContent[]>([]);
  const [preferences, setPreferences] = useState<AppPreferences>(defaultPreferences);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const cachedReview = readCachedReview();
    if (cachedReview && preferences.offlineCache) {
      setReview(cachedReview);
    }
    try {
      const [summary, status, carePlanReview, resources, grants] = await Promise.all([
        api.summary(),
        api.health(),
        api.carePlanReview(),
        api.resourceSearch("parkinson exercise", "parkinsons"),
        api.grantSearch("mobility parkinson")
      ]);
      setPatient(summary);
      setHealth(status);
      setReview(carePlanReview);
      setVerifiedContent([...resources, ...grants].slice(0, 4));
      if (preferences.offlineCache) {
        window.localStorage.setItem(CARE_REVIEW_CACHE_KEY, JSON.stringify(carePlanReview));
      }
    } catch (err) {
      if (!cachedReview || !preferences.offlineCache) {
        throw err;
      }
      setError(t("settings.offlineCacheUsed"));
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem(PREFERENCES_KEY);
    if (!stored) {
      return;
    }
    try {
      setPreferences({ ...defaultPreferences, ...JSON.parse(stored) });
    } catch {
      setPreferences(defaultPreferences);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
    window.dispatchEvent(new Event("caregiver-companion-preferences-change"));
  }, [preferences]);

  function togglePreference(key: keyof AppPreferences) {
    setPreferences((current) => ({ ...current, [key]: !current[key] }));
  }

  async function rebuildRecords() {
    setBusy("reset");
    setMessage(null);
    setError(null);
    try {
      await api.reset();
      await load();
      await refreshNotifications({ suppressToasts: true });
      setMessage(t("settings.rebuilt"));
      notify({ title: t("notifications.carePlanRebuilt"), body: t("settings.rebuilt"), kind: "system", href: "/" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function copyFeedUrl() {
    const url = api.calendarFeedUrl();
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <>
      <AppHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <section className="flex-1 space-y-4 px-4 pb-4">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {message ? <div className="rounded-lg bg-mint p-3 text-sm font-semibold text-moss">{message}</div> : null}

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <MonitorSmartphone className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.appearance")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.appearanceDescription")}</p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {themeOptions.map((item) => {
              const Icon = item.icon;
              const active = mode === item.mode;
              return (
                <button
                  aria-pressed={active}
                  className={clsx(
                    "flex min-h-20 flex-col items-center justify-center gap-2 rounded-lg border px-2 py-3 text-center text-xs font-bold transition",
                    active ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] bg-white text-[#536159] hover:bg-[#f5f8f6]"
                  )}
                  key={item.mode}
                  onClick={() => setMode(item.mode)}
                  type="button"
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                  {t(item.labelKey)}
                </button>
              );
            })}
          </div>
          <p className="mt-3 rounded-lg bg-[#f5f8f6] px-3 py-2 text-xs font-semibold text-[#536159]">
            {t("settings.theme.current")}: {resolvedTheme === "dark" ? t("settings.theme.dark") : t("settings.theme.light")}
          </p>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.verifiedContent")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.verifiedContentDescription")}</p>
          <div className="mt-3 space-y-2">
            {verifiedContent.map((item) => (
              <a className="block rounded-lg border border-[#dfe8e2] px-3 py-2" href={item.url || "#"} key={`${item.title}-${item.url}`} target="_blank" rel="noreferrer">
                <span className="block text-sm font-bold text-ink">{item.title}</span>
                <span className="mt-1 block text-xs text-[#66726a]">{item.source}</span>
                <span className="mt-2 inline-flex rounded-full bg-mint px-2 py-0.5 text-[11px] font-bold text-moss">{t("settings.verifiedSource")}</span>
              </a>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <h2 className="font-bold">{t("settings.language")}</h2>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.languageDescription")}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {languages.map((item) => (
              <button
                className={`rounded-lg border px-3 py-2 text-left text-sm font-semibold ${
                  language === item.code ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] bg-white text-[#536159]"
                }`}
                key={item.code}
                onClick={() => setLanguage(item.code as Language)}
              >
                <span className="block">{item.nativeLabel}</span>
                <span className="text-xs font-normal">{item.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Smartphone className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.appPreferences")}</h2>
          </div>
          <div className="mt-3 divide-y divide-[#e7ede9] rounded-lg border border-[#dfe8e2]">
            <SettingsToggle
              checked={preferences.criticalAlerts}
              description={t("settings.criticalAlertsDescription")}
              icon={<BellRing className="h-4 w-4" />}
              label={t("settings.criticalAlerts")}
              onChange={() => togglePreference("criticalAlerts")}
            />
            <SettingsToggle
              checked={preferences.notificationBadges}
              description={t("settings.notificationBadgesDescription")}
              icon={<Check className="h-4 w-4" />}
              label={t("settings.notificationBadges")}
              onChange={() => togglePreference("notificationBadges")}
            />
            <SettingsToggle
              checked={preferences.offlineCache}
              description={t("settings.offlineCacheDescription")}
              icon={<Wifi className="h-4 w-4" />}
              label={t("settings.offlineCache")}
              onChange={() => togglePreference("offlineCache")}
            />
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.careIntelligence")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.careIntelligenceDescription")}</p>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Metric label={t("settings.pendingReview")} value={review?.pending_review_count ?? 0} />
            <Metric label={t("settings.next30Days")} value={review?.upcoming_30_day_count ?? 0} />
            <Metric label={t("settings.memorySignals")} value={review?.memory.learned_preferences.length ?? 0} />
          </div>
          <div className="mt-3 space-y-2">
            {(review?.narrative || []).map((line, index) => (
              <p className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm text-[#34423a]" key={index}>
                {line}
              </p>
            ))}
            {review && review.memory.learned_preferences.length === 0 ? (
              <p className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm text-[#66726a]">{t("settings.noMemorySignals")}</p>
            ) : null}
            {(review?.memory.learned_preferences || []).map((item, index) => (
              <div className="rounded-lg border border-[#dfe8e2] px-3 py-2" key={`${item.action_type}-${index}`}>
                <p className="text-sm font-bold text-ink">{item.action_type}</p>
                <p className="mt-0.5 text-xs text-[#66726a]">
                  {item.kind}: {item.reason}
                </p>
              </div>
            ))}
          </div>
          <Button className="mt-3 w-full" variant="secondary" onClick={load} disabled={Boolean(busy)}>
            <RefreshCw className="h-4 w-4" /> {t("settings.refreshReview")}
          </Button>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <CalendarPlus className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.calendarIntegration")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.calendarIntegrationDescription")}</p>
          <div className="mt-4 grid gap-2">
            <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white" href={api.calendarExportUrl()}>
              <Download className="h-4 w-4" /> {t("settings.downloadIcs")}
            </a>
            <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss" href={api.calendarFeedUrl()}>
              <CalendarPlus className="h-4 w-4" /> {t("settings.subscribeIcs")}
            </a>
            <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss" href={webcalUrl(api.calendarFeedUrl())}>
              <CalendarPlus className="h-4 w-4" /> {t("settings.openWebcal")}
            </a>
            <Button variant="secondary" onClick={copyFeedUrl}>
              <Copy className="h-4 w-4" /> {copied ? t("settings.copied") : t("settings.copySubscription")}
            </Button>
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <UserRound className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.careProfile")}</h2>
          </div>
          <div className="mt-3 space-y-2 text-sm text-[#34423a]">
            <p>
              <span className="font-semibold">{t("common.patient")}:</span> {patient?.name || "Mdm Tan Siew Lan"}
            </p>
            <p>
              <span className="font-semibold">{t("settings.caregiver")}:</span> {patient?.caregiver || "Daughter, Elaine"}
            </p>
            <p>
              <span className="font-semibold">{t("settings.livingArrangement")}:</span> {patient?.living_arrangement || "Lives with daughter in Toa Payoh"}
            </p>
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.recordProcessing")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.recordProcessingDescription")}</p>
          <div className="mt-4 grid grid-cols-1 gap-2">
            <Button variant="secondary" onClick={rebuildRecords} disabled={Boolean(busy)}>
              <RotateCcw className="h-4 w-4" /> {t("settings.rebuild")}
            </Button>
          </div>
          {busy ? <p className="mt-3 text-sm font-semibold text-[#705a16]">{t("settings.rebuilding")}</p> : null}
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.traceability")}</h2>
          </div>
          <div className="mt-3 grid gap-2">
            <Link href="/audit" className="flex items-center justify-between rounded-lg border border-[#dfe8e2] px-3 py-3 text-sm font-semibold text-moss">
              <span className="inline-flex items-center gap-2">
                <FileClock className="h-4 w-4" /> {t("settings.reasoningTrail")}
              </span>
              <span aria-hidden="true">›</span>
            </Link>
            <Link href="/records" className="flex items-center justify-between rounded-lg border border-[#dfe8e2] px-3 py-3 text-sm font-semibold text-moss">
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4" /> {t("settings.recordProvenance")}
              </span>
              <span aria-hidden="true">›</span>
            </Link>
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.systemStatus")}</h2>
          </div>
          <div className="mt-3 flex items-center justify-between rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm">
            <span>{t("common.api")}</span>
            <span className="font-semibold text-moss">{health?.ok ? t("common.connected") : t("common.checking")}</span>
          </div>
          <div className="mt-2 flex items-center justify-between rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm">
            <span>{t("common.storage")}</span>
            <span className="font-semibold text-moss">{health?.store || t("common.checking")}</span>
          </div>
        </section>
      </section>
      <BottomNav />
    </>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-center">
      <span className="block text-lg font-black text-ink">{value}</span>
      <span className="mt-0.5 block text-[11px] font-bold text-[#66726a]">{label}</span>
    </div>
  );
}

function readCachedReview() {
  try {
    const stored = window.localStorage.getItem(CARE_REVIEW_CACHE_KEY);
    return stored ? (JSON.parse(stored) as CarePlanReview) : null;
  } catch {
    return null;
  }
}

function webcalUrl(url: string) {
  return url.replace(/^https?:\/\//, "webcal://");
}

function SettingsToggle({
  checked,
  description,
  icon,
  label,
  onChange
}: {
  checked: boolean;
  description: string;
  icon: ReactNode;
  label: string;
  onChange: () => void;
}) {
  return (
    <button aria-pressed={checked} className="flex w-full items-center gap-3 px-3 py-3 text-left" onClick={onChange} type="button">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-mint text-moss">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-bold text-ink">{label}</span>
        <span className="mt-0.5 block text-xs text-[#66726a]">{description}</span>
      </span>
      <span
        className={clsx(
          "relative h-7 w-12 shrink-0 rounded-full transition",
          checked ? "bg-moss" : "bg-[#cbd8cf]"
        )}
        aria-hidden="true"
      >
        <span
          className={clsx(
            "absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition",
            checked ? "left-6" : "left-1"
          )}
        />
      </span>
    </button>
  );
}
