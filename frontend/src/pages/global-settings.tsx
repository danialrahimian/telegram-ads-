import { CheckCircle2Icon, KeyRoundIcon, LockIcon, MonitorCogIcon, SaveIcon, SparklesIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { Field } from "@/components/field";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { keys, useAction, useAppSettings, useSystem } from "@/lib/queries";
import type { AppSettings } from "@/lib/types";

const MODELS = [
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (پیشنهادی)" },
  { id: "claude-opus-5-5", label: "Claude Opus 5.5 (دقیق‌تر، گران‌تر)" },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5 (سریع و ارزان)" },
];

export default function GlobalSettingsPage() {
  const settings = useAppSettings();
  const sys = useSystem();
  return (
    <div className="space-y-5">
      <PageHeader title="تنظیمات کلی" description="تنظیمات مشترک همه‌ی حساب‌ها: Claude، تازه‌سازی داشبورد و رمز ورود." />
      {settings.isLoading || !settings.data ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          <ClaudeCard s={settings.data} />
          <div className="space-y-5">
            <UiCard s={settings.data} />
            <PasswordCard />
          </div>
        </div>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <MonitorCogIcon className="size-4" /> سرور
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-muted-foreground">نسخه</div>
            <div className="ltr font-medium">{sys.data?.version ?? "…"}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">آی‌پی سرور</div>
            <div className="flex items-center font-medium">
              <span className="ltr">{sys.data?.server_ip || "…"}</span>
              {sys.data?.server_ip && <CopyButton value={sys.data.server_ip} />}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">کارهای در صف</div>
            <div className="num font-medium">{num(sys.data?.queued_jobs)}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">دستورهای سرور</div>
            <div className="ltr text-xs">tgads status · tgads logs · tgads update</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ClaudeCard({ s }: { s: AppSettings }) {
  const [key, setKey] = useState("");
  const [model, setModel] = useState(s.claude_model);
  const custom = !MODELS.some((m) => m.id === model);
  const save = useAction<Record<string, unknown>, AppSettings>({
    fn: (body) => api.put("/settings", body),
    invalidate: [keys.settings],
    success: "ذخیره شد.",
    onSuccess: () => setKey(""),
  });
  const test = useAction<void, { ok: boolean; model: string; reply: string }>({
    fn: () => api.post("/settings/claude/test"),
    success: (r) => `Claude پاسخ داد (${r.model}): ${r.reply}`,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <SparklesIcon className="size-4" /> Claude
        </CardTitle>
        <CardDescription>برای تحلیل حساب‌ها و تحلیل و بازنویسی متن آگهی‌ها. کلید از console.anthropic.com</CardDescription>
        <CardAction>
          {s.claude_key_set ? (
            <Badge variant="success">
              <CheckCircle2Icon /> •••• <span className="ltr">{s.claude_key_last4}</span>
            </Badge>
          ) : (
            <Badge variant="secondary">تنظیم نشده</Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-4">
        <Field label={s.claude_key_set ? "کلید تازه (برای جایگزینی)" : "کلید API"} htmlFor="claude-key" hint="رمزنگاری‌شده ذخیره می‌شود.">
          <Input
            id="claude-key"
            type="password"
            dir="ltr"
            autoComplete="off"
            placeholder="sk-ant-…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </Field>
        <Field label="مدل">
          <Select value={custom ? "custom" : model} onValueChange={(v) => setModel(v === "custom" ? "" : v)}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODELS.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.label}
                </SelectItem>
              ))}
              <SelectItem value="custom">مدل دیگر…</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        {custom && (
          <Field label="شناسه‌ی مدل" htmlFor="model-id">
            <Input id="model-id" dir="ltr" value={model} onChange={(e) => setModel(e.target.value)} placeholder="claude-…" />
          </Field>
        )}
      </CardContent>
      <CardFooter className="flex-wrap gap-2">
        <Button
          disabled={save.isPending || (!key.trim() && model === s.claude_model) || !model.trim()}
          onClick={() =>
            save.mutate({ ...(key.trim() ? { claude_api_key: key.trim() } : {}), claude_model: model.trim() })
          }
        >
          <KeyRoundIcon /> ذخیره
        </Button>
        <Button variant="outline" disabled={!s.claude_key_set || test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "در حال آزمایش…" : "آزمایش اتصال"}
        </Button>
        {s.claude_key_set && (
          <Button variant="ghost" className="text-destructive" onClick={() => save.mutate({ claude_api_key: "" })}>
            <Trash2Icon /> حذف کلید
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function UiCard({ s }: { s: AppSettings }) {
  const [sec, setSec] = useState(String(s.ui_refresh_seconds));
  useEffect(() => setSec(String(s.ui_refresh_seconds)), [s.ui_refresh_seconds]);
  const save = useAction<void>({
    fn: () => api.put("/settings", { ui_refresh_seconds: Number(sec) }),
    invalidate: [keys.settings, keys.system],
    success: "ذخیره شد.",
  });
  const n = Number(sec);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">تازه‌سازی داشبورد</CardTitle>
        <CardDescription>
          صفحه‌ها هر چند ثانیه داده‌ی تازه را از سرور می‌گیرند. فاصله‌ی همگام‌سازی با تلگرام برای هر حساب جدا در صفحه‌ی
          اتصال آن حساب تنظیم می‌شود.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Field label="هر چند ثانیه" htmlFor="ui-refresh" error={n < 2 || n > 600 ? "بین ۲ تا ۶۰۰ ثانیه" : undefined}>
          <Input id="ui-refresh" type="number" dir="ltr" min={2} max={600} className="w-32" value={sec} onChange={(e) => setSec(e.target.value)} />
        </Field>
      </CardContent>
      <CardFooter className="justify-end">
        <Button disabled={save.isPending || n < 2 || n > 600 || n === s.ui_refresh_seconds} onClick={() => save.mutate()}>
          <SaveIcon /> ذخیره
        </Button>
      </CardFooter>
    </Card>
  );
}

function PasswordCard() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [rep, setRep] = useState("");
  const save = useAction<void>({
    fn: () => api.post("/auth/password", { current: cur, new: next }),
    success: "رمز عوض شد.",
    onSuccess: () => {
      setCur("");
      setNext("");
      setRep("");
    },
  });
  const mismatch = rep.length > 0 && rep !== next;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LockIcon className="size-4" /> تغییر رمز ورود
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-3">
        <Field label="رمز فعلی" htmlFor="pw-cur">
          <Input id="pw-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
        </Field>
        <Field label="رمز تازه" htmlFor="pw-new" hint="حداقل ۸ حرف">
          <Input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="تکرار رمز تازه" htmlFor="pw-rep" error={mismatch ? "یکسان نیست" : undefined}>
          <Input id="pw-rep" type="password" autoComplete="new-password" value={rep} onChange={(e) => setRep(e.target.value)} />
        </Field>
      </CardContent>
      <CardFooter className="justify-end">
        <Button disabled={save.isPending || !cur || next.length < 8 || next !== rep} onClick={() => save.mutate()}>
          تغییر رمز
        </Button>
      </CardFooter>
    </Card>
  );
}
