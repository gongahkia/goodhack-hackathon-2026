"use client";

import Link from "next/link";
import { useState } from "react";
import { BellOff, ExternalLink, RotateCcw, X } from "lucide-react";
import { clsx } from "clsx";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AppNotification } from "@/lib/types";
import { useNotifications } from "@/components/notifications-provider";

type NotificationTab = "active" | "dismissed";

export default function NotificationsPage() {
  const { t, dateLocale } = useI18n();
  const { activeNotifications, dismissedNotifications, dismissNotification, restoreNotification } = useNotifications();
  const [tab, setTab] = useState<NotificationTab>("active");
  const items = tab === "active" ? activeNotifications : dismissedNotifications;

  return (
    <>
      <AppHeader title={t("notifications.title")} subtitle={t("notifications.subtitle")} />
      <section className="flex-1 space-y-4 px-4 pb-4">
        <div className="grid grid-cols-2 rounded-xl border border-[#dfe8e2] bg-white p-1">
          {(["active", "dismissed"] as NotificationTab[]).map((item) => (
            <button
              className={clsx("rounded-lg px-3 py-2 text-sm font-semibold", tab === item ? "bg-mint text-moss" : "text-[#66726a]")}
              key={item}
              onClick={() => setTab(item)}
            >
              {t(`notifications.${item}`)}
            </button>
          ))}
        </div>

        {items.length === 0 ? (
          <div className="rounded-xl border border-[#dfe8e2] bg-white p-6 text-center">
            <BellOff className="mx-auto h-8 w-8 text-[#9aa69f]" />
            <p className="mt-3 text-sm font-semibold text-[#536159]">
              {tab === "active" ? t("notifications.emptyActive") : t("notifications.emptyDismissed")}
            </p>
          </div>
        ) : null}

        <div className="space-y-3">
          {items.map((notification) => (
            <NotificationCard
              key={notification.id}
              notification={notification}
              dateLocale={dateLocale}
              onDismiss={() => dismissNotification(notification.id)}
              onRestore={() => restoreNotification(notification.id)}
              dismissed={tab === "dismissed"}
            />
          ))}
        </div>
      </section>
      <BottomNav />
    </>
  );
}

function NotificationCard({
  notification,
  dateLocale,
  dismissed,
  onDismiss,
  onRestore
}: {
  notification: AppNotification;
  dateLocale: string;
  dismissed: boolean;
  onDismiss: () => void;
  onRestore: () => void;
}) {
  const { t } = useI18n();
  return (
    <article className={clsx("rounded-xl border bg-white p-4", dismissed ? "border-[#e0e3e1] opacity-80" : "border-[#dfe8e2]")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase text-moss">{notification.kind.replace("_", " ")}</p>
          <h2 className="mt-1 font-bold text-ink">{notification.title}</h2>
          <p className="mt-1 text-sm text-[#536159]">{notification.body}</p>
          <p className="mt-2 text-xs text-[#66726a]">
            {t("notifications.sentAt")} · {formatDate(notification.created_at, dateLocale)}
          </p>
        </div>
        <span className={clsx("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", dismissed ? "bg-[#b8c0ba]" : "bg-[#b6654b]")} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {notification.href ? (
          <Link className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white" href={notification.href}>
            {t("notifications.view")} <ExternalLink className="h-4 w-4" />
          </Link>
        ) : null}
        {dismissed ? (
          <Button variant="secondary" onClick={onRestore}>
            <RotateCcw className="h-4 w-4" /> {t("notifications.restore")}
          </Button>
        ) : (
          <Button variant="quiet" onClick={onDismiss}>
            <X className="h-4 w-4" /> {t("notifications.dismiss")}
          </Button>
        )}
      </div>
    </article>
  );
}
