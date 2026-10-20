import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon } from "lucide-react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { z } from "zod";
import { Field } from "@/components/field";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Account } from "@/lib/types";
import { cn } from "@/lib/utils";

export const COLORS = [
  { id: "teal", label: "فیروزه‌ای" },
  { id: "violet", label: "بنفش" },
  { id: "amber", label: "کهربایی" },
  { id: "rose", label: "سرخ" },
  { id: "sky", label: "آبی" },
  { id: "lime", label: "سبز" },
];

const schema = z.object({
  name: z.string().trim().min(1, "نام حساب را بنویسید").max(80),
  slug: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/, "۳ تا ۴۰ حرف انگلیسی کوچک، عدد یا خط تیره (مثل darvaze)"),
  color: z.string(),
});
type FormValues = z.infer<typeof schema>;

export default function AccountNewPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", slug: "", color: "teal" },
  });
  const color = form.watch("color");

  const onSubmit = form.handleSubmit(async (v) => {
    try {
      const acc = await api.post<Account>("/accounts", v);
      await qc.invalidateQueries({ queryKey: keys.accounts });
      await qc.invalidateQueries({ queryKey: keys.overview });
      toast.success("حساب ساخته شد. حالا اتصال‌ها را تنظیم کنید.");
      nav(`/accounts/${acc.slug}/settings`);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  });

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <PageHeader
        title="حساب تبلیغاتی جدید"
        description="هر حساب Telegram Ads که برای یک ربات جداست، اینجا یک حساب جداگانه با داشبورد و تحلیل خودش می‌شود."
      />
      <Card>
        <CardHeader>
          <CardTitle>مشخصات</CardTitle>
          <CardDescription>توکن‌ها را در مرحله‌ی بعد، در صفحه‌ی اتصال وارد می‌کنید.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid gap-5">
            <Field label="نام نمایشی" htmlFor="name" error={form.formState.errors.name?.message} hint="مثل «سایکونت» یا «دروازه آزادی»">
              <Input id="name" {...form.register("name")} aria-invalid={!!form.formState.errors.name} />
            </Field>
            <Field
              label="شناسه‌ی مسیر"
              htmlFor="slug"
              error={form.formState.errors.slug?.message}
              hint="در آدرس داشبورد می‌آید: /accounts/darvaze"
            >
              <Input
                id="slug"
                dir="ltr"
                className="text-left"
                placeholder="darvaze"
                {...form.register("slug")}
                aria-invalid={!!form.formState.errors.slug}
              />
            </Field>
            <Field label="رنگ">
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="رنگ">
                {COLORS.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    role="radio"
                    aria-checked={color === c.id}
                    aria-label={c.label}
                    title={c.label}
                    data-accent={c.id}
                    onClick={() => form.setValue("color", c.id)}
                    className={cn(
                      "flex size-9 items-center justify-center rounded-full ring-offset-2 ring-offset-background transition",
                      color === c.id && "ring-2 ring-ring",
                    )}
                    style={{ background: "var(--acc)" }}
                  >
                    {color === c.id && <CheckIcon className="size-4 text-white" />}
                  </button>
                ))}
              </div>
            </Field>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              ساخت حساب
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
