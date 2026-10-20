import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangleIcon, LockIcon } from "lucide-react";
import { useState } from "react";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, errorMessage } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Me } from "@/lib/types";

export function LoginPage({ me, error, retry }: { me?: Me; error?: unknown; retry?: () => void }) {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setMsg("");
    try {
      await api.get("/auth/me"); // make sure the CSRF cookie exists
      await api.post("/auth/login", { password });
      await qc.invalidateQueries({ queryKey: keys.me });
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-b from-accent/40 to-background px-4 py-10">
      <div className="w-full max-w-sm space-y-4">
        <div className="flex flex-col items-center gap-2 text-center">
          <img src="/favicon.svg" alt="" className="size-12" />
          <h1 className="text-xl font-bold">Telegram Ads Manager</h1>
          <p className="text-sm text-muted-foreground">مدیریت، تحلیل و بهینه‌سازی تبلیغات تلگرام</p>
        </div>
        {error ? <QueryError error={error} retry={retry} /> : null}
        {me?.problems?.length ? (
          <Alert variant="warning">
            <AlertTriangleIcon />
            <AlertTitle>تنظیمات سرور کامل نیست</AlertTitle>
            <AlertDescription>
              <ul className="list-disc ps-4">
                {me.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              <p>
                روی سرور <code className="ltr">tgads edit</code> یا <code className="ltr">tgads install</code> را اجرا کنید.
              </p>
            </AlertDescription>
          </Alert>
        ) : null}
        {me?.insecure_cookie ? (
          <Alert variant="warning">
            <AlertTriangleIcon />
            <AlertTitle>اتصال امن نیست</AlertTitle>
            <AlertDescription>پنل را با https باز کنید؛ در غیر این صورت ورود کار نمی‌کند.</AlertDescription>
          </Alert>
        ) : null}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LockIcon className="size-4" /> ورود
            </CardTitle>
            <CardDescription>رمزی که موقع نصب انتخاب کردید را وارد کنید.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-1.5">
                <Label htmlFor="password">رمز عبور</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={!!msg}
                />
                {msg && <p className="text-xs text-destructive">{msg}</p>}
              </div>
              <Button type="submit" disabled={busy || !password}>
                {busy ? "در حال ورود…" : "ورود"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="text-center text-xs text-muted-foreground">
          رمز را فراموش کرده‌اید؟ روی سرور <code className="ltr">tgads password</code> را اجرا کنید.
        </p>
      </div>
    </div>
  );
}
