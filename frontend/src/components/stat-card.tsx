import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  change,
  goodWhen = "up",
  icon: Icon,
  tone,
  loading,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  change?: number | null;
  goodWhen?: "up" | "down" | "neutral";
  icon?: React.ComponentType<{ className?: string }>;
  tone?: "good" | "bad" | "warn";
  loading?: boolean;
  className?: string;
}) {
  const good = change == null || goodWhen === "neutral" ? null : goodWhen === "up" ? change >= 0 : change <= 0;
  return (
    <Card className={cn("gap-2 px-4 py-4", className)}>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">{label}</span>
        {Icon && <Icon className="size-4 shrink-0 opacity-70" />}
      </div>
      {loading ? (
        <Skeleton className="h-7 w-24" />
      ) : (
        <div
          className={cn(
            "num truncate text-xl font-bold tracking-tight sm:text-2xl",
            tone === "good" && "text-success",
            tone === "bad" && "text-destructive",
            tone === "warn" && "text-warning",
          )}
        >
          {value}
        </div>
      )}
      <div className="flex min-h-4 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {change != null && Number.isFinite(change) && (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 font-medium",
              good === null ? "text-muted-foreground" : good ? "text-success" : "text-destructive",
            )}
            title="نسبت به دوره‌ی قبل"
          >
            {change >= 0 ? <ArrowUpIcon className="size-3" /> : <ArrowDownIcon className="size-3" />}
            {pct(Math.abs(change))}
          </span>
        )}
        {hint && <span className="truncate">{hint}</span>}
      </div>
    </Card>
  );
}
