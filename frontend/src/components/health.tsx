import { Badge } from "@/components/ui/badge";
import type { Health } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL: Record<string, string> = { ok: "سالم", warn: "ناقص", error: "خطا", unset: "تنظیم نشده" };

export function HealthDot({ status, className }: { status: Health; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        status === "ok" && "bg-success",
        status === "warn" && "bg-warning",
        status === "error" && "bg-destructive",
        (!status || status === "unset") && "bg-muted-foreground/40",
        className,
      )}
    />
  );
}

export function HealthBadge({ status, configured = true }: { status: Health; configured?: boolean }) {
  const s = configured ? status || "unset" : "unset";
  const variant = s === "ok" ? "success" : s === "warn" ? "warning" : s === "error" ? "destructive" : "secondary";
  return (
    <Badge variant={variant}>
      <HealthDot status={s} />
      {s === "unset" && configured ? "بررسی نشده" : LABEL[s] ?? s}
    </Badge>
  );
}
