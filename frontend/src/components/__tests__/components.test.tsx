import { render, screen } from "@testing-library/react";
import { AdStatusBadge } from "@/components/ad-status";
import { HealthBadge } from "@/components/health";
import { StatCard } from "@/components/stat-card";

describe("components", () => {
  it("StatCard shows value and a colored change", () => {
    render(<StatCard label="خرج" value="۱ TON" change={0.2} goodWhen="down" />);
    expect(screen.getByText("خرج")).toBeInTheDocument();
    expect(screen.getByText("۱ TON")).toBeInTheDocument();
    expect(screen.getByTitle("نسبت به دوره‌ی قبل").className).toContain("text-destructive");
  });

  it("HealthBadge labels each state", () => {
    const { rerender } = render(<HealthBadge status="ok" />);
    expect(screen.getByText("سالم")).toBeInTheDocument();
    rerender(<HealthBadge status="error" />);
    expect(screen.getByText("خطا")).toBeInTheDocument();
    rerender(<HealthBadge status="ok" configured={false} />);
    expect(screen.getByText("تنظیم نشده")).toBeInTheDocument();
  });

  it("AdStatusBadge treats paused active ads as paused", () => {
    render(<AdStatusBadge status="active" paused />);
    expect(screen.getByText("مکث")).toBeInTheDocument();
  });
});

describe("bot sync parts", () => {
  it("shows a successful ledger with zero rows as its own state, with the filters sent", async () => {
    const { SyncParts } = await import("@/components/bot-diagnostics");
    const account = {
      sync: {
        bot: {
          last_try: 1,
          parts: {
            stats: { ok: true, code: "ok", title: "سالم", fix: "" },
            transactions: {
              ok: true,
              code: "ok_empty",
              title: "درخواست موفق، ولی صفر ردیف",
              fix: "",
              rows: 0,
              filters: { from: 1700000000, purchase_types: ["buy", "buy_extend"] },
            },
            tags: { "3": { ok: false, code: "access_denied", title: "دسترسی «users» به کلید داده نشده", fix: "دسترسی بدهید", referrer: "9001" } },
          },
        },
      },
    } as unknown as import("@/lib/types").Account;
    render(<SyncParts account={account} />);
    expect(screen.getByText(/صفر ردیف/)).toBeInTheDocument();
    expect(screen.getByText("buy, buy_extend")).toBeInTheDocument();
    expect(screen.getByText(/رفرال معرف 9001/)).toBeInTheDocument();
  });
});
