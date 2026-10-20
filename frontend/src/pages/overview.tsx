import { ArrowLeftIcon, LightbulbIcon, PlusIcon, WalletIcon } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { HealthBadge } from "@/components/health";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useNow } from "@/hooks/use-now";
import { ago, delta, money, num, pct } from "@/lib/format";
import { useOverview } from "@/lib/queries";
import type { OverviewAccount } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function OverviewPage() {
  const { data, isLoading, error, refetch } = useOverview();
  const accounts = data?.accounts ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="نمای کلی"
        description="هر حساب تبلیغاتی مسیر، داشبورد و تحلیل جداگانه‌ی خودش را دارد."
        actions={
          <Button asChild>
            <Link to="/accounts/new">
              <PlusIcon /> افزودن حساب
            </Link>
          </Button>
        }
      />
      {error && <QueryError error={error} retry={() => refetch()} />}
      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      )}
      {!isLoading && !error && accounts.length === 0 && (
        <EmptyState
          icon={WalletIcon}
          title="هنوز حسابی اضافه نشده"
          description="برای هر ربات (مثلاً سایکونت و دروازه آزادی) یک حساب بسازید، سپس توکن Telegram Ads و کلید API ربات را در صفحه‌ی اتصال وارد کنید."
          action={
            <Button asChild>
              <Link to="/accounts/new">
                <PlusIcon /> ساخت اولین حساب
              </Link>
            </Button>
          }
        />
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map((a) => (
          <AccountCard key={a.id} a={a} />
        ))}
      </div>
    </div>
  );
}

function AccountCard({ a }: { a: OverviewAccount }) {
  const now = useNow(10_000);
  const s = a.summary;
  const w = s?.["7"];
  const cur = a.telegram.currency;
  const cps = w?.cps ?? null;
  const cpsBad = cps !== null && cps > a.settings.stop_cost_per_start;
  return (
    <Card data-accent={a.color} className="overflow-hidden pt-0">
      <div className="h-1 w-full" style={{ background: "var(--acc)" }} />
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span
            className="flex size-7 items-center justify-center rounded-md text-xs font-bold text-white"
            style={{ background: "var(--acc)" }}
          >
            {a.name.slice(0, 1)}
          </span>
          {a.name}
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-xs">Telegram Ads</span>
          <HealthBadge status={a.telegram.status} configured={a.telegram.configured} />
          <span className="ms-1 text-xs">ربات</span>
          <HealthBadge status={a.bot.status} configured={a.bot.configured} />
        </CardDescription>
        <CardAction>
          {a.pending_proposals > 0 && (
            <Badge variant="warning" asChild>
              <Link to={`/accounts/${a.slug}/proposals`}>
                <LightbulbIcon /> {num(a.pending_proposals)} پیشنهاد
              </Link>
            </Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent>
        {!s || !w ? (
          <p className="text-sm text-muted-foreground">
            {a.telegram.configured ? "در انتظار اولین همگام‌سازی…" : "اتصال Telegram Ads تنظیم نشده است."}
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            <Metric label="خرج ۷ روز" value={money(w.spent, cur)} change={delta(w.spent, w.prev_spent)} neutral />
            <Metric label="استارت ربات" value={num(w.starts)} change={delta(w.starts, w.prev_starts)} />
            <Metric
              label="هزینه هر استارت"
              value={money(cps, cur)}
              change={delta(cps, w.prev_cps)}
              goodWhen="down"
              tone={cpsBad ? "bad" : undefined}
            />
            <Metric label="خریدار (۷ روز)" value={num(w.buyers)} change={delta(w.buyers, w.prev_buyers)} />
            <Metric label="کاربر جدید ربات" value={num(w.new_users)} />
            <Metric label="موجودی حساب" value={money(s.balance.account, cur)} />
          </div>
        )}
        {s && (
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              آگهی فعال: <b className="num text-foreground">{num(s.counts.running)}</b>
            </span>
            <span>
              در بررسی: <b className="num text-foreground">{num(s.counts.review)}</b>
            </span>
            {s.attributed_28.buyers > 0 && (
              <span>
                هزینه هر مشتری (رفرال، ۲۸ روز):{" "}
                <b className="num text-foreground">{money(s.attributed_28.cpp, cur)}</b>
              </span>
            )}
          </div>
        )}
      </CardContent>
      <CardFooter className="mt-auto justify-between gap-2 border-t pt-4 text-xs text-muted-foreground">
        <span>آخرین همگام‌سازی: {ago(a.sync.fast?.last_ok, now)}</span>
        <Button asChild size="sm" variant="secondary">
          <Link to={`/accounts/${a.slug}`}>
            داشبورد <ArrowLeftIcon />
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function Metric({
  label,
  value,
  change,
  goodWhen = "up",
  neutral,
  tone,
}: {
  label: string;
  value: string;
  change?: number | null;
  goodWhen?: "up" | "down";
  neutral?: boolean;
  tone?: "bad";
}) {
  const good = change == null ? null : goodWhen === "up" ? change >= 0 : change <= 0;
  return (
    <div className="min-w-0">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className={cn("num truncate text-base font-semibold", tone === "bad" && "text-destructive")}>{value}</div>
      {change != null && Number.isFinite(change) && (
        <div
          className={cn(
            "num text-[11px]",
            neutral ? "text-muted-foreground" : good ? "text-success" : "text-destructive",
          )}
        >
          {change >= 0 ? "▲" : "▼"} {pct(Math.abs(change))}
        </div>
      )}
    </div>
  );
}
