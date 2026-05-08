"use client";

import { clsx } from "clsx";
import type { NodeStatus } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

export function StatusBadge({ status }: { status: NodeStatus }) {
  const { t } = useI18n();
  const label = t(`status.${status}`);
  return (
    <span
      className={clsx(
        "inline-flex rounded-full px-2.5 py-1 text-xs font-semibold",
        status === "pending_review" && "bg-[#fff3c4] text-[#7a5b00]",
        status === "approved" && "bg-[#d9f2e2] text-[#285b39]",
        status === "dismissed" && "bg-[#e6e8e6] text-[#68706a]",
        status === "edited" && "bg-[#e3edf8] text-[#24547a]"
      )}
    >
      {label}
    </span>
  );
}
