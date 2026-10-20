import { HistoryIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { useAccountCtx } from "@/components/layout/account-layout";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { dateTime, money, num, seconds } from "@/lib/format";
import { useActivity } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { JobStatus } from "./ad-detail";

const JOB: Record<string, string> = { pause: "توقف", resume: "فعال‌سازی", withdraw: "برداشت بودجه", topup: "شارژ" };

export function eventLabel(action: string): string {
  const fixed: Record<string, string> = {
    account_created: "ساخت حساب",
    app_settings: "تغییر تنظیمات کلی",
    settings: "تغییر تنظیمات حساب",
    bot_check_failed: "خطای اتصال ربات",
    bot_connection_set: "تنظیم اتصال ربات",
    bot_sync_warning: "هشدار همگام‌سازی ربات",
    claude_analysis: "تحلیل Claude",
    edit_ad: "ویرایش آگهی",
    create_ad: "ساخت آگهی",
    kill_switch: "توقف اضطراری",
    legacy_imported: "انتقال از نسخه‌ی ۱",
    login: "ورود",
    password_changed: "تغییر رمز",
    proposals: "پیشنهادهای تازه",
    reject: "رد پیشنهاد",
    tag_created: "ساخت برچسب",
    tag_deleted: "حذف برچسب",
    telegram_check_failed: "خطای اتصال Telegram Ads",
    telegram_token_removed: "حذف توکن Telegram Ads",
    telegram_token_set: "ثبت توکن Telegram Ads",
    text_analyzed: "تحلیل متن",
    text_created: "متن جدید",
    text_deleted: "حذف متن",
    text_versioned: "نسخه‌ی تازه‌ی متن",
    automation_paused: "توقف اجرای خودکار",
    automation_resumed: "ادامه‌ی اجرای خودکار",
  };
  if (fixed[action]) return fixed[action];
  const m = action.match(/^(approve|queue)_(\w+)$/);
  if (m) return `${m[1] === "approve" ? "تأیید" : "صف"} ${JOB[m[2]] ?? m[2]}`;
  const j = action.match(/^(pause|resume|withdraw|topup)_(done|failed|cancelled)$/);
  if (j) return `${JOB[j[1]]} ${j[2] === "done" ? "انجام شد" : j[2] === "failed" ? "ناموفق" : "لغو شد"}`;
  return action;
}

export default function ActivityPage() {
  const account = useAccountCtx();
  const { data, isLoading, error, refetch } = useActivity(account.slug);
  const [level, setLevel] = useState<"all" | "warn">("all");
  const cur = account.telegram.currency;
  const pending = (data?.jobs ?? []).filter((j) => j.status === "queued" || j.status === "running");
  const done = (data?.jobs ?? []).filter((j) => j.status !== "queued" && j.status !== "running");
  const events = (data?.events ?? []).filter((e) => level === "all" || e.level !== "info");

  return (
    <div className="space-y-5">
      <PageHeader title="فعالیت" description="صف کارها و گزارش هر اتفاقی که در این حساب افتاده است." />
      {error && <QueryError error={error} retry={() => refetch()} />}
      {isLoading && <Skeleton className="h-64" />}
      {data && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">صف کارها</CardTitle>
              <CardDescription>توقف، فعال‌سازی، برداشت و شارژ — به ترتیب اجرا</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {pending.length === 0 && done.length === 0 && (
                <p className="text-sm text-muted-foreground">هنوز کاری در صف نرفته است.</p>
              )}
              {[...pending, ...done].slice(0, 60).map((j) => {
                const wait = j.run_at - data.now;
                return (
                  <div key={j.id} className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">
                        {j.label ?? JOB[j.kind] ?? j.kind}
                        {j.amount ? <span className="num"> · {money(j.amount, cur)}</span> : null}{" "}
                        <Link to={`/accounts/${account.slug}/ads/${j.ad_id}`} className="text-xs font-normal text-muted-foreground hover:underline">
                          {j.target_label || `#${j.ad_id}`}
                        </Link>
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {j.status === "queued" && wait > 0 ? `اجرا تا ${seconds(Math.round(wait))} دیگر` : dateTime(j.created_ts)}
                        {(j.attempts ?? 0) > 1 && <span className="num"> · تلاش {num(j.attempts)}</span>}
                        {j.result && ` · ${j.result}`}
                      </div>
                    </div>
                    <JobStatus status={j.status} />
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                گزارش رویدادها
                <Tabs value={level} onValueChange={(v) => setLevel(v as "all" | "warn")}>
                  <TabsList className="h-8">
                    <TabsTrigger value="all" className="text-xs">همه</TabsTrigger>
                    <TabsTrigger value="warn" className="text-xs">هشدار و خطا</TabsTrigger>
                  </TabsList>
                </Tabs>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {events.length === 0 ? (
                <EmptyState icon={HistoryIcon} title="رویدادی نیست" />
              ) : (
                <ol className="relative space-y-3 border-s ps-4">
                  {events.map((e) => (
                    <li key={e.id} className="relative">
                      <span
                        className={cn(
                          "absolute -start-[21px] top-1.5 size-2.5 rounded-full border-2 border-card",
                          e.level === "error" ? "bg-destructive" : e.level === "warn" ? "bg-warning" : "bg-muted-foreground/50",
                        )}
                      />
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
                        <span className="font-medium">{eventLabel(e.action)}</span>
                        {e.actor !== "system" && (
                          <Badge variant="outline" className="text-[10px]">
                            {e.actor === "user" ? "شما" : e.actor === "rules" ? "قوانین" : e.actor}
                          </Badge>
                        )}
                        {e.ad_id && (
                          <Link to={`/accounts/${account.slug}/ads/${e.ad_id}`} className="num text-xs text-muted-foreground hover:underline">
                            #{e.ad_id}
                          </Link>
                        )}
                      </div>
                      {e.detail && <p className="text-xs leading-relaxed break-words text-muted-foreground">{e.detail}</p>}
                      <time className="text-[11px] text-muted-foreground/80">{dateTime(e.ts)}</time>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
