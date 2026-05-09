"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Bell, Check, RotateCcw, X } from "lucide-react";
import { clsx } from "clsx";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { AppNotification } from "@/lib/types";

const STORAGE_KEY = "caregiver-companion-notifications";
const PREFERENCES_KEY = "caregiver-companion-preferences";

type AppPreferences = {
  criticalAlerts: boolean;
  notificationBadges: boolean;
};

type NotificationStore = {
  dismissed: Record<string, string>;
  seen: Record<string, string>;
};

type Toast = AppNotification & {
  local?: boolean;
};

type NotificationInput = Pick<AppNotification, "title" | "body"> & Partial<AppNotification>;

type NotificationsContextValue = {
  notifications: AppNotification[];
  activeNotifications: AppNotification[];
  dismissedNotifications: Array<AppNotification & { dismissed_at: string }>;
  unreadCount: number;
  dismissNotification: (id: string) => void;
  restoreNotification: (id: string) => void;
  notify: (notification: NotificationInput) => void;
  refreshNotifications: (options?: { suppressToasts?: boolean }) => Promise<void>;
};

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [dismissed, setDismissed] = useState<Record<string, string>>({});
  const [seen, setSeen] = useState<Record<string, string>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [preferences, setPreferences] = useState<AppPreferences>({ criticalAlerts: true, notificationBadges: true });
  const [hydrated, setHydrated] = useState(false);
  const initialFetchDone = useRef(false);
  const dismissedRef = useRef(dismissed);
  const seenRef = useRef(seen);
  const preferencesRef = useRef(preferences);
  const storageTimer = useRef<number | null>(null);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as Partial<NotificationStore>;
        setDismissed(parsed.dismissed || {});
        setSeen(parsed.seen || {});
      }
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    function loadPreferences() {
      const stored = window.localStorage.getItem(PREFERENCES_KEY);
      if (!stored) {
        setPreferences({ criticalAlerts: true, notificationBadges: true });
        return;
      }
      try {
        const parsed = JSON.parse(stored) as Partial<AppPreferences>;
        setPreferences({
          criticalAlerts: parsed.criticalAlerts !== false,
          notificationBadges: parsed.notificationBadges !== false
        });
      } catch {
        setPreferences({ criticalAlerts: true, notificationBadges: true });
      }
    }

    loadPreferences();
    window.addEventListener("storage", loadPreferences);
    window.addEventListener("caregiver-companion-preferences-change", loadPreferences);
    return () => {
      window.removeEventListener("storage", loadPreferences);
      window.removeEventListener("caregiver-companion-preferences-change", loadPreferences);
    };
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    dismissedRef.current = dismissed;
    seenRef.current = seen;
    if (storageTimer.current) {
      window.clearTimeout(storageTimer.current);
    }
    storageTimer.current = window.setTimeout(() => {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ dismissed: dismissedRef.current, seen: seenRef.current }));
    }, 100);
    return () => {
      if (storageTimer.current) {
        window.clearTimeout(storageTimer.current);
      }
    };
  }, [dismissed, hydrated, seen]);

  useEffect(() => {
    preferencesRef.current = preferences;
  }, [preferences]);

  const removeToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const pushToast = useCallback(
    (notification: NotificationInput) => {
      const id = notification.id || `local:${Date.now()}:${Math.random().toString(16).slice(2)}`;
      const toast: Toast = {
        id,
        kind: notification.kind || "system",
        title: notification.title,
        body: notification.body,
        created_at: notification.created_at || new Date().toISOString(),
        href: notification.href,
        source_node_id: notification.source_node_id,
        node_status: notification.node_status,
        occurred_at: notification.occurred_at,
        local: !notification.id
      };
      setToasts((current) => [toast, ...current.filter((item) => item.id !== id)].slice(0, 3));
      window.setTimeout(() => removeToast(id), 6500);
    },
    [removeToast]
  );

  const refreshNotifications = useCallback(async (options?: { suppressToasts?: boolean }) => {
    const items = await api.notifications();
    setNotifications(items);

    const visible = items.filter((item) => !dismissedRef.current[item.id]);
    const newItems = visible.filter((item) => !seenRef.current[item.id]);
    if (newItems.length > 0) {
      if (!options?.suppressToasts) {
        const shouldToast = initialFetchDone.current ? newItems : newItems.slice(0, 2);
        shouldToast.filter((item) => preferencesRef.current.criticalAlerts || item.kind !== "review").forEach(pushToast);
      }
      const timestamp = new Date().toISOString();
      setSeen((current) => {
        const next = { ...current };
        for (const item of newItems) {
          next[item.id] = timestamp;
        }
        seenRef.current = next;
        return next;
      });
    }
    initialFetchDone.current = true;
  }, [pushToast]);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    refreshNotifications().catch(() => {
      pushToast({ title: t("notifications.syncFailed"), body: t("notifications.syncFailedBody"), kind: "system" });
    });
    const timer = window.setInterval(() => {
      refreshNotifications().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [hydrated, pushToast, refreshNotifications, t]);

  const dismissNotification = useCallback((id: string) => {
    setDismissed((current) => {
      const next = { ...current, [id]: new Date().toISOString() };
      dismissedRef.current = next;
      return next;
    });
  }, []);

  const restoreNotification = useCallback((id: string) => {
    setDismissed((current) => {
      const next = { ...current };
      delete next[id];
      dismissedRef.current = next;
      return next;
    });
  }, []);

  const value = useMemo<NotificationsContextValue>(() => {
    const activeNotifications = notifications
      .filter((item) => !dismissed[item.id])
      .sort((a, b) => {
        if (!preferences.criticalAlerts) {
          return 0;
        }
        const aPriority = a.kind === "review" ? 0 : 1;
        const bPriority = b.kind === "review" ? 0 : 1;
        return aPriority - bPriority;
      });
    const dismissedNotifications = notifications
      .filter((item) => dismissed[item.id])
      .map((item) => ({ ...item, dismissed_at: dismissed[item.id] }));

    return {
      notifications,
      activeNotifications,
      dismissedNotifications,
      unreadCount: activeNotifications.length,
      dismissNotification,
      restoreNotification,
      notify: pushToast,
      refreshNotifications
    };
  }, [dismissNotification, dismissed, notifications, preferences.criticalAlerts, pushToast, refreshNotifications, restoreNotification]);

  return (
    <NotificationsContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={removeToast} />
    </NotificationsContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationsContext);
  if (!context) {
    throw new Error("useNotifications must be used inside NotificationsProvider");
  }
  return context;
}

export function NotificationBell() {
  const { unreadCount } = useNotifications();
  const { t } = useI18n();
  const [showBadge, setShowBadge] = useState(true);

  useEffect(() => {
    function loadPreference() {
      const stored = window.localStorage.getItem(PREFERENCES_KEY);
      if (!stored) {
        setShowBadge(true);
        return;
      }
      try {
        const parsed = JSON.parse(stored) as { notificationBadges?: boolean };
        setShowBadge(parsed.notificationBadges !== false);
      } catch {
        setShowBadge(true);
      }
    }

    loadPreference();
    window.addEventListener("storage", loadPreference);
    window.addEventListener("caregiver-companion-preferences-change", loadPreference);
    return () => {
      window.removeEventListener("storage", loadPreference);
      window.removeEventListener("caregiver-companion-preferences-change", loadPreference);
    };
  }, []);

  return (
    <Link
      href="/notifications"
      className="relative inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#dfe8e2] bg-white text-moss shadow-sm"
      aria-label={t("notifications.title")}
    >
      <Bell className="h-5 w-5" aria-hidden="true" />
      {showBadge && unreadCount > 0 ? (
        <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-[#b6654b] px-1.5 py-0.5 text-center text-[10px] font-bold leading-none text-white">
          {unreadCount > 9 ? "9+" : unreadCount}
        </span>
      ) : null}
    </Link>
  );
}

function ToastViewport({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="fixed left-1/2 top-3 z-50 flex w-[calc(100vw-1.5rem)] max-w-[406px] -translate-x-1/2 flex-col gap-2">
      {toasts.map((toast) => (
        <SwipeToast toast={toast} onDismiss={onDismiss} key={toast.id} />
      ))}
    </div>
  );
}

function SwipeToast({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const { t } = useI18n();
  const toastRef = useRef<HTMLDivElement | null>(null);
  const startX = useRef<number | null>(null);
  const dragX = useRef(0);
  const frame = useRef<number | null>(null);

  function applyDrag(nextDragX: number) {
    dragX.current = nextDragX;
    if (frame.current) {
      return;
    }
    frame.current = window.requestAnimationFrame(() => {
      frame.current = null;
      const element = toastRef.current;
      if (!element) {
        return;
      }
      const offset = dragX.current;
      element.style.opacity = String(Math.max(0.45, 1 - Math.abs(offset) / 220));
      element.style.transform = `translateX(${offset}px) rotate(${offset / 28}deg)`;
    });
  }

  function resetDrag() {
    dragX.current = 0;
    const element = toastRef.current;
    if (!element) {
      return;
    }
    element.style.opacity = "1";
    element.style.transform = "translateX(0) rotate(0deg)";
  }

  return (
    <div
      ref={toastRef}
      className="rounded-xl border border-[#dfe8e2] bg-white p-3 shadow-lg transition-transform"
      onPointerDown={(event) => {
        startX.current = event.clientX;
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (startX.current === null) {
          return;
        }
        applyDrag(event.clientX - startX.current);
      }}
      onPointerUp={() => {
        if (Math.abs(dragX.current) > 96) {
          onDismiss(toast.id);
        }
        resetDrag();
        startX.current = null;
      }}
      onPointerCancel={() => {
        resetDrag();
        startX.current = null;
      }}
      role="status"
      style={{ touchAction: "pan-y" }}
    >
      <div className="flex items-start gap-3">
        <span
          className={clsx(
            "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
            toast.kind === "dismissed" ? "bg-[#f4e5df] text-[#8d3d29]" : "bg-mint text-moss"
          )}
        >
          {toast.kind === "dismissed" ? <X className="h-4 w-4" /> : <Check className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-ink">{toast.title}</p>
          <p className="mt-0.5 line-clamp-2 text-xs text-[#536159]">{toast.body}</p>
          {toast.href ? (
            <Link href={toast.href} className="mt-2 inline-flex text-xs font-semibold text-moss" onClick={() => onDismiss(toast.id)}>
              {t("notifications.view")}
            </Link>
          ) : null}
        </div>
        <button className="rounded-full p-1 text-[#6c756f] hover:bg-[#eef3ef]" onClick={() => onDismiss(toast.id)} aria-label={t("notifications.dismiss")}>
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
