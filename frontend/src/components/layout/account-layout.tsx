import { AlertTriangleIcon, PauseCircleIcon, PlugZapIcon } from "lucide-react";
import { createContext, useContext } from "react";
import { Link, Outlet, useParams } from "react-router";
import { QueryError } from "@/components/query-error";
import { SyncStatus } from "@/components/sync-status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAccount } from "@/lib/queries";
import type { Account } from "@/lib/types";

const Ctx = createContext<Account | null>(null);

export function useAccountCtx(): Account {
  const a = useContext(Ctx);
  if (!a) throw new Error("useAccountCtx outside AccountLayout");
  return a;
}

export function AccountLayout() {
  const { slug = "" } = useParams();
  const { data: account, error, isLoading, refetch } = useAccount(slug);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-56" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (error || !account) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <Alert variant="warning">
          <AlertTriangleIcon />
          <AlertTitle>این حساب پیدا نشد</AlertTitle>
          <AlertDescription>
            <Button asChild size="sm" variant="outline" className="mt-2">
              <Link to="/">بازگشت به نمای کلی</Link>
            </Button>
          </AlertDescription>
        </Alert>
      );
    }
    return <QueryError error={error} retry={() => refetch()} />;
  }

  const needsToken = !account.telegram.configured;
  const tgBroken = account.telegram.configured && account.telegram.status === "error";
  return (
    <Ctx.Provider value={account}>
      <div data-accent={account.color} className="space-y-5">
        <div className="flex flex-col gap-2 rounded-xl border bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <span
              className="flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-bold text-white"
              style={{ background: "var(--acc)" }}
            >
              {account.name.slice(0, 1)}
            </span>
            <div className="min-w-0">
              <div className="truncate font-semibold">{account.name}</div>
              <div className="truncate text-xs text-muted-foreground">
                {account.bot.username ? <span className="ltr">@{account.bot.username}</span> : "ربات تنظیم نشده"}
                {account.telegram.title && <> · {account.telegram.title}</>}
              </div>
            </div>
          </div>
          <SyncStatus account={account} />
        </div>

        {needsToken && (
          <Alert variant="info">
            <PlugZapIcon />
            <AlertTitle>اتصال به Telegram Ads هنوز برقرار نشده</AlertTitle>
            <AlertDescription>
              <p>توکن API این حساب را در صفحه‌ی اتصال وارد کنید تا آگهی‌ها و آمار خوانده شوند.</p>
              <Button asChild size="sm" className="mt-2">
                <Link to={`/accounts/${account.slug}/settings`}>رفتن به اتصال و تنظیمات</Link>
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {tgBroken && (
          <Alert variant="destructive">
            <AlertTriangleIcon />
            <AlertTitle>اتصال Telegram Ads خطا دارد</AlertTitle>
            <AlertDescription>
              <p>{account.telegram.error}</p>
              <Button asChild size="sm" variant="outline" className="mt-2">
                <Link to={`/accounts/${account.slug}/settings`}>بررسی اتصال</Link>
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {account.automation_paused && (
          <Alert variant="warning">
            <PauseCircleIcon />
            <AlertTitle>اجرای خودکار متوقف است</AlertTitle>
            <AlertDescription>
              پیشنهادها ساخته می‌شوند ولی هیچ کاری اجرا نمی‌شود. از صفحه‌ی تنظیمات دوباره روشنش کنید.
            </AlertDescription>
          </Alert>
        )}

        <Outlet />
      </div>
    </Ctx.Provider>
  );
}
