"""Full user journey in a real browser: login, two separate accounts, connections and health checks,
periodic sync, dashboards, ads, referral tags, Claude text analysis, budget history, bulk operations
(text change, referral links, replacements), bot diagnostics, proposals, actions, mobile layout."""

import re

import pytest

from tests.e2e.conftest import PASSWORD, Stack

expect = pytest.importorskip("playwright.sync_api").expect

DESKTOP = {"width": 1366, "height": 900}
MOBILE = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def ctx(browser, stack: Stack):
    context = browser.new_context(viewport=DESKTOP, locale="fa-IR", base_url=stack.base)
    yield context
    context.close()


@pytest.fixture(scope="module")
def errors() -> list[str]:
    return []


@pytest.fixture(scope="module")
def page(ctx, errors):
    p = ctx.new_page()
    p.set_default_timeout(15_000)
    p.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    p.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    yield p


def _nav(page, path: str) -> None:
    page.goto(path)
    page.wait_for_load_state("networkidle")


def test_login(page, shot):
    _nav(page, "/")
    expect(page.get_by_role("heading", name="Telegram Ads Manager")).to_be_visible()
    shot(page, "01-login")
    page.get_by_label("رمز عبور").fill("wrong-password")
    page.get_by_role("button", name="ورود").click()
    expect(page.get_by_text("رمز اشتباه است.")).to_be_visible()
    page.get_by_label("رمز عبور").fill(PASSWORD)
    page.get_by_role("button", name="ورود").click()
    expect(page.get_by_role("heading", name="نمای کلی")).to_be_visible()
    expect(page.get_by_text("هنوز حسابی اضافه نشده")).to_be_visible()
    shot(page, "02-overview-empty")


def _create_account(page, name: str, slug: str, color: str) -> None:
    _nav(page, "/accounts/new")
    page.get_by_label("نام نمایشی").fill(name)
    page.get_by_label("شناسه‌ی مسیر").fill(slug)
    page.get_by_role("radio", name=color).click()
    page.get_by_role("button", name="ساخت حساب").click()
    expect(page).to_have_url(re.compile(f"/accounts/{slug}/settings$"))


def _connect(page, stack: Stack, token: str, bot_key: str, bot_user: str, shot_name: str | None = None, shot=None):
    page.get_by_label("توکن API").fill(token)
    page.get_by_role("button", name="ذخیره و بررسی").first.click()
    expect(page.locator("#telegram").get_by_text("سالم")).to_be_visible()
    page.get_by_label("آدرس API ربات").fill(f"http://127.0.0.1:{stack.bot}/api/docs")
    page.get_by_label("نام کاربری ربات").fill(bot_user)
    page.get_by_label("کلید API ربات").fill(bot_key)
    page.locator("#bot").get_by_role("button", name="ذخیره و بررسی").click()
    expect(page.locator("#bot").get_by_text("آمار ربات:")).to_be_visible()
    expect(page.locator("#bot").get_by_text("سالم")).to_be_visible()
    if shot and shot_name:
        shot(page, shot_name)


def test_two_accounts_with_connections(page, stack: Stack, shot):
    _create_account(page, "سایکونت", "psychonet", "فیروزه‌ای")
    expect(page.get_by_text("اتصال به Telegram Ads هنوز برقرار نشده")).to_be_visible()
    # A wrong token is reported, not stored as healthy.
    page.get_by_label("توکن API").fill("not-a-real-token")
    page.get_by_role("button", name="ذخیره و بررسی").first.click()
    expect(page.locator("#telegram").get_by_text("خطا", exact=True)).to_be_visible()
    page.get_by_label("توکن تازه (برای جایگزینی)").fill("mocktoken-a")
    page.get_by_role("button", name="ذخیره و بررسی").first.click()
    expect(page.locator("#telegram").get_by_text("سالم")).to_be_visible()
    page.get_by_label("آدرس API ربات").fill(f"http://127.0.0.1:{stack.bot}/api/docs")
    page.get_by_label("نام کاربری ربات").fill("psychonet_test_bot")
    page.get_by_label("کلید API ربات").fill("botkey-a")
    page.locator("#bot").get_by_role("button", name="ذخیره و بررسی").click()
    expect(page.locator("#bot").get_by_text("سالم")).to_be_visible()
    shot(page, "03-settings-connected")

    _create_account(page, "دروازه آزادی", "darvaze", "بنفش")
    _connect(page, stack, "mocktoken-b", "botkey-b", "darvaze_test_bot")

    # Health check button works on demand.
    page.locator("#bot").get_by_role("button", name="بررسی سلامت").click()
    expect(page.get_by_text("اتصال ربات سالم است.")).to_be_visible()


def test_dashboards_are_separate(page, shot):
    _nav(page, "/accounts/psychonet/ads")
    expect(page.locator("tbody tr")).to_have_count(12, timeout=30_000)
    _nav(page, "/accounts/darvaze/ads")
    expect(page.locator("tbody tr")).to_have_count(4, timeout=30_000)
    expect(page.get_by_text("darvaze_main", exact=False).first).to_be_visible()
    expect(page.get_by_text("good_low_budget")).to_have_count(0)


def test_dashboard_live(page, shot):
    _nav(page, "/accounts/psychonet")
    expect(page.get_by_text("امروز، زنده")).to_be_visible()
    expect(page.get_by_text("خرج تبلیغات")).to_be_visible()
    # stats sync fills the daily chart
    expect(page.locator(".recharts-surface").first).to_be_visible(timeout=30_000)
    shot(page, "04-dashboard")
    _nav(page, "/")
    expect(page.get_by_text("سایکونت").first).to_be_visible()
    expect(page.get_by_text("دروازه آزادی").first).to_be_visible()
    shot(page, "05-overview")


def test_sync_interval_is_configurable(page):
    _nav(page, "/accounts/psychonet/settings")
    box = page.get_by_label("آگهی‌ها و موجودی (ثانیه)")
    box.fill("15")
    page.locator("#sync").get_by_role("button", name="ذخیره").click()
    expect(page.get_by_text("تنظیمات ذخیره شد.")).to_be_visible()
    page.reload()
    expect(page.get_by_label("آگهی‌ها و موجودی (ثانیه)")).to_have_value("15")
    # Manual sync button
    page.get_by_role("button", name="همگام‌سازی").click()
    expect(page.get_by_text(re.compile("همگام‌سازی (شروع شد|از قبل)"))).to_be_visible()


def test_referral_tag_attribution(page, stack: Stack, shot):
    _nav(page, "/accounts/psychonet/sales")
    page.get_by_role("button", name="برچسب جدید").click()
    dlg = page.get_by_role("dialog")
    dlg.get_by_label("نام برچسب").fill("کانال‌های تکنولوژی")
    dlg.get_by_label("شناسه‌ی عددی معرف").fill("9001")
    dlg.get_by_role("button", name="بررسی").click()
    expect(dlg.get_by_text(re.compile("کاربر دعوت کرده"))).to_be_visible()
    dlg.get_by_label("کد start (اختیاری)").fill("ref_a1")
    expect(dlg.get_by_text("https://t.me/psychonet_test_bot?start=ref_a1")).to_be_visible()
    dlg.get_by_role("button", name="ذخیره").click()
    expect(page.get_by_text("برچسب ساخته شد.")).to_be_visible()
    row = page.locator("tbody tr", has_text="کانال‌های تکنولوژی")
    expect(row).to_be_visible()
    # Next bot sync reads the 40 referred users of 9001.
    page.get_by_role("button", name="همگام‌سازی").click()
    expect(row.locator("td").nth(2)).to_have_text(re.compile("۴۰|۴۱"), timeout=30_000)
    stack.add_user("a", "9001")
    shot(page, "06-sales")


def test_claude_text_analysis_and_manual_edit(page, shot):
    _nav(page, "/settings")
    page.get_by_label("کلید API").fill("sk-ant-test")
    page.get_by_role("button", name="ذخیره").first.click()
    expect(page.get_by_text("ذخیره شد.")).to_be_visible()
    page.get_by_role("button", name="آزمایش اتصال").click()
    expect(page.get_by_text(re.compile("Claude پاسخ داد"))).to_be_visible()
    shot(page, "07-global-settings")

    _nav(page, "/accounts/psychonet/texts")
    page.get_by_role("button", name="وارد کردن از آگهی‌ها").click()
    expect(page.get_by_text(re.compile("متن از آگهی‌ها وارد شد"))).to_be_visible()
    card = page.locator("[data-slot=card]", has_text="متن آگهی‌ها").first
    card.get_by_role("button", name="تحلیل با Claude").click()
    card.get_by_role("button", name="شروع تحلیل").click()
    expect(card.get_by_text("پیشنهاد روشن ولی بدون نام برند.")).to_be_visible(timeout=20_000)
    expect(card.get_by_text("باید کوتاه شود")).to_be_visible()  # the 170-char rewrite is flagged
    shot(page, "08-texts-analysis")
    card.get_by_role("button", name="ویرایش و ذخیره").first.click()
    dlg = page.get_by_role("dialog")
    expect(dlg.get_by_label("متن")).to_have_value("سایکونت | تست رایگان VPN 👇")
    dlg.get_by_label("متن").fill("سایکونت | تست رایگان و پرسرعت 👇")
    dlg.get_by_role("button", name="ذخیره").click()
    expect(page.get_by_text("سایکونت | تست رایگان و پرسرعت 👇")).to_be_visible()


def _proposal_row(page, text: str):
    return page.locator("div.rounded-lg.border", has_text=text).filter(has=page.get_by_role("button", name="رد")).first


def test_good_ad_topped_up_after_a_gap_gets_no_withdraw(page, stack: Stack, shot):
    _nav(page, "/accounts/psychonet/ads")
    row = page.locator("tbody tr", has_text="sample_refill_gap")
    expect(row.get_by_text("بی‌بودجه از ۲۰ روز پیش")).to_be_visible(timeout=30_000)
    _nav(page, "/accounts/psychonet/proposals")
    expect(page.get_by_text("شارژ دوباره‌ی آگهی‌های خوبِ بی‌بودجه")).to_be_visible(timeout=30_000)
    refill = _proposal_row(page, "sample_refill_gap")
    expect(refill.get_by_text(re.compile("20 روز است بودجه ندارد"))).to_be_visible()
    shot(page, "14-refill-proposal")
    # The advertiser tops it up on ads.telegram.org; the next fast sync records it as funded from now.
    stack.set_ad("a", 11, remaining_budget=1.0)
    # The next fast sync (every 15 s, set earlier) re-runs the rules: the refill disappears and the ad,
    # whose funded time starts now, is not proposed for a withdrawal.
    expect(page.get_by_text(re.compile("20 روز است بودجه ندارد"))).to_have_count(0, timeout=45_000)
    withdraw = page.locator("[data-slot=card]", has_text="پس گرفتن بودجه‌ی بلااستفاده")
    expect(withdraw.get_by_text("sample_refill_gap")).to_have_count(0)
    _nav(page, "/accounts/psychonet/ads/11")
    expect(page.get_by_text("شارژ از صفر")).to_be_visible()
    expect(page.get_by_text("سایت تلگرام")).to_be_visible()


def test_replace_proposal_for_a_declined_ad(page, stack: Stack, shot):
    stack.set_balance("a", 10)
    _nav(page, "/accounts/psychonet/proposals")
    expect(page.get_by_text("جایگزینی آگهی (مشکل متن یا عکس)")).to_be_visible(timeout=20_000)
    row = _proposal_row(page, "Misleading urgency")
    row.get_by_role("button", name="ساخت آگهی جایگزین").click()
    dlg = page.get_by_role("dialog")
    expect(dlg.get_by_text("Misleading urgency").first).to_be_visible()
    expect(dlg.get_by_test_id("text-check").get_by_text(re.compile("فوریت ساختگی"))).to_be_visible()
    dlg.get_by_role("button", name="بررسی و اصلاح با Claude").click()
    expect(dlg.get_by_label("متن آگهی جایگزین")).to_have_value(re.compile("^سایکونت"), timeout=15_000)
    expect(dlg.get_by_text("با قوانین آگهی تلگرام می‌خواند.")).to_be_visible()
    dlg.get_by_role("button", name="پیش‌نمایش").click()
    expect(dlg.get_by_test_id("bulk-preview")).to_be_visible()
    expect(dlg.get_by_text(re.compile("اگر آگهی جدید رد شود، آگهی قدیمی دست نمی‌خورد"))).to_be_visible()
    shot(page, "15-replace-preview")
    dlg.get_by_role("button", name=re.compile("تأیید و اجرا")).click()
    expect(page).to_have_url(re.compile(r"/accounts/psychonet/bulk/\d+$"))
    item = page.get_by_test_id("bulk-item").first
    expect(item.get_by_text("در بررسی تلگرام")).to_be_visible(timeout=30_000)
    stack.review("a")
    expect(item.get_by_text("قدیمی بازنشسته شد")).to_be_visible(timeout=90_000)
    shot(page, "16-replace-done")


def test_bulk_text_change_with_preview_then_archive(page, stack: Stack, shot):
    stack.set_balance("a", 0.05)
    _nav(page, "/accounts/psychonet/ads")
    page.get_by_role("checkbox", name="انتخاب آگهی 4").click()
    page.get_by_role("checkbox", name="انتخاب آگهی 5").click()
    bar = page.get_by_role("toolbar", name="اقدام گروهی")
    expect(bar.get_by_text("۲")).to_be_visible()
    bar.get_by_role("button", name="متن/عکس").click()
    dlg = page.get_by_role("dialog")
    dlg.get_by_label("متن تازه (خالی = متن فعلی بماند)").fill("سایکونت | اینترنت پایدار با تست رایگان 👇")
    expect(dlg.get_by_text("با قوانین آگهی تلگرام می‌خواند.")).to_be_visible()
    dlg.get_by_role("radio", name=re.compile("از موجودی حساب")).click()
    dlg.get_by_role("button", name="پیش‌نمایش").click()
    expect(dlg.get_by_text(re.compile("موجودی حساب .* کافی نیست"))).to_be_visible()
    expect(dlg.get_by_role("button", name=re.compile("تأیید و اجرا"))).to_be_disabled()
    stack.set_balance("a", 10)
    dlg.get_by_role("button", name="بازگشت و ویرایش").click()
    dlg.get_by_role("radio", name=re.compile("انتقال از آگهی قدیمی")).click()
    dlg.get_by_role("button", name="پیش‌نمایش").click()
    expect(dlg.get_by_text(re.compile("آگهی جدید به بررسی تلگرام می‌رود")).first).to_be_visible()
    expect(dlg.get_by_text("سایکونت | اینترنت پایدار با تست رایگان 👇").first).to_be_visible()
    shot(page, "17-bulk-preview")
    dlg.get_by_role("button", name="تأیید و اجرا برای ۲ آگهی").click()
    expect(page).to_have_url(re.compile(r"/accounts/psychonet/bulk/\d+$"))
    items = page.get_by_test_id("bulk-item")
    expect(items).to_have_count(2)
    expect(items.get_by_text("در بررسی تلگرام")).to_have_count(2, timeout=30_000)
    stack.review("a")
    expect(items.get_by_text("قدیمی بازنشسته شد")).to_have_count(2, timeout=90_000)
    shot(page, "18-bulk-done")
    _nav(page, "/accounts/psychonet/ads?status=archived")
    expect(page.locator("tbody tr")).to_have_count(3, timeout=20_000)  # 4, 5 and the replaced declined ad
    expect(page.get_by_text("بایگانی").first).to_be_visible()


def test_referral_links_for_every_ad(page, stack: Stack, shot):
    _nav(page, "/accounts/psychonet/settings#tracking")
    page.get_by_label("تعداد آگهی در هر دسته").fill("20")
    page.get_by_label("فاصله‌ی دسته‌ها (ثانیه)").fill("0")
    page.get_by_label("حداکثر آگهی هم‌زمان در بررسی").fill("50")
    page.locator("#bulk").get_by_role("button", name="ذخیره").click()
    expect(page.get_by_text("تنظیمات ذخیره شد.").first).to_be_visible()
    page.get_by_label("شناسه‌ی عددی حساب‌های معرفِ خودتان").fill("9500\n9600\n9700")
    page.get_by_role("button", name="ذخیره‌ی استخر").click()
    expect(page.get_by_text("استخر معرف‌ها ذخیره شد.")).to_be_visible()
    page.get_by_role("button", name="بررسی معرف‌ها در ربات").click()
    expect(page.get_by_test_id("pool").get_by_text("در ربات هست")).to_have_count(3)
    expect(page.get_by_text("نیاز به پشتیبانی ربات دارد", exact=True)).to_be_visible()
    shot(page, "19-referrer-pool")

    _nav(page, "/accounts/psychonet/sales")
    page.get_by_role("link", name="ساخت برچسب برای همه").click()
    dlg = page.get_by_role("dialog")
    expect(dlg.get_by_text("لینک رفرال از استخر معرف‌ها")).to_be_visible()
    dlg.get_by_role("radio", name=re.compile("ویرایش در جا")).click()
    dlg.get_by_role("button", name="پیش‌نمایش").click()
    expect(dlg.get_by_text("تخصیص معرف‌ها")).to_be_visible()
    expect(dlg.get_by_text(re.compile("برچسب مشترک می‌گیرند")).first).to_be_visible()
    shot(page, "20-referral-preview")
    dlg.get_by_role("button", name=re.compile("تأیید و اجرا")).click()
    expect(page).to_have_url(re.compile(r"/accounts/psychonet/bulk/\d+$"))
    items = page.get_by_test_id("bulk-item")
    expect(items.first).to_be_visible()
    n = items.count()
    expect(items.get_by_text("در بررسی تلگرام")).to_have_count(n, timeout=60_000)
    stack.review("a")
    expect(items.get_by_text("تأیید شد")).to_have_count(n, timeout=90_000)
    _nav(page, "/accounts/psychonet/sales")
    expect(page.locator("tbody tr", has_text="start=9500").first).to_be_visible()
    expect(page.get_by_role("link", name="ساخت برچسب برای همه")).to_have_count(0)


def test_bot_diagnostics_explain_failures(page, stack: Stack, shot):
    _create_account(page, "عیب‌یابی", "diagtest", "کهربایی")
    page.get_by_label("آدرس API ربات").fill(f"http://127.0.0.1:{stack.bot}")
    page.get_by_label("نام کاربری ربات").fill("psychonet_test_bot")
    page.get_by_label("کلید API ربات").fill("botkey-limited")
    page.locator("#bot").get_by_role("button", name="ذخیره و بررسی").click()
    expect(page.locator("#bot").get_by_text("ناقص")).to_be_visible()
    page.get_by_role("button", name="عیب‌یابی اتصال ربات").click()
    diag = page.get_by_test_id("bot-diag")
    expect(diag.get_by_text("دسترسی «users» به کلید داده نشده").first).to_be_visible(timeout=20_000)
    expect(diag.get_by_text(re.compile("نام گزارش‌شده توسط ربات"))).to_be_visible()
    expect(page.get_by_role("button", name="کپی گزارش برای توسعه‌دهنده‌ی ربات")).to_be_visible()
    diag.get_by_text("جزئیات فنی").first.click()
    expect(diag.get_by_text("GET /api/statbot")).to_be_visible()
    shot(page, "21-bot-diag-denied")
    page.get_by_label("کلید API تازه (خالی = همان قبلی)").fill("botkey-500")
    page.locator("#bot").get_by_role("button", name="ذخیره و بررسی").click()
    expect(page.locator("#bot").get_by_text("-500")).to_be_visible()  # last four characters of the new key
    page.get_by_role("button", name="عیب‌یابی اتصال ربات").click()
    expect(diag.get_by_text("خطای داخلی ربات (HTTP 500)").first).to_be_visible(timeout=20_000)
    expect(diag.get_by_text(re.compile("Fatal error")).first).to_be_visible()
    assert "botkey-500" not in page.content()
    shot(page, "22-bot-diag-500")


def test_proposals_and_actions(page, shot):
    _nav(page, "/accounts/psychonet/proposals")
    expect(page.get_by_role("heading", name="پیشنهادها")).to_be_visible()
    page.get_by_role("button", name="بررسی دوباره‌ی قوانین").click()
    expect(page.get_by_text(re.compile("قوانین بررسی شد|پیشنهاد تازه ساخته شد"))).to_be_visible()
    expect(page.get_by_role("button", name="رد").first).to_be_visible(timeout=20_000)
    shot(page, "09-proposals")
    page.get_by_role("button", name="رد").first.click()
    expect(page.get_by_text(re.compile("رد شد؛ تا یک هفته"))).to_be_visible()

    _nav(page, "/accounts/psychonet/ads/3")
    expect(page.get_by_text("متن و لینک")).to_be_visible()
    shot(page, "10-ad-detail")
    page.get_by_role("button", name="اقدام‌ها").click()
    page.get_by_role("menuitem", name="توقف موقت").click()
    expect(page.get_by_text("توقف در صف رفت.")).to_be_visible()
    _nav(page, "/accounts/psychonet/activity")
    expect(page.get_by_text("صف کارها", exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile("توقف")).first).to_be_visible()
    shot(page, "11-activity")


def test_claude_account_analysis(page, shot):
    _nav(page, "/accounts/darvaze/analysis")
    page.get_by_role("button", name="تحلیل کامل حساب").click()
    expect(page.get_by_role("heading", name="تحلیل")).to_be_visible(timeout=20_000)
    expect(page.locator("table").first).to_be_visible()
    shot(page, "12-analysis")
    with page.expect_download() as dl:
        page.get_by_role("link", name="خروجی داده‌ها (ZIP)").click()
    assert dl.value.suggested_filename.startswith("tgads-darvaze-")


def test_new_ad_form(page, shot):
    _nav(page, "/accounts/darvaze/ads/new")
    page.get_by_label("نام کاربری کانال").fill("@sample_channel")
    page.get_by_label("متن آگهی").fill("دروازه آزادی | اینترنت آزاد 👇")
    page.get_by_label("بودجه‌ی اولیه").fill("5")
    page.get_by_role("button", name="ساخت و ارسال برای بررسی").click()
    expect(page.get_by_text(re.compile("موجودی حساب .* کافی نیست"))).to_be_visible()  # balance is 0.05
    page.get_by_label("بودجه‌ی اولیه").fill("0.04")
    shot(page, "13-ad-new")
    page.get_by_role("button", name="ساخت و ارسال برای بررسی").click()
    expect(page.get_by_text(re.compile("ساخته شد و برای بررسی"))).to_be_visible()
    expect(page).to_have_url(re.compile(r"/accounts/darvaze/ads/\d+$"))
    page.get_by_role("link", name="آگهی‌ها").first.click()
    expect(page).to_have_url(re.compile(r"/accounts/darvaze/ads$"))


OVERFLOW_JS = r"""
() => {
  // Elements that stick out of the page content area (or the screen), ignoring horizontally scrollable boxes.
  const main = document.querySelector('main');
  const ms = getComputedStyle(main), mr = main.getBoundingClientRect();
  const left = mr.left + parseFloat(ms.paddingLeft) - 1, right = mr.right - parseFloat(ms.paddingRight) + 1;
  const scrollBox = (el) => {
    for (let p = el.parentElement; p && p !== main; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true;
    }
    return false;
  };
  const bad = [];
  for (const el of main.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).position === 'fixed' || scrollBox(el)) continue;
    if (r.left < left || r.right > right) bad.push(`${el.tagName}.${String(el.className).slice(0, 60)} "${el.textContent.trim().slice(0, 30)}"`);
  }
  return {pageOverflow: document.documentElement.scrollWidth - window.innerWidth, bad: bad.slice(0, 5)};
}
"""

RESPONSIVE_PAGES = [
    "/",
    "/accounts/psychonet",
    "/accounts/psychonet/ads",
    "/accounts/psychonet/ads/3",
    "/accounts/psychonet/ads/new",
    "/accounts/psychonet/proposals",
    "/accounts/psychonet/bulk",
    "/accounts/psychonet/bulk/1",
    "/accounts/psychonet/ads?status=archived",
    "/accounts/psychonet/texts",
    "/accounts/psychonet/sales",
    "/accounts/psychonet/analysis",
    "/accounts/psychonet/activity",
    "/accounts/psychonet/settings",
    "/settings",
    "/accounts/new",
]


@pytest.mark.parametrize("width", [360, 390, 768])
def test_every_page_fits_small_screens(browser, ctx, stack: Stack, shot, width, errors):
    mctx = browser.new_context(
        viewport={"width": width, "height": 800},
        device_scale_factor=2,
        is_mobile=width < 700,
        has_touch=width < 700,
        base_url=stack.base,
        storage_state=ctx.storage_state(),
    )
    p = mctx.new_page()
    p.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    problems = []
    try:
        for path in RESPONSIVE_PAGES:
            p.goto(path)
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(400)
            res = p.evaluate(OVERFLOW_JS)
            if res["pageOverflow"] > 1 or res["bad"]:
                problems.append(f"{width}px {path}: {res}")
            if width == 390:
                shot(p, "m-" + (path.strip("/").replace("/", "-") or "overview"))
    finally:
        mctx.close()
    assert problems == []


def test_mobile_menu(browser, ctx, stack: Stack, shot):
    mctx = browser.new_context(
        viewport=MOBILE, is_mobile=True, has_touch=True, base_url=stack.base, storage_state=ctx.storage_state()
    )
    p = mctx.new_page()
    p.goto("/accounts/psychonet")
    p.get_by_role("button", name="منو").click()
    expect(p.get_by_role("dialog").get_by_role("link", name="آگهی‌ها")).to_be_visible()
    shot(p, "m-menu", full=False)
    p.get_by_role("dialog").get_by_role("link", name="آگهی‌ها").click()
    expect(p).to_have_url(re.compile("/accounts/psychonet/ads$"))
    expect(p.get_by_role("dialog")).to_have_count(0)
    mctx.close()


def test_no_browser_errors(errors):
    # HTTP 4xx answers we triggered on purpose (wrong password, low balance) show up as
    # "Failed to load resource"; anything else is a real JavaScript error.
    real = [e for e in errors if "Failed to load resource" not in e]
    assert real == []
