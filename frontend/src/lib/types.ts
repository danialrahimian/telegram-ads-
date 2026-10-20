/** Shapes returned by the backend (see backend/app/api/v1/routes). */

export type Health = "ok" | "warn" | "error" | "unset" | "" | null;
export type SyncKind = "fast" | "stats" | "bot";

export interface Me {
  authenticated: boolean;
  version: string;
  problems: string[];
  insecure_cookie: boolean;
}

export interface SyncState {
  last_try?: number;
  last_ok?: number;
  error?: string;
  fails?: number;
  duration?: number;
  [k: string]: unknown;
}

export interface AccountSettings {
  sync_fast_seconds: number;
  sync_stats_seconds: number;
  sync_bot_seconds: number;
  target_cost_per_customer: number;
  stop_cost_per_start: number;
  scale_cost_per_start: number;
  min_spend_to_judge: number;
  min_purchases_to_judge: number;
  stalled_spend_28d: number;
  stalled_min_remaining: number;
  stalled_min_age_days: number;
  topup_max_per_ad: number;
  topup_daily_cap: number;
  fatigue_age_days: number;
  fatigue_ratio: number;
  default_cpm_channel: number;
  default_cpm_bot: number;
  default_budget: number;
  bot_timezone: string;
  purchase_types: string[];
  toman_per_unit: number;
}

export interface Account {
  id: number;
  slug: string;
  name: string;
  color: string;
  created_at: string | null;
  telegram: {
    configured: boolean;
    token_last4: string;
    status: Health;
    error: string;
    checked_ts: number;
    account_id: string;
    title: string;
    currency: string;
    spent_budget: number;
    remaining_budget: number;
    ads_budget: number;
  };
  bot: {
    configured: boolean;
    base_url: string;
    username: string;
    key_last4: string;
    status: Health;
    error: string;
    checked_ts: number;
    stats: Record<string, number | string>;
    fields: Record<string, string[]>;
  };
  settings: AccountSettings;
  sync: Partial<Record<SyncKind, SyncState>>;
  automation_paused: boolean;
  pending_proposals: number;
  queued_jobs?: number;
  syncing: SyncKind[];
}

export interface WindowStats {
  views: number;
  clicks: number;
  starts: number;
  spent: number;
  cps: number | null;
  prev_cps: number | null;
  prev_spent: number;
  prev_starts: number;
  ctr: number | null;
  start_rate: number | null;
  purchases: number;
  buyers: number;
  revenue: number;
  prev_revenue: number;
  prev_buyers: number;
  new_users: number | null;
}

export interface Summary {
  "7": WindowStats;
  "28": WindowStats;
  attributed_28: { buyers: number; purchases: number; revenue: number; users: number; ad_spend: number; cpp: number | null };
  roas_28: number | null;
  counts: { running: number; review: number; declined: number; total: number };
  balance: { account: number; on_ads: number; spent_total: number; on_running_ads: number };
  target_cost_per_customer: number;
}

export interface DailyRow {
  day: string;
  views: number;
  clicks: number;
  starts: number;
  spent: number;
  purchases: number;
  revenue: number;
  attributed_purchases: number;
  new_users: number | null;
}

export interface LivePoint {
  ts: number;
  spent: number;
  starts: number;
  clicks: number;
  views: number;
}

export interface Live {
  today: { spent: number; starts: number; clicks: number; views: number; new_users: number | null };
  points: LivePoint[];
  since_ts: number;
}

export interface OverviewAccount extends Account {
  summary: Summary | null;
}

export interface AdRow {
  ad_id: number;
  title: string;
  text: string;
  promote_url: string;
  start_code: string;
  cpm: number;
  placement: string;
  status: string;
  is_paused: boolean;
  has_stats: boolean;
  running: boolean;
  views: number;
  clicks: number;
  starts: number;
  action_type: string;
  spent: number;
  remaining: number;
  daily_budget_limit: number | null;
  created_date: number;
  age_days: number | null;
  target_type: string;
  target_label: string;
  has_photo: boolean;
  decline_reason: string;
  note: string;
  variant_id: number | null;
  tag_id: number | null;
  tag_name: string | null;
  tag_shared: boolean;
  first_day: string | null;
  last_spend_day: string | null;
  cps: number | null;
  ctr: number | null;
  start_rate: number | null;
  buyers: number | null;
  purchases: number | null;
  revenue: number | null;
  cpp: number | null;
  spent_7: number;
  starts_7: number;
  clicks_7: number;
  views_7: number;
  cps_7: number | null;
  spent_28: number;
  starts_28: number;
  clicks_28: number;
  views_28: number;
  cps_28: number | null;
  spent_since: number;
  starts_since: number;
  clicks_since: number;
  views_since: number;
  cps_since: number | null;
}

export type AdWindow = "7" | "28" | "since" | "all";

export interface Job {
  id: number;
  kind: string;
  label?: string;
  ad_id: number;
  target_label?: string;
  amount: number | null;
  status: string;
  attempts?: number;
  result: string;
  created_ts: number;
  run_at: number;
}

export interface Proposal {
  id: number;
  ad_id: number;
  kind: "withdraw" | "stop" | "refresh" | "topup";
  label: string;
  amount: number | null;
  reason: string;
  metrics?: Record<string, unknown>;
  status: string;
  created_ts: number;
  decided_ts?: number | null;
  result: string;
  target_label?: string;
  placement?: string;
  title?: string;
}

export interface AdDetail {
  ad: AdRow;
  target: Record<string, unknown> | null;
  daily: { day: string; views: number; clicks: number; starts: number; spent: number }[];
  jobs: Job[];
  proposals: Proposal[];
}

export interface TextAnalysis {
  score: number | null;
  summary: string;
  strengths: string[];
  issues: { issue?: string; severity?: string; fix?: string }[];
  rewrites: { text: string; angle: string; length: number; too_long: boolean }[];
  model: string;
}

export interface TextVariant {
  id: number;
  name: string;
  text: string;
  active: boolean;
  source: string;
  length: number;
  created_at: string | null;
  updated_at: string | null;
  analysis: TextAnalysis | null;
  analyzed_at: string | null;
  performance: {
    ads?: number;
    running?: number;
    views?: number;
    clicks?: number;
    starts?: number;
    spent?: number;
    buyers?: number;
    ctr?: number | null;
    start_rate?: number | null;
    cps?: number | null;
    cpp?: number | null;
  };
  versioned?: boolean;
}

export interface Tag {
  id: number;
  name: string;
  referrer_id: string;
  start_code: string;
  note: string;
  link: string;
  referred_count: number;
  last_synced_ts: number;
  last_error: string;
  ads: { ad_id: number; title: string; status: string }[];
  ad_spend: number;
  ad_starts: number;
  users: number;
  buyers: number;
  purchases: number;
  revenue: number;
  cpp: number | null;
  buy_rate: number | null;
}

export interface SalesOverview {
  days: number;
  by_type: { type: string; count: number; amount: number }[];
  purchase_types: string[];
  transactions_stored: number;
  last_tx_ts: number;
}

export interface Analysis {
  id: number;
  question: string;
  output: string;
  model: string;
  created_at: string;
}

export interface EventRow {
  id: number;
  ts: number;
  account_id?: number | null;
  actor: string;
  action: string;
  ad_id: number | null;
  level: string;
  detail: string;
}

export interface AppSettings {
  claude_model: string;
  claude_key_set: boolean;
  claude_key_last4: string;
  ui_refresh_seconds: number;
}

export interface SystemInfo {
  version: string;
  server_ip: string;
  scheduler_tick: number;
  queued_jobs: number;
  ui_refresh_seconds: number;
  min_sync_seconds: number;
}

export interface TelegramCheck {
  ok: boolean;
  error?: string;
  code?: string;
  title?: string;
  currency?: string;
  remaining_budget?: number;
}

export interface BotCheck {
  ok: boolean;
  status: Health;
  error: string;
  checks: { name: string; label: string; ok: boolean; message: string }[];
  stats?: Record<string, number>;
}
