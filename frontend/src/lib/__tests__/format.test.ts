import { ago, delta, money, num, pct, seconds } from "@/lib/format";

describe("format", () => {
  it("formats numbers with Persian digits", () => {
    expect(num(1234)).toBe("۱٬۲۳۴");
    expect(num(null)).toBe("—");
  });
  it("keeps more precision for small amounts", () => {
    expect(money(0.0375, "TON")).toBe("۰٫۰۳۷۵ TON");
    expect(money(12.345)).toBe("۱۲٫۳۵");
    expect(money(undefined)).toBe("—");
  });
  it("computes deltas safely", () => {
    expect(delta(15, 10)).toBeCloseTo(0.5);
    expect(delta(5, 0)).toBeNull();
    expect(delta(null, 3)).toBeNull();
    expect(pct(0.25)).toContain("۲۵");
  });
  it("renders relative times and durations", () => {
    expect(ago(0)).toBe("هرگز");
    expect(ago(1000, 1005)).toBe("همین حالا");
    expect(ago(1000, 1000 + 120)).toBe("۲ دقیقه پیش");
    expect(seconds(30)).toBe("۳۰ ثانیه");
    expect(seconds(600)).toBe("۱۰ دقیقه");
  });
});
