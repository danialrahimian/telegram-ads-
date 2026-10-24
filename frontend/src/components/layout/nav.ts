import {
  BotIcon,
  HistoryIcon,
  LayersIcon,
  LayoutDashboardIcon,
  LightbulbIcon,
  MegaphoneIcon,
  PlugIcon,
  SparklesIcon,
  TypeIcon,
} from "lucide-react";

export const ACCOUNT_NAV = [
  { to: "", label: "داشبورد", icon: LayoutDashboardIcon, end: true },
  { to: "ads", label: "آگهی‌ها", icon: MegaphoneIcon },
  { to: "proposals", label: "پیشنهادها", icon: LightbulbIcon, badge: "proposals" as const },
  { to: "bulk", label: "عملیات گروهی", icon: LayersIcon },
  { to: "texts", label: "متن‌ها", icon: TypeIcon },
  { to: "sales", label: "فروش و رفرال", icon: BotIcon },
  { to: "analysis", label: "تحلیل با Claude", icon: SparklesIcon },
  { to: "activity", label: "فعالیت", icon: HistoryIcon },
  { to: "settings", label: "اتصال و تنظیمات", icon: PlugIcon },
];
