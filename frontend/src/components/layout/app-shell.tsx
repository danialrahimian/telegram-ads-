import { useQueryClient } from "@tanstack/react-query";
import { MenuIcon } from "lucide-react";
import { useState } from "react";
import { Outlet, useLocation } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import { Sidebar } from "./sidebar";

export function AppShell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const loc = useLocation();

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* already logged out */
    }
    qc.clear();
    await qc.invalidateQueries({ queryKey: keys.me });
    toast.success("خارج شدید.");
  };

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <aside className="sticky top-0 hidden h-dvh border-e border-sidebar-border lg:block">
        <Sidebar onLogout={logout} />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur lg:hidden">
          <Button variant="ghost" size="icon" aria-label="منو" onClick={() => setOpen(true)}>
            <MenuIcon />
          </Button>
          <img src="/favicon.svg" alt="" className="size-6" />
          <span className="truncate text-sm font-bold">Telegram Ads Manager</span>
        </header>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent side="start" className="w-72 p-0">
            <SheetTitle className="sr-only">منو</SheetTitle>
            <SheetDescription className="sr-only">پیمایش بین حساب‌ها و صفحه‌ها</SheetDescription>
            <Sidebar onNavigate={() => setOpen(false)} onLogout={logout} />
          </SheetContent>
        </Sheet>

        <main key={loc.pathname.split("/").slice(0, 3).join("/")} className="mx-auto w-full max-w-7xl flex-1 px-3 py-4 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
