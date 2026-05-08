import { clsx } from "clsx";
import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "quiet" | "danger";
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-moss text-white hover:bg-ink",
        variant === "secondary" && "border border-[#cbd8cf] bg-white text-ink hover:bg-mint/60",
        variant === "quiet" && "text-moss hover:bg-mint/60",
        variant === "danger" && "bg-[#f4e5df] text-[#8d3d29] hover:bg-[#efd2c8]",
        className
      )}
      {...props}
    />
  );
}
