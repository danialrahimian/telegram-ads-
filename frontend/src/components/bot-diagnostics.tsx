import { CheckCircle2Icon, CircleXIcon, ClipboardCopyIcon, StethoscopeIcon, TriangleAlertIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { ago, num } from "@/lib/format";
import { accountApi, keys, useAction, useBotDiag } from "@/lib/queries";
import type { Account, DiagReport, SyncPart } from "@/lib/types";
import { cn } from "@/lib/utils";

/** "Bot connection diagnostics": every request the panel needs, its result and a cause with a fix. */
export function BotDiagnostics({ account }: { account: Account }) {
  const last = useBotDiag(account.slug);
  const [fresh, setFresh] = useState<{ report: DiagReport; text: string } | null>(null);
  const run = useAction<void, { report: DiagReport; text: string }>({
    fn: () => api.post(`${accountApi(account.slug)}/bot/diagnose`),
    invalidate: [[...keys.acc(account.slug), "bot-diag"]],
    success: (r) => (r.report.failed ? `${num(r.report.failed)} درخواست ناموفق بود؛ جزئیات را ببینید.` : "همه‌ی درخواست‌ها سالم‌اند."),
    onSuccess: (r) => setFresh(r),
  });
  const data = fresh ?? (last.data?.report ? { report: last.data.report, text: last.data.text } : null);
  const copy = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.text);
      toast.success("گزارش (بدون کلید API) کپی شد.");
    } catch {
      toast.error("کپی نشد؛ دستی انتخاب کنید.");
    }
  };
  return (
    <div className="space-y-3 rounded-lg border p-3" id="bot-diag">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">عیب‌یابی اتصال ربات</div>
          <div className="text-xs text-muted-foreground">
            هر درخواستی که پنل لازم دارد جدا امتحان می‌شود{data ? ` · آخرین: ${ago(data.report.ts)}` : ""}.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => run.mutate()} disabled={run.isPending || !account.bot.configured}>
            <StethoscopeIcon className={run.isPending ? "animate-pulse" : ""} />
            {run.isPending ? "در حال بررسی…" : "عیب‌یابی اتصال ربات"}
          </Button>
          {data && (
            <Button size="sm" variant="ghost" onClick={copy}>
              <ClipboardCopyIcon /> کپی گزارش برای توسعه‌دهنده‌ی ربات
            </Button>
          )}
        </div>
      </div>
      <SyncParts account={account} />
      {data && <ReportView report={data.report} />}
    </div>
  );
}

function ReportView({ report }: { report: DiagReport }) {
  const id = report.identity;
  return (
    <div className="space-y-2" data-testid="bot-diag">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={report.failed ? "warning" : "success"} className="num">
          {num(report.ok)} سالم · {num(report.failed)} ناموفق
        </Badge>
        <span className="text-muted-foreground">
          کاربران ربات (statbot): <span className="num">{id.count_user == null ? "—" : num(id.count_user)}</span> · نام کاربری
          واردشده: <span className="ltr">@{id.configured_username || "—"}</span>
          {id.reported_username && (
            <>
              {" "}
              · نام گزارش‌شده توسط ربات: <span className="ltr">@{id.reported_username}</span>
            </>
          )}
        </span>
      </div>
      {report.warnings.map((w) => (
        <Alert key={w} variant="warning">
          <TriangleAlertIcon />
          <AlertDescription>{w}</AlertDescription>
        </Alert>
      ))}
      <ul className="space-y-1.5">
        {report.rows.map((r) => (
          <li key={r.name} className="rounded-md border px-3 py-2 text-sm">
            <div className="flex items-start gap-2">
              {r.ok ? (
                <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-success" />
              ) : (
                <CircleXIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2">
                  <span className="font-medium">{r.label}</span>
                  <span className={cn("text-xs", r.ok ? "text-muted-foreground" : "text-destructive")}>{r.cause.title}</span>
                </div>
                {!r.ok && r.cause.fix && <p className="text-xs leading-relaxed text-muted-foreground">{r.cause.fix}</p>}
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-muted-foreground">جزئیات فنی</summary>
                  <div className="mt-1 space-y-0.5 ltr text-left wrap-anywhere">
                    <div>
                      {r.method} {r.path} {r.action && `actions=${r.action}`}
                    </div>
                    <div>body: {JSON.stringify(r.body)}</div>
                    <div>
                      HTTP {r.http_status ?? "—"} · {r.elapsed_ms} ms
                      {r.rows != null && ` · rows: ${r.rows}`}
                    </div>
                    {r.msg && <div>msg: {r.msg}</div>}
                    {r.excerpt && <div>response: {r.excerpt}</div>}
                    {r.fields.length > 0 && <div>fields: {r.fields.join(", ")}</div>}
                  </div>
                </details>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const PART_LABEL: Record<string, string> = { stats: "آمار", transactions: "تراکنش‌ها" };

/** Result of each part of the last bot sync (stats, ledger, each referral tag). */
export function SyncParts({ account }: { account: Account }) {
  const parts = account.sync.bot?.parts;
  if (!parts) return null;
  const list: [string, SyncPart][] = [];
  if (parts.stats) list.push(["stats", parts.stats]);
  if (parts.transactions) list.push(["transactions", parts.transactions]);
  for (const [tagId, p] of Object.entries(parts.tags ?? {})) list.push([`tag-${tagId}`, p]);
  return (
    <div className="space-y-1 text-xs" data-testid="bot-sync-parts">
      <div className="text-muted-foreground">آخرین همگام‌سازی ربات ({ago(account.sync.bot?.last_try)}):</div>
      {list.map(([k, p]) => (
        <div key={k} className="flex flex-wrap items-center gap-1.5">
          <span className={cn("size-1.5 rounded-full", p.ok ? (p.code === "ok_empty" ? "bg-warning" : "bg-success") : "bg-destructive")} />
          <span className="font-medium">{PART_LABEL[k] ?? `رفرال معرف ${p.referrer ?? k.slice(4)}`}:</span>
          <span className="text-muted-foreground">
            {p.title}
            {p.rows != null && ` (${num(p.rows)} ردیف)`}
            {p.mode === "per_type" && " — بر اساس نوع خرید"}
          </span>
          {p.code === "ok_empty" && p.filters && (
            <span className="text-muted-foreground">
              — فیلترها: از <span className="num">{p.filters.from ? new Date(p.filters.from * 1000).toLocaleDateString("fa-IR") : "ابتدا"}</span>،
              نوع‌های خرید: <span className="ltr">{(p.filters.purchase_types ?? []).join(", ") || "—"}</span>
            </span>
          )}
          {p.warning && <span className="text-warning">{p.warning}</span>}
          {!p.ok && p.fix && <span className="text-muted-foreground">— {p.fix}</span>}
        </div>
      ))}
    </div>
  );
}
