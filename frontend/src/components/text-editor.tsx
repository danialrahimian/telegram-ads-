import { useQuery } from "@tanstack/react-query";
import { AlertTriangleIcon, CheckCircle2Icon, SparklesIcon } from "lucide-react";
import { useState } from "react";
import { Field } from "@/components/field";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useDebounced } from "@/hooks/use-debounced";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { accountApi, keys, useAction } from "@/lib/queries";
import type { TextCheck } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Ad text box with a live check against Telegram's ad guidelines and a "fix with Claude" button.
 *  Claude's version lands in the box so the user can still edit it before anything is saved. */
export function TextEditor({
  slug,
  id,
  label = "متن آگهی",
  value,
  onChange,
  adId,
  promoteUrl,
  reason,
  rows = 3,
}: {
  slug: string;
  id: string;
  label?: string;
  value: string;
  onChange: (v: string) => void;
  adId?: number;
  promoteUrl?: string;
  reason?: string;
  rows?: number;
}) {
  const text = useDebounced(value, 350);
  const check = useQuery({
    queryKey: [...keys.acc(slug), "text-check", text, adId ?? null, promoteUrl ?? null],
    queryFn: () =>
      api.post<TextCheck>(`${accountApi(slug)}/texts/check`, { text, ad_id: adId ?? null, promote_url: promoteUrl ?? null }),
    enabled: text.trim().length > 0,
    staleTime: Infinity,
  });
  const [notes, setNotes] = useState<string[]>([]);
  const fix = useAction<void, { text: string; notes: string[] }>({
    fn: () => api.post(`${accountApi(slug)}/texts/fix`, { text: value, reason: reason ?? "", ad_id: adId ?? null }),
    success: "Claude متن را اصلاح کرد؛ قبل از ادامه بازبینی و ویرایش کنید.",
    onSuccess: (r) => {
      onChange(r.text);
      setNotes(r.notes);
    },
  });
  const issues = check.data?.issues ?? [];
  const len = value.trim().length;
  return (
    <div className="grid gap-2">
      <Field label={label} htmlFor={id} hint={<span className={cn("num", len > 160 && "text-destructive")}>{num(len)} / ۱۶۰</span>}>
        <Textarea id={id} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={len > 160} />
      </Field>
      {value.trim() && check.data && (
        <div className="space-y-1 rounded-md border px-3 py-2 text-xs" data-testid="text-check">
          {issues.length === 0 ? (
            <div className="flex items-center gap-1.5 text-success">
              <CheckCircle2Icon className="size-3.5" /> با قوانین آگهی تلگرام می‌خواند.
            </div>
          ) : (
            issues.map((i) => (
              <div key={i.code + i.message} className={cn("flex items-start gap-1.5", i.severity === "error" ? "text-destructive" : "text-warning")}>
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
                <span>{i.message}</span>
              </div>
            ))
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" disabled={!value.trim() || fix.isPending} onClick={() => fix.mutate()}>
          <SparklesIcon className={fix.isPending ? "animate-pulse" : ""} />
          {fix.isPending ? "Claude در حال اصلاح…" : "بررسی و اصلاح با Claude"}
        </Button>
        {notes.length > 0 && <span className="text-xs text-muted-foreground">{notes.join("؛ ")}</span>}
      </div>
    </div>
  );
}
