import { budgetless, headerState, toggleAll, toggleOne } from "@/lib/bulk";

describe("bulk selection", () => {
  it("toggles one id", () => {
    const s = toggleOne(new Set([1]), 2);
    expect([...s].sort()).toEqual([1, 2]);
    expect([...toggleOne(s, 1)]).toEqual([2]);
  });

  it("selects every visible id, then clears them", () => {
    const some = new Set([1, 9]);
    const all = toggleAll(some, [1, 2, 3]);
    expect([...all].sort()).toEqual([1, 2, 3, 9]);
    expect([...toggleAll(all, [1, 2, 3])]).toEqual([9]); // ids outside the filter stay selected
  });

  it("reports the header checkbox state", () => {
    expect(headerState(new Set(), [1, 2])).toBe(false);
    expect(headerState(new Set([1]), [1, 2])).toBe("indeterminate");
    expect(headerState(new Set([1, 2]), [1, 2])).toBe(true);
    expect(headerState(new Set([1]), [])).toBe(false);
  });

  it("labels ads without budget", () => {
    expect(budgetless({ remaining: 1, empty_days: null })).toBeNull();
    expect(budgetless({ remaining: 0, empty_days: 20 })).toBe("بی‌بودجه از ۲۰ روز پیش");
    expect(budgetless({ remaining: 0.005, empty_days: 0 })).toBe("بی‌بودجه از امروز");
    expect(budgetless({ remaining: 0, empty_days: null })).toBe("بی‌بودجه");
  });
});
