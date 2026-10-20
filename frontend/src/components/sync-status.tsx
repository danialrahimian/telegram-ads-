import { RefreshCwIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNow } from "@/hooks/use-now";
import { api } from "@/lib/api";
import { ago, seconds } from "@/lib/format";
import { accountApi, keys, useAction } from "@/lib/queries";
import type { Account, SyncKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_LABEL: Record<SyncKind, string> = { fast: "آگهی‌ها", stats: "آمار روزانه", bot: "ربات فروش" };
const INTERVAL_KEY = { fast: "sync_fast_seconds", stats: "sync_stats_seconds", bot: "sync_bot_seconds" } as const;

export function SyncStatus({ account }: { account: Account }) {
  const now = useNow(5000);
  const sync = useAction<void, { started: string[]; errors?: string[] }>({
    fn: () => api.post(`${accountApi(account.slug)}/sync`, { kind: "all" }),
    invalidate: [keys.acc(account.slug), keys.accounts],
    success: (r) =>
      r.errors?.length ? null : r.started.length ? "همگام‌سازی شروع شد." : "همگام‌سازی از قبل در حال اجراست.",
    onSuccess: (r) => {
      if (r.errors?.length) toast.error(r.errors.join("\n"));
    },
  });
  const kinds: SyncKind[] = account.bot.configured ? ["fast", "stats", "bot"] : ["fast", "stats"];
  const busy = account.syncing.length > 0 || sync.isPending;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {kinds.map((k) => {
        const st = account.sync[k];
        const running = account.syncing.includes(k);
        const failed = !!st?.error;
        return (
          <Tooltip key={k}>
            <TooltipTrigger asChild>
              <span className="inline-flex cursor-default items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className={cn(
                    "size-1.5 rounded-full",
                    running ? "animate-pulse bg-info" : failed ? "bg-destructive" : st?.last_ok ? "bg-success" : "bg-muted-foreground/40",
                  )}
                />
                {KIND_LABEL[k]}: <span className="num">{running ? "در حال اجرا…" : ago(st?.last_ok, now)}</span>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div>هر {seconds(account.settings[INTERVAL_KEY[k]])} یک بار</div>
              {failed && <div className="mt-1 text-destructive-foreground/90">آخرین خطا: {st?.error}</div>}
            </TooltipContent>
          </Tooltip>
        );
      })}
      <Button
        size="sm"
        variant="outline"
        disabled={busy || !account.telegram.configured}
        onClick={() => sync.mutate()}
      >
        <RefreshCwIcon className={cn(busy && "animate-spin")} />
        همگام‌سازی
      </Button>
    </div>
  );
}
