import { ArrowDownWideNarrowIcon, MegaphoneIcon, PlusIcon, SearchIcon, TagIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { AdActions } from "@/components/ad-actions";
import { AdStatusBadge, placementLabel } from "@/components/ad-status";
import { EmptyState } from "@/components/empty-state";
import { useAccountCtx } from "@/components/layout/account-layout";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { currencyLabel, money, num, pct } from "@/lib/format";
import { useAds } from "@/lib/queries";
import type { AdRow, AdWindow } from "@/lib/types";
import { cn } from "@/lib/utils";

type StatusFilter = "all" | "running" | "review" | "stopped" | "declined";
type SortKey = "spent" | "starts" | "cps" | "remaining" | "newest" | "buyers";

function windowed(a: AdRow, w: AdWindow) {
  if (w === "all") return { spent: a.spent, starts: a.starts, clicks: a.clicks, views: a.views, cps: a.cps };
  const k = w as "7" | "28" | "since";
  return {
    spent: a[`spent_${k}`],
    starts: a[`starts_${k}`],
    clicks: a[`clicks_${k}`],
    views: a[`views_${k}`],
    cps: a[`cps_${k}`],
  };
}

function matchStatus(a: AdRow, f: StatusFilter) {
  if (f === "all") return true;
  if (f === "running") return a.running;
  if (f === "review") return a.status === "in_review" || a.status === "ready_for_review";
  if (f === "declined") return a.status === "declined";
  return a.status === "stopped" || a.is_paused;
}

export default function AdsPage() {
  const account = useAccountCtx();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const win = (params.get("w") as AdWindow) || "7";
  const status = (params.get("status") as StatusFilter) || "all";
  const sort = (params.get("sort") as SortKey) || "spent";
  const since = params.get("since") || "";
  const [q, setQ] = useState("");
  const { data, isLoading, error, refetch } = useAds(account.slug, win === "since" && since ? since : undefined);
  const cur = account.telegram.currency;
  const stopCps = account.settings.stop_cost_per_start;

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    const list = (data?.ads ?? []).filter(
      (a) =>
        matchStatus(a, status) &&
        (!term ||
          String(a.ad_id).includes(term) ||
          a.text.toLowerCase().includes(term) ||
          a.target_label.toLowerCase().includes(term) ||
          (a.tag_name ?? "").toLowerCase().includes(term)),
    );
    const val = (a: AdRow) => {
      const w = windowed(a, win);
      switch (sort) {
        case "starts":
          return w.starts;
        case "cps":
          return w.cps ?? Number.POSITIVE_INFINITY;
        case "remaining":
          return a.remaining;
        case "buyers":
          return a.buyers ?? -1;
        case "newest":
          return a.created_date;
        default:
          return w.spent;
      }
    };
    return [...list].sort((a, b) => (sort === "cps" ? val(a) - val(b) : val(b) - val(a)));
  }, [data, q, status, sort, win]);

  const counts = useMemo(() => {
    const all = data?.ads ?? [];
    return {
      all: all.length,
      running: all.filter((a) => matchStatus(a, "running")).length,
      review: all.filter((a) => matchStatus(a, "review")).length,
      stopped: all.filter((a) => matchStatus(a, "stopped")).length,
      declined: all.filter((a) => matchStatus(a, "declined")).length,
    };
  }, [data]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="آگهی‌ها"
        description="همه‌ی آگهی‌های این حساب با آمار، برچسب رفرال و فروش هر کدام."
        actions={
          <Button asChild>
            <Link to="new">
              <PlusIcon /> آگهی جدید
            </Link>
          </Button>
        }
      />

      <div className="flex flex-col gap-3">
        <Tabs value={status} onValueChange={(v) => set("status", v === "all" ? "" : v)}>
          <TabsList className="w-full justify-start sm:w-fit">
            {(
              [
                ["all", "همه"],
                ["running", "فعال"],
                ["review", "در بررسی"],
                ["stopped", "متوقف"],
                ["declined", "رد شده"],
              ] as const
            ).map(([k, label]) => (
              <TabsTrigger key={k} value={k} className="flex-none">
                {label} <span className="num text-xs text-muted-foreground">{num(counts[k])}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1 basis-56">
            <SearchIcon className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="جستجو در متن، جایگاه، برچسب یا شماره…"
              className="ps-8"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <Select value={win} onValueChange={(v) => set("w", v === "7" ? "" : v)}>
            <SelectTrigger className="w-36" aria-label="بازه">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">۷ روز اخیر</SelectItem>
              <SelectItem value="28">۲۸ روز اخیر</SelectItem>
              <SelectItem value="all">کل عمر آگهی</SelectItem>
              <SelectItem value="since">از تاریخ…</SelectItem>
            </SelectContent>
          </Select>
          {win === "since" && (
            <Input
              type="date"
              dir="ltr"
              className="w-40"
              value={since}
              onChange={(e) => set("since", e.target.value)}
              aria-label="از تاریخ"
            />
          )}
          <Select value={sort} onValueChange={(v) => set("sort", v === "spent" ? "" : v)}>
            <SelectTrigger className="w-40" aria-label="مرتب‌سازی">
              <ArrowDownWideNarrowIcon />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="spent">بیشترین خرج</SelectItem>
              <SelectItem value="starts">بیشترین استارت</SelectItem>
              <SelectItem value="cps">ارزان‌ترین استارت</SelectItem>
              <SelectItem value="buyers">بیشترین خریدار</SelectItem>
              <SelectItem value="remaining">بیشترین بودجه</SelectItem>
              <SelectItem value="newest">جدیدترین</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {error && <QueryError error={error} retry={() => refetch()} />}
      {isLoading && <Skeleton className="h-96" />}
      {!isLoading && !error && rows.length === 0 && (
        <EmptyState
          icon={MegaphoneIcon}
          title={data?.ads.length ? "آگهی‌ای با این فیلتر نیست" : "هنوز آگهی‌ای خوانده نشده"}
          description={data?.ads.length ? undefined : "بعد از اولین همگام‌سازی، آگهی‌های حساب اینجا می‌آیند."}
        />
      )}

      {rows.length > 0 && (
        <>
          {/* Desktop table */}
          <Card className="hidden py-0 md:flex">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>آگهی</TableHead>
                  <TableHead>وضعیت</TableHead>
                  <TableHead className="text-end">خرج</TableHead>
                  <TableHead className="text-end">استارت</TableHead>
                  <TableHead className="text-end">هر استارت</TableHead>
                  <TableHead className="text-end">CTR</TableHead>
                  <TableHead className="text-end">خریدار</TableHead>
                  <TableHead className="text-end">بودجه</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((a) => {
                  const w = windowed(a, win);
                  return (
                    <TableRow
                      key={a.ad_id}
                      className="cursor-pointer"
                      onClick={(e) => {
                        if ((e.target as HTMLElement).closest("button,a,[role=menuitem]")) return;
                        nav(String(a.ad_id));
                      }}
                    >
                      <TableCell className="max-w-[22rem] whitespace-normal">
                        <div className="flex items-center gap-1.5">
                          <Link to={String(a.ad_id)} className="truncate font-medium hover:underline">
                            {a.target_label || a.title || `#${a.ad_id}`}
                          </Link>
                          <Badge variant="outline" className="shrink-0 text-[10px]">
                            {placementLabel(a.placement)}
                          </Badge>
                        </div>
                        <div className="line-clamp-1 text-xs text-muted-foreground wrap-anywhere">{a.text}</div>
                        {a.tag_name && (
                          <div className="mt-0.5 flex items-center gap-1 text-[11px] text-info">
                            <TagIcon className="size-3" /> {a.tag_name}
                            {a.tag_shared && <span className="text-muted-foreground">(مشترک)</span>}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <AdStatusBadge status={a.status} paused={a.is_paused} />
                      </TableCell>
                      <TableCell className="num text-end">{money(w.spent, cur)}</TableCell>
                      <TableCell className="num text-end">{num(w.starts)}</TableCell>
                      <TableCell
                        className={cn("num text-end", w.cps != null && w.cps > stopCps && a.has_stats && "text-destructive")}
                      >
                        {money(w.cps, cur)}
                      </TableCell>
                      <TableCell className="num text-end">{pct(w.views ? w.clicks / w.views : null)}</TableCell>
                      <TableCell className="num text-end">{a.buyers == null ? "—" : num(a.buyers)}</TableCell>
                      <TableCell className="num text-end">{money(a.remaining, cur)}</TableCell>
                      <TableCell>
                        <AdActions account={account} ad={a} compact />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Card>

          {/* Mobile cards */}
          <div className="grid gap-2 md:hidden">
            {rows.map((a) => {
              const w = windowed(a, win);
              return (
                <Card key={a.ad_id} className="gap-3 px-4 py-3">
                  <div className="flex items-start gap-2">
                    <Link to={String(a.ad_id)} className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium">{a.target_label || a.title || `#${a.ad_id}`}</span>
                        <Badge variant="outline" className="shrink-0 text-[10px]">
                          {placementLabel(a.placement)}
                        </Badge>
                      </div>
                      <div className="line-clamp-2 text-xs text-muted-foreground wrap-anywhere">{a.text}</div>
                    </Link>
                    <AdActions account={account} ad={a} compact />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <AdStatusBadge status={a.status} paused={a.is_paused} />
                    {a.tag_name && (
                      <Badge variant="info">
                        <TagIcon /> {a.tag_name}
                      </Badge>
                    )}
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-center text-xs">
                    <MiniStat label={`خرج ${currencyLabel(cur)}`} value={money(w.spent)} />
                    <MiniStat label="استارت" value={num(w.starts)} />
                    <MiniStat
                      label="هر استارت"
                      value={money(w.cps)}
                      bad={w.cps != null && w.cps > stopCps && a.has_stats}
                    />
                    <MiniStat label={`بودجه ${currencyLabel(cur)}`} value={money(a.remaining)} />
                  </div>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function MiniStat({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-md bg-muted/50 px-1 py-1.5">
      <div className={cn("num truncate font-semibold", bad && "text-destructive")}>{value}</div>
      <div className="text-muted-foreground">{label}</div>
    </div>
  );
}
