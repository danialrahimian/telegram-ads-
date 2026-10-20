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
