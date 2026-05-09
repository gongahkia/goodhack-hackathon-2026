"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, BellRing, Check, MonitorSmartphone, Moon, RefreshCw, ShieldCheck, Smartphone, Sun, Wifi, X } from "lucide-react";
import { clsx } from "clsx";
import { useNotifications } from "@/components/notifications-provider";
import { api } from "@/lib/api";
import { languages, useI18n, type Language } from "@/lib/i18n";
import { useTheme, type ThemeMode } from "@/lib/theme";

type AppPreferences = {
  criticalAlerts: boolean;
  notificationBadges: boolean;
  offlineCache: boolean;
  breakBufferMinutes: number;
  restWindows: RestWindow[];
};
type RestWindow = { id: string; label: string; start: string; end: string; enabled: boolean };

const PREFERENCES_KEY = "caregiver-companion-preferences";
const defaultRestWindows: RestWindow[] = [{ id: "midday", label: "Protected rest", start: "12:00", end: "18:00", enabled: true }];
const defaultPreferences: AppPreferences = {
  criticalAlerts: true,
  notificationBadges: true,
  offlineCache: true,
  breakBufferMinutes: 10,
  restWindows: defaultRestWindows
};

const themeOptions = [
  { mode: "light", labelKey: "settings.theme.light", icon: Sun },
  { mode: "dark", labelKey: "settings.theme.dark", icon: Moon },
  { mode: "adaptive", labelKey: "settings.theme.adaptive", icon: MonitorSmartphone }
] satisfies Array<{ mode: ThemeMode; labelKey: string; icon: typeof Sun }>;

export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { language, setLanguage, t } = useI18n();
  const { mode, setMode } = useTheme();
  const { notify, refreshNotifications } = useNotifications();
  const [preferences, setPreferences] = useState<AppPreferences>(defaultPreferences);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    try {
      const stored = window.localStorage.getItem(PREFERENCES_KEY);
      setPreferences(stored ? { ...defaultPreferences, ...JSON.parse(stored) } : defaultPreferences);
    } catch {
      setPreferences(defaultPreferences);
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
    window.dispatchEvent(new Event("caregiver-companion-preferences-change"));
  }, [open, preferences]);

  function togglePreference(key: "criticalAlerts" | "notificationBadges" | "offlineCache") {
    setPreferences((current) => ({ ...current, [key]: !current[key] }));
  }

  function updateRestWindow(id: string, patch: Partial<RestWindow>) {
    setPreferences((current) => ({
      ...current,
      restWindows: current.restWindows.map((window) => (window.id === id ? { ...window, ...patch } : window))
    }));
  }

  async function refreshCareReview() {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.carePlanRereason();
      await refreshNotifications({ suppressToasts: true });
      setMessage(result.conclusion);
      notify({ title: t("settings.refreshReview"), body: result.conclusion, kind: "system", href: "/notifications" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-y-0 left-1/2 z-50 w-full max-w-[430px] -translate-x-1/2 bg-black/20 p-3 backdrop-blur-sm md:inset-y-6" role="dialog" aria-modal="true" aria-label={t("settings.title")}>
      <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[#dfe8e2] bg-white shadow-xl">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[#dfe8e2] px-4 py-4">
          <div>
            <p className="text-xs font-bold uppercase text-moss">Caregiver Companion</p>
            <h2 className="mt-1 text-xl font-bold text-ink">{t("settings.title")}</h2>
          </div>
          <button className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#dfe8e2] text-[#6c756f]" onClick={onClose} aria-label={t("reference.close")}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
          {message ? <div className="rounded-lg bg-mint p-3 text-sm font-semibold text-moss">{message}</div> : null}
          <section>
            <h3 className="font-bold">{t("settings.appearance")}</h3>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {themeOptions.map((item) => {
                const Icon = item.icon;
                const active = mode === item.mode;
                return (
                  <button
                    aria-pressed={active}
                    className={clsx("flex min-h-16 flex-col items-center justify-center gap-1 rounded-lg border px-2 text-xs font-bold", active ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] text-[#536159]")}
                    key={item.mode}
                    onClick={() => setMode(item.mode)}
                    type="button"
                  >
                    <Icon className="h-4 w-4" /> {t(item.labelKey)}
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <h3 className="font-bold">{t("settings.language")}</h3>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {languages.map((item) => (
                <button
                  className={clsx("rounded-lg border px-3 py-2 text-left text-sm font-semibold", language === item.code ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] text-[#536159]")}
                  key={item.code}
                  onClick={() => setLanguage(item.code as Language)}
                  type="button"
                >
                  <span className="block">{item.nativeLabel}</span>
                  <span className="text-xs font-normal">{item.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section>
            <div className="flex items-center gap-2">
              <Smartphone className="h-5 w-5 text-moss" />
              <h3 className="font-bold">{t("settings.appPreferences")}</h3>
            </div>
            <div className="mt-3 divide-y divide-[#e7ede9] rounded-lg border border-[#dfe8e2]">
              <ModalToggle checked={preferences.criticalAlerts} icon={<BellRing className="h-4 w-4" />} label={t("settings.criticalAlerts")} onChange={() => togglePreference("criticalAlerts")} />
              <ModalToggle checked={preferences.notificationBadges} icon={<Check className="h-4 w-4" />} label={t("settings.notificationBadges")} onChange={() => togglePreference("notificationBadges")} />
              <ModalToggle checked={preferences.offlineCache} icon={<Wifi className="h-4 w-4" />} label={t("settings.offlineCache")} onChange={() => togglePreference("offlineCache")} />
              <label className="flex items-center justify-between gap-3 p-3">
                <span>
                  <span className="block text-sm font-bold text-ink">{t("settings.breakBuffer")}</span>
                  <span className="mt-0.5 block text-xs text-[#66726a]">{t("settings.breakBufferDescription")}</span>
                </span>
                <input
                  className="h-10 w-20 rounded-lg border border-[#cbd8cf] bg-white px-3 text-right text-sm font-bold text-ink"
                  max={60}
                  min={0}
                  onChange={(event) =>
                    setPreferences((current) => ({
                      ...current,
                      breakBufferMinutes: Math.max(0, Math.min(60, Number(event.target.value) || 0))
                    }))
                  }
                  step={5}
                  type="number"
                  value={preferences.breakBufferMinutes}
                />
              </label>
            </div>
          </section>

          <section>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-moss" />
              <h3 className="font-bold">{t("settings.restWindows")}</h3>
            </div>
            <p className="mt-2 text-sm text-[#536159]">{t("settings.restWindowsDescription")}</p>
            <div className="mt-3 space-y-2">
              {preferences.restWindows.map((window) => (
                <div className="rounded-lg border border-[#dfe8e2] p-3" key={window.id}>
                  <div className="flex items-center justify-between gap-3">
                    <input
                      className="min-w-0 flex-1 rounded-lg border border-[#cbd8cf] px-3 py-2 text-sm font-bold text-ink"
                      onChange={(event) => updateRestWindow(window.id, { label: event.target.value })}
                      value={window.label}
                    />
                    <button className={clsx("h-6 w-11 rounded-full p-1 transition", window.enabled ? "bg-moss" : "bg-[#dfe8e2]")} onClick={() => updateRestWindow(window.id, { enabled: !window.enabled })} type="button">
                      <span className={clsx("block h-4 w-4 rounded-full bg-white transition", window.enabled ? "translate-x-5" : "translate-x-0")} />
                    </button>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <input className="rounded-lg border border-[#cbd8cf] px-3 py-2 text-sm font-bold text-ink" onChange={(event) => updateRestWindow(window.id, { start: event.target.value })} type="time" value={window.start} />
                    <input className="rounded-lg border border-[#cbd8cf] px-3 py-2 text-sm font-bold text-ink" onChange={(event) => updateRestWindow(window.id, { end: event.target.value })} type="time" value={window.end} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-moss" />
              <h3 className="font-bold">{t("settings.careIntelligence")}</h3>
            </div>
            <p className="mt-2 text-sm text-[#536159]">{t("settings.careIntelligenceDescription")}</p>
            <button
              className="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss disabled:opacity-60"
              disabled={busy}
              onClick={refreshCareReview}
              type="button"
            >
              <RefreshCw className="h-4 w-4" /> {t("settings.refreshReview")}
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}

function ModalToggle({ checked, icon, label, onChange }: { checked: boolean; icon: ReactNode; label: string; onChange: () => void }) {
  return (
    <button className="flex w-full items-center justify-between gap-3 p-3 text-left" onClick={onChange} type="button">
      <span className="inline-flex items-center gap-2 text-sm font-bold text-ink">
        <span className="text-moss">{icon}</span>
        {label}
      </span>
      <span className={clsx("h-6 w-11 rounded-full p-1 transition", checked ? "bg-moss" : "bg-[#dfe8e2]")}>
        <span className={clsx("block h-4 w-4 rounded-full bg-white transition", checked ? "translate-x-5" : "translate-x-0")} />
      </span>
    </button>
  );
}
