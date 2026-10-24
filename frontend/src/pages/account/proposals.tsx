import { CheckIcon, LightbulbIcon, PlayIcon, RefreshCwIcon, ReplaceIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { placementLabel } from "@/components/ad-status";
import { BulkDialog, type BulkTarget } from "@/components/bulk-dialog";
import { ConfirmButton } from "@/components/confirm-button";
import { EmptyState } from "@/components/empty-state";
import { useAccountCtx } from "@/components/layout/account-layout";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { dateTime, money, num } from "@/lib/format";
import { accountApi, keys, useAction, useProposals } from "@/lib/queries";
import type { Proposal } from "@/lib/types";

const KIND_ORDER: Proposal["kind"][] = ["replace", "stop", "withdraw", "refill", "topup", "refresh"];
const KIND_TITLE: Record<Proposal["kind"], { title: string; desc: string; variant: "destructive" | "warning" | "success" | "info" }> = {
  stop: { title: "توقف آگهی‌های پرهزینه", desc: "هزینه‌ی هر استارت از سقف بیشتر است", variant: "destructive" },
  withdraw: { title: "پس گرفتن بودجه‌ی بلااستفاده", desc: "آگهی دیگر نمایش داده نمی‌شود ولی بودجه دارد", variant: "warning" },
  topup: { title: "شارژ آگهی‌های خوب", desc: "آگهی ارزان کار می‌کند و بودجه‌اش رو به اتمام است", variant: "success" },
  refresh: { title: "تازه کردن متن", desc: "عملکرد آگهی نسبت به اوایلش افت کرده (خستگی)", variant: "info" },
  refill: {
    title: "شارژ دوباره‌ی آگهی‌های خوبِ بی‌بودجه",
    desc: "آگهی در روزهایی که بودجه داشت ارزان کار می‌کرد و حالا بودجه‌اش تمام شده",
    variant: "success",
  },
  replace: {
    title: "جایگزینی آگهی (مشکل متن یا عکس)",
    desc: "تلگرام آگهی را رد کرده، نمایشش نمی‌دهد یا متنش احتمالاً با قوانین نمی‌خواند",
    variant: "destructive",
  },
};

function target(p: Proposal): BulkTarget {
  return { ad_id: p.ad_id, label: p.target_label || p.title || `#${p.ad_id}`, text: p.text ?? "", reason: p.reason };
}

export default function ProposalsPage() {
  const account = useAccountCtx();
  const nav = useNavigate();
  const { data, isLoading, error, refetch } = useProposals(account.slug);
  const base = accountApi(account.slug);
  const inv = [keys.acc(account.slug), keys.accounts];
  const cur = account.telegram.currency;
  const [replacing, setReplacing] = useState<Proposal[] | null>(null);

  const approve = useAction<number, { kind: string; ad_id: number | null; message: string }>({
    fn: (id) => api.post(`${base}/proposals/${id}/approve`),
    invalidate: inv,
    onSuccess: (r) => {
      if (r.kind === "refresh" && r.ad_id) nav(`/accounts/${account.slug}/ads/new?replace=${r.ad_id}`);
    },
  });
  const reject = useAction<number>({ fn: (id) => api.post(`${base}/proposals/${id}/reject`), invalidate: inv });
  const approveKind = useAction<string, { approved: number; errors: string[] }>({
    fn: (kind) => api.post(`${base}/proposals/approve-kind`, { kind }),
    invalidate: inv,
    success: (r) => `${num(r.approved)} پیشنهاد تأیید شد${r.errors.length ? `؛ ${num(r.errors.length)} خطا` : ""}.`,
  });
  const run = useAction<void, { created?: number }>({
    fn: () => api.post(`${base}/proposals/run`),
    invalidate: inv,
    success: (r) => (r?.created ? `${num(r.created)} پیشنهاد تازه ساخته شد.` : "قوانین بررسی شد؛ پیشنهاد تازه‌ای نیست."),
  });

  const groups = useMemo(() => {
    const g = new Map<Proposal["kind"], Proposal[]>();
    for (const p of data?.pending ?? []) g.set(p.kind, [...(g.get(p.kind) ?? []), p]);
    return KIND_ORDER.filter((k) => g.has(k)).map((k) => ({ kind: k, items: g.get(k)! }));
  }, [data]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="پیشنهادها"
        description="قوانین حساب، آگهی‌ها را بررسی می‌کنند و پیشنهاد می‌دهند؛ هیچ کاری بدون تأیید شما اجرا نمی‌شود."
        actions={
          <Button variant="outline" onClick={() => run.mutate()} disabled={run.isPending}>
            <RefreshCwIcon className={run.isPending ? "animate-spin" : ""} /> بررسی دوباره‌ی قوانین
          </Button>
        }
      />
      {error && <QueryError error={error} retry={() => refetch()} />}
      {isLoading && <Skeleton className="h-64" />}

      {data && (
        <Card className="gap-3 py-4">
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>شارژ ۲۴ ساعت اخیر</span>
              <span className="num text-muted-foreground">
                {money(data.topup_used_24h, cur)} از {money(data.topup_daily_cap, cur)}
              </span>
            </div>
            <Progress value={data.topup_daily_cap ? (data.topup_used_24h / data.topup_daily_cap) * 100 : 0} />
          </CardContent>
        </Card>
      )}

      {replacing && (
        <BulkDialog
          account={account}
          kind="replace"
          targets={replacing.map(target)}
          proposalIds={replacing.map((p) => p.id)}
          onClose={() => setReplacing(null)}
        />
      )}

      {data && (
        <Tabs defaultValue="pending">
          <TabsList>
            <TabsTrigger value="pending">
              در انتظار <span className="num text-xs">{num(data.pending.length)}</span>
            </TabsTrigger>
            <TabsTrigger value="history">تاریخچه</TabsTrigger>
          </TabsList>
          <TabsContent value="pending" className="space-y-4">
            {groups.length === 0 && (
              <EmptyState
                icon={LightbulbIcon}
                title="پیشنهادی در انتظار نیست"
                description="بعد از هر همگام‌سازی آمار، قوانین دوباره بررسی می‌شوند."
              />
            )}
            {groups.map(({ kind, items }) => (
              <Card key={kind}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Badge variant={KIND_TITLE[kind].variant} className="num">
                      {num(items.length)}
                    </Badge>
                    {KIND_TITLE[kind].title}
                  </CardTitle>
                  <CardDescription>{KIND_TITLE[kind].desc}</CardDescription>
                  {kind === "replace" && items.length > 1 && (
                    <CardAction>
                      <Button size="sm" variant="outline" onClick={() => setReplacing(items)}>
                        <CheckIcon /> تأیید همه
                      </Button>
                    </CardAction>
                  )}
                  {kind !== "refresh" && kind !== "replace" && items.length > 1 && (
                    <CardAction>
                      <ConfirmButton
                        size="sm"
                        variant="outline"
                        title={`تأیید همه‌ی ${num(items.length)} پیشنهاد؟`}
                        description={
                          kind === "topup" || kind === "refill"
                            ? "همه‌ی شارژها تا سقف روزانه در صف اجرا می‌روند."
                            : "همه‌ی این آگهی‌ها متوقف می‌شوند و بودجه‌شان بعد از ۱۰ دقیقه برمی‌گردد."
                        }
                        onConfirm={() => approveKind.mutateAsync(kind)}
                      >
                        <CheckIcon /> تأیید همه
                      </ConfirmButton>
                    </CardAction>
                  )}
                </CardHeader>
                <CardContent className="grid gap-2">
                  {items.map((p) => (
                    <div key={p.id} className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center">
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <Link to={`/accounts/${account.slug}/ads/${p.ad_id}`} className="font-medium hover:underline">
                            {p.target_label || p.title || `#${p.ad_id}`}
                          </Link>
                          {p.placement && <Badge variant="outline">{placementLabel(p.placement)}</Badge>}
                          {p.amount ? <Badge variant="secondary" className="num">{money(p.amount, cur)}</Badge> : null}
                        </div>
                        <p className="text-xs leading-relaxed text-muted-foreground">{p.reason}</p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        {kind === "replace" ? (
                          <Button size="sm" onClick={() => setReplacing([p])}>
                            <ReplaceIcon /> ساخت آگهی جایگزین
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant={kind === "stop" || kind === "withdraw" ? "destructive" : "default"}
                            disabled={approve.isPending}
                            onClick={() => approve.mutate(p.id)}
                          >
                            {kind === "refresh" ? <PlayIcon /> : <CheckIcon />}
                            {kind === "refresh" ? "ساخت آگهی جایگزین" : "تأیید"}
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" disabled={reject.isPending} onClick={() => reject.mutate(p.id)}>
                          <XIcon /> رد
                        </Button>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            ))}
          </TabsContent>
          <TabsContent value="history">
            <Card className="py-2">
              <CardContent className="divide-y px-0">
                {data.history.length === 0 && <p className="p-5 text-sm text-muted-foreground">هنوز تاریخچه‌ای نیست.</p>}
                {data.history.map((p) => (
                  <div key={p.id} className="flex flex-col gap-1 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="text-sm">
                        <span className="font-medium">{p.label}</span>{" "}
                        <Link to={`/accounts/${account.slug}/ads/${p.ad_id}`} className="text-muted-foreground hover:underline">
                          · {p.target_label || `#${p.ad_id}`}
                        </Link>
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {dateTime(p.decided_ts || p.created_ts)} {p.result && `· ${p.result}`}
                      </div>
                    </div>
                    <Badge
                      variant={p.status === "rejected" ? "secondary" : p.status === "expired" ? "outline" : "success"}
                    >
                      {p.status === "rejected" ? "رد شد" : p.status === "expired" ? "منقضی" : p.status === "done" ? "انجام شد" : "تأیید شد"}
                    </Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
