import { DownloadIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { useAccountCtx } from "@/components/layout/account-layout";
import { Markdown } from "@/components/markdown";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { accountApi, keys, useAction, useAnalyses, useAppSettings } from "@/lib/queries";
import type { Analysis } from "@/lib/types";

const QUICK = [
  "کدام آگهی‌ها را متوقف کنم و بودجه را به کدام‌ها بدهم؟",
  "چرا هزینه‌ی هر استارت این هفته تغییر کرده؟",
  "کدام جایگاه‌ها (کانال/ربات) بیشترین مشتری را با کمترین هزینه آورده‌اند؟",
  "برای رسیدن به هدف هزینه‌ی هر مشتری، برنامه‌ی هفته‌ی بعد را بنویس.",
];

export default function AnalysisPage() {
  const account = useAccountCtx();
  const settings = useAppSettings();
  const { data, isLoading, error, refetch } = useAnalyses(account.slug);
  const [q, setQ] = useState("");
  const base = accountApi(account.slug);
  const ask = useAction<string, Analysis>({
    fn: (question) => api.post(`${base}/analysis`, { question }),
    invalidate: [[...keys.acc(account.slug), "analysis"]],
    success: "تحلیل آماده شد.",
    onSuccess: () => setQ(""),
  });
  const noKey = settings.data && !settings.data.claude_key_set;

  return (
    <div className="space-y-5">
      <PageHeader
        title="تحلیل با Claude"
        description="Claude آمار آگهی‌ها، فروش ربات و رفرال‌های همین حساب را می‌خواند و پیشنهاد عملی می‌دهد."
        actions={
          <Button asChild variant="outline">
            <a href={`/api/v1${base}/export.zip`} download>
              <DownloadIcon /> خروجی داده‌ها (ZIP)
            </a>
          </Button>
        }
      />
      {noKey && (
        <Alert variant="warning">
          <AlertDescription>
            کلید API Claude تنظیم نشده است.{" "}
            <Link to="/settings" className="underline">
              تنظیمات کلی
            </Link>{" "}
            — یا فایل ZIP را دانلود و در claude.ai بارگذاری کنید.
          </AlertDescription>
        </Alert>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">سؤال بپرسید</CardTitle>
          <CardDescription>خالی بگذارید تا یک تحلیل کامل از وضعیت حساب بگیرید.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={3}
            placeholder="مثلاً: چرا آگهی‌های ربات این هفته گران‌تر شده‌اند؟"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            maxLength={2000}
          />
          <div className="flex flex-wrap gap-1.5">
            {QUICK.map((x) => (
              <button
                key={x}
                type="button"
                onClick={() => setQ(x)}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
              >
                {x}
              </button>
            ))}
          </div>
          <Button onClick={() => ask.mutate(q)} disabled={ask.isPending || !!noKey}>
            <SparklesIcon className={ask.isPending ? "animate-pulse" : ""} />
            {ask.isPending ? "Claude در حال تحلیل… (تا یک دقیقه)" : q.trim() ? "بپرس" : "تحلیل کامل حساب"}
          </Button>
        </CardContent>
      </Card>

      {error && <QueryError error={error} retry={() => refetch()} />}
      {isLoading && <Skeleton className="h-48" />}
      {ask.isPending && <Skeleton className="h-40" />}
      {data?.length === 0 && !ask.isPending && (
        <EmptyState icon={SparklesIcon} title="هنوز تحلیلی گرفته نشده" />
      )}
      <div className="space-y-4">
        {data?.map((a) => (
          <Card key={a.id}>
            <CardHeader>
              <CardTitle className="text-sm leading-relaxed">{a.question || "تحلیل کامل حساب"}</CardTitle>
              <CardDescription className="flex flex-wrap items-center gap-2">
                {dateTime(a.created_at)}
                <Badge variant="outline" className="ltr">
                  {a.model}
                </Badge>
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Markdown>{a.output}</Markdown>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
