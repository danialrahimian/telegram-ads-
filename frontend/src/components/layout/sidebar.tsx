import { HomeIcon, LogOutIcon, MonitorIcon, MoonIcon, PlusIcon, SettingsIcon, SunIcon } from "lucide-react";
import { NavLink, useMatch } from "react-router";
import { HealthDot } from "@/components/health";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { type Theme, useTheme } from "@/hooks/use-theme";
import { num } from "@/lib/format";
import { useAccounts, useMe } from "@/lib/queries";
import type { Account, Health } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ACCOUNT_NAV } from "./nav";

const itemCls = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground [&_svg]:size-4 [&_svg]:shrink-0",
    isActive && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
  );

function accountHealth(a: Account): Health {
  const tg = a.telegram.configured ? a.telegram.status : "unset";
  const bot = a.bot.configured ? a.bot.status : "unset";
  if (tg === "error" || bot === "error") return "error";
  if (tg === "ok" && (bot === "ok" || bot === "unset")) return bot === "unset" ? "warn" : "ok";
  if (tg === "unset") return "unset";
  return "warn";
}

export function Sidebar({ onNavigate, onLogout }: { onNavigate?: () => void; onLogout: () => void }) {
  const { data: accounts, isLoading } = useAccounts();
  const { data: me } = useMe();
  const match = useMatch("/accounts/:slug/*");
  const activeSlug = match?.params.slug !== "new" ? match?.params.slug : undefined;

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-4">
        <img src="/favicon.svg" alt="" className="size-7" />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-bold">Telegram Ads Manager</div>
          <div className="truncate text-[11px] text-muted-foreground">مدیریت تبلیغات تلگرام</div>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto p-3 scrollbar-thin" aria-label="منوی اصلی">
        <div className="space-y-0.5">
          <NavLink to="/" end className={itemCls} onClick={onNavigate}>
            <HomeIcon /> نمای کلی
          </NavLink>
          <NavLink to="/settings" className={itemCls} onClick={onNavigate}>
            <SettingsIcon /> تنظیمات کلی
          </NavLink>
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between px-2.5 text-xs font-medium text-muted-foreground">
            <span>حساب‌های تبلیغاتی</span>
            <Button asChild size="icon-sm" variant="ghost" className="size-6" title="افزودن حساب">
              <NavLink to="/accounts/new" onClick={onNavigate} aria-label="افزودن حساب">
                <PlusIcon className="size-3.5" />
              </NavLink>
            </Button>
          </div>
          {isLoading && (
            <div className="space-y-1.5 px-1">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          )}
          {accounts?.length === 0 && (
            <NavLink to="/accounts/new" className={itemCls} onClick={onNavigate}>
              <PlusIcon /> افزودن اولین حساب
            </NavLink>
          )}
          {accounts?.map((a) => {
            const open = a.slug === activeSlug;
            return (
              <div key={a.id} data-accent={a.color} className="space-y-0.5">
                <NavLink
                  to={`/accounts/${a.slug}`}
                  end
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      "flex h-10 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors hover:bg-sidebar-accent",
                      (open || isActive) && "font-semibold",
                    )
                  }
                >
                  <span
                    className="flex size-6 shrink-0 items-center justify-center rounded-md text-xs font-bold text-white"
                    style={{ background: "var(--acc)" }}
                  >
                    {a.name.slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{a.name}</span>
                  {a.pending_proposals > 0 && (
                    <Badge variant="warning" className="h-5 px-1.5 num">
                      {num(a.pending_proposals)}
                    </Badge>
                  )}
                  <HealthDot status={accountHealth(a)} />
                </NavLink>
                {open && (
                  <div className="ms-4 space-y-0.5 border-s border-sidebar-border ps-2">
                    {ACCOUNT_NAV.map((item) => (
                      <NavLink
                        key={item.to}
                        to={`/accounts/${a.slug}${item.to ? `/${item.to}` : ""}`}
                        end={item.end}
                        className={itemCls}
                        onClick={onNavigate}
                      >
                        <item.icon />
                        <span className="flex-1">{item.label}</span>
                        {item.badge === "proposals" && a.pending_proposals > 0 && (
                          <span className="num text-xs text-warning">{num(a.pending_proposals)}</span>
                        )}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      <div className="flex shrink-0 items-center gap-1 border-t border-sidebar-border p-2">
        <ThemeMenu />
        <Button variant="ghost" size="sm" className="flex-1 justify-start text-muted-foreground" onClick={onLogout}>
          <LogOutIcon /> خروج
        </Button>
        {me?.version && <span className="num px-2 text-[11px] text-muted-foreground ltr">v{me.version}</span>}
      </div>
    </div>
  );
}

export function ThemeMenu() {
  const { theme, resolved, setTheme } = useTheme();
  const Icon = theme === "system" ? MonitorIcon : resolved === "dark" ? MoonIcon : SunIcon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="پوسته">
          <Icon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
          <DropdownMenuRadioItem value="light">روشن</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">تیره</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">مطابق سیستم</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
