"""HAX_NON_ROOT Telegram bot — independent implementation for Nacer_22."""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import time
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

from config import ADMIN_IDS, BOT_BRAND, OWNER_BRAND, SUPPORT_CHANNEL, BOT_TOKEN
from hax_api import hax_api, HaxApiError
import storage as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger(BOT_BRAND)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def fmt(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def duration_label(seconds: int) -> str:
    seconds = int(seconds)
    units = ((2592000, "شهر"), (604800, "أسبوع"), (86400, "يوم"), (3600, "ساعة"), (60, "دقيقة"), (1, "ثانية"))
    for size, label in units:
        if seconds >= size and seconds % size == 0:
            n = seconds // size
            if label == "ساعة" and n == 1: return "ساعة واحدة"
            if label == "يوم" and n == 1: return "يوم واحد"
            return f"{n} {label}"
    return f"{seconds} ثانية"


def main_keyboard(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔑 شراء مفتاح", callback_data="menu:buy"), InlineKeyboardButton("💎 مفاتيحي", callback_data="menu:keys")],
        [InlineKeyboardButton("🛍️ المتجر", callback_data="menu:shop"), InlineKeyboardButton("🎒 مشترياتي", callback_data="menu:purchases")],
        [InlineKeyboardButton("♻️ إعادة ضبط المفتاح", callback_data="menu:reset")],
        [InlineKeyboardButton("🎁 الهدية اليومية", callback_data="menu:daily"), InlineKeyboardButton("💰 رصيدي", callback_data="menu:balance")],
        [InlineKeyboardButton("👥 دعوة الأصدقاء", callback_data="menu:referral"), InlineKeyboardButton("📊 إحصائياتي", callback_data="menu:stats")],
    ]
    if SUPPORT_CHANNEL:
        rows.append([InlineKeyboardButton("📢 قناة الدعم", url=SUPPORT_CHANNEL)])
    if is_admin(uid):
        rows.append([InlineKeyboardButton("⚙️ لوحة إدارة HAX_NON_ROOT", callback_data="admin:panel")])
    return InlineKeyboardMarkup(rows)


def back_keyboard(target: str = "menu:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data=target)]])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 نظرة عامة", callback_data="admin:overview"), InlineKeyboardButton("🔑 إنشاء مفاتيح", callback_data="admin:create")],
        [InlineKeyboardButton("📋 جميع المفاتيح", callback_data="admin:keys"), InlineKeyboardButton("🔎 فحص كود", callback_data="admin:check")],
        [InlineKeyboardButton("🔧 صيانة التطبيق", callback_data="admin:maintenance"), InlineKeyboardButton("📢 القنوات المطلوبة", callback_data="admin:channels")],
        [InlineKeyboardButton("👥 المستخدمون", callback_data="admin:users"), InlineKeyboardButton("💰 تعديل النقاط", callback_data="admin:give")],
        [InlineKeyboardButton("🛍️ إضافة منتج", callback_data="admin:addproduct"), InlineKeyboardButton("📦 إدارة المنتجات", callback_data="admin:products")],
        [InlineKeyboardButton("📣 رسالة جماعية", callback_data="admin:broadcast"), InlineKeyboardButton("💾 نسخة احتياطية", callback_data="admin:backup")],
        [InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin:stats")],
        [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="menu:home")],
    ])


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    info = db.get_user(user.id) or {}
    text = (
        f"👋 أهلاً <b>{esc(user.first_name)}</b>\n\n"
        f"<b>{BOT_BRAND}</b> · {OWNER_BRAND}\n"
        f"💰 رصيدك: <b>{fmt(info.get('points', 0))}</b> نقطة\n"
        f"🔑 مفاتيحك: <b>{len(info.get('keys', []))}</b>\n\n"
        "اختر الخدمة من القائمة:"
    )
    markup = main_keyboard(user.id)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def check_required_channels(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, list[dict]]:
    channels = db.get_settings().get("required_channels", [])
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return not missing, missing


def channel_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for channel in channels:
        url = channel.get("url") or f"https://t.me/{str(channel.get('chat_id', '')).lstrip('@')}"
        rows.append([InlineKeyboardButton("📢 " + str(channel.get("title", "قناة"))[:50], url=url)])
    rows.append([InlineKeyboardButton("✅ تحقّق من الاشتراك", callback_data="user:checksub")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    ref_code = context.args[0] if context.args else ""
    profile, created, referrer = db.register_user(user.id, user.first_name or "", user.username or "", ref_code)
    if created and referrer:
        try:
            await context.bot.send_message(referrer, f"🎉 انضم مستخدم عبر رابطك! حصلت على نقاط الإحالة.\nرصيدك الآن: {fmt((db.get_user(referrer) or {}).get('points', 0))}")
        except Exception:
            pass
    if profile.get("is_banned") and not is_admin(user.id):
        await update.message.reply_text("🚫 حسابك محظور من استخدام البوت.")
        return
    if not is_admin(user.id):
        try:
            state = await asyncio.to_thread(hax_api.maintenance)
            if state.get("maintenance", {}).get("client"):
                await update.message.reply_text(db.get_settings().get("maintenance_message", "البوت تحت الصيانة."))
                return
        except HaxApiError as exc:
            log.warning("Maintenance status check failed: %s", exc)
        ok, missing = await check_required_channels(user.id, context)
        if not ok:
            await update.message.reply_text("⚠️ اشترك في القنوات التالية أولاً ثم اضغط تحقق:", reply_markup=channel_keyboard(missing))
            return
    if created:
        for aid in ADMIN_IDS:
            if aid != user.id:
                try:
                    await context.bot.send_message(aid, f"🆕 مستخدم جديد في {BOT_BRAND}\n👤 {esc(user.first_name)}\n🆔 <code>{user.id}</code>", parse_mode=ParseMode.HTML)
                except Exception:
                    pass
    await send_home(update, context)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للإدارة فقط.")
        return
    await update.message.reply_text("⚙️ لوحة إدارة HAX_NON_ROOT", reply_markup=admin_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""
    user = db.get_user(uid)
    if user and user.get("is_banned") and not is_admin(uid):
        await q.edit_message_text("🚫 حسابك محظور.")
        return

    if data == "menu:home":
        await send_home(update, context)
        return
    if data == "user:checksub":
        ok, missing = await check_required_channels(uid, context)
        if ok:
            await q.edit_message_text("✅ تم التحقق من الاشتراك.")
            await send_home(update, context)
        else:
            await q.edit_message_text("❌ لم تكتمل عضويتك في القنوات المطلوبة.", reply_markup=channel_keyboard(missing))
        return

    if data == "menu:buy":
        settings = db.get_settings()
        durations = settings.get("key_durations", {})
        rows = []
        for seconds, price in sorted(durations.items(), key=lambda item: int(item[0])):
            rows.append([InlineKeyboardButton(f"⏱ {duration_label(int(seconds))} — {fmt(price)} نقطة", callback_data=f"buy:{seconds}")])
        rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="menu:home")])
        await q.edit_message_text(f"🔑 <b>شراء مفتاح HAX</b>\nرصيدك الحالي: <b>{fmt((user or {}).get('points', 0))}</b> نقطة\nاختر المدة:", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("buy:"):
        debited = False
        api_key_created = False
        price = -1
        try:
            seconds = int(data.split(":", 1)[1])
            price = int(db.get_settings().get("key_durations", {}).get(str(seconds), -1))
            if price < 0 or not db.debit_points(uid, price):
                await q.edit_message_text("❌ رصيدك غير كافٍ أو هذه المدة غير متاحة.", reply_markup=back_keyboard("menu:buy"))
                return
            debited = True
            keys = await asyncio.to_thread(hax_api.create_keys, seconds * 1000, 1, 1)
            if not keys:
                raise HaxApiError("لم يُرجع الخادم أي مفتاح.")
            api_key_created = True
            key = keys[0]
            db.add_owned_key(uid, {"id": key["id"], "code": key["code"], "duration_ms": seconds * 1000, "duration_label": duration_label(seconds), "created_at": key.get("createdAt", ""), "last_reset": 0})
            await q.edit_message_text(
                "✅ <b>تم إنشاء مفتاحك بنجاح!</b>\n\n"
                f"🔑 الكود: <code>{esc(key['code'])}</code>\n"
                f"⏱ المدة: <b>{duration_label(seconds)}</b>\n"
                "⌛ يبدأ احتساب الصلاحية عند أول تفعيل وفق نظام خادمك.\n\nاحتفظ بالكود ولا تشاركه.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 مفاتيحي", callback_data="menu:keys")], [InlineKeyboardButton("⬅️ القائمة", callback_data="menu:home")]]),
            )
        except HaxApiError as exc:
            if debited and not api_key_created:
                db.add_points(uid, price)
            await q.edit_message_text(f"⚠️ تعذر إنشاء المفتاح: {esc(exc)}", reply_markup=back_keyboard("menu:buy"), parse_mode=ParseMode.HTML)
        except Exception:
            log.exception("Key purchase failed")
            await q.edit_message_text("حدث خطأ أثناء شراء المفتاح. إن خُصم رصيدك ولم يصلك الكود، تواصل مع الإدارة.", reply_markup=back_keyboard("menu:buy"))
        return

    if data == "menu:keys":
        owned = (user or {}).get("keys", [])
        if not owned:
            await q.edit_message_text("📭 لا تملك مفاتيح بعد.", reply_markup=back_keyboard())
            return
        rows = []
        text = "💎 <b>مفاتيحك</b>\n\n"
        for key in owned[-15:][::-1]:
            text += f"🔑 <code>{esc(key.get('code'))}</code>\n⏱ {esc(key.get('duration_label', ''))}\n\n"
            rows.append([InlineKeyboardButton("♻️ إعادة ضبط " + str(key.get("code", ""))[:12], callback_data=f"reset:{key.get('id')}")])
        rows.append([InlineKeyboardButton("⬅️ القائمة", callback_data="menu:home")])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "menu:reset":
        owned = (user or {}).get("keys", [])
        rows = [[InlineKeyboardButton(str(k.get("code", "مفتاح"))[:22], callback_data=f"reset:{k.get('id')}")] for k in owned[-20:]]
        rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="menu:home")])
        await q.edit_message_text("اختر المفتاح الذي تريد إزالة أجهزته المسجلة منه:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("reset:"):
        key_id = data.split(":", 1)[1]
        own = next((k for k in (user or {}).get("keys", []) if k.get("id") == key_id), None)
        if not own:
            await q.edit_message_text("❌ لا يمكن العثور على هذا المفتاح في حسابك.", reply_markup=back_keyboard())
            return
        last_reset = int(own.get("last_reset", 0))
        wait = 12 * 3600 - (int(time.time()) - last_reset)
        if wait > 0 and not is_admin(uid):
            await q.edit_message_text(f"⏳ يمكنك إعادة ضبط هذا المفتاح بعد {wait // 3600} ساعة و{(wait % 3600) // 60} دقيقة.", reply_markup=back_keyboard("menu:keys"))
            return
        try:
            result = await asyncio.to_thread(hax_api.reset_key, key_id)
            def update_reset(data_store):
                for item in data_store["users"].get(str(uid), {}).get("keys", []):
                    if item.get("id") == key_id:
                        item["last_reset"] = int(time.time())
                        break
            db.mutate(update_reset)
            await q.edit_message_text(f"✅ تمت إعادة ضبط المفتاح.\nعدد الأجهزة التي أزيلت: {fmt(result.get('resetDevices', 0))}", reply_markup=back_keyboard("menu:keys"))
        except HaxApiError as exc:
            await q.edit_message_text(f"❌ فشلت إعادة الضبط: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("menu:keys"))
        return

    if data == "menu:balance":
        await q.edit_message_text(f"💰 رصيدك الحالي: <b>{fmt((user or {}).get('points', 0))}</b> نقطة", parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        return
    if data == "menu:daily":
        settings = db.get_settings()
        cooldown = int(settings.get("daily_gift_cooldown", 86400))
        last = int((user or {}).get("last_daily_gift", 0))
        remaining = cooldown - (int(time.time()) - last)
        if remaining > 0:
            await q.edit_message_text(f"🎁 حصلت على هديتك بالفعل.\nالعودة بعد {remaining // 3600} ساعة و{(remaining % 3600) // 60} دقيقة.", reply_markup=back_keyboard())
            return
        amount = int(settings.get("daily_gift_points", 3))
        def claim(data_store):
            item = data_store["users"].get(str(uid))
            if not item or int(item.get("last_daily_gift", 0)) + cooldown > int(time.time()):
                return False
            item["last_daily_gift"] = int(time.time())
            item["points"] = int(item.get("points", 0)) + amount
            data_store["stats"]["points_issued"] += amount
            return True
        if db.mutate(claim):
            await q.edit_message_text(f"🎉 استلمت هديتك اليومية: <b>+{amount}</b> نقطة!", parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        else:
            await q.edit_message_text("لقد استلمت الهدية بالفعل.", reply_markup=back_keyboard())
        return
    if data == "menu:referral":
        code = (user or {}).get("referral_code", "")
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={code}"
        await q.edit_message_text(f"👥 <b>رابط دعوتك</b>\n\n<code>{link}</code>\n\nمكافأة الإحالة: {fmt(db.get_settings().get('referral_points', 5))} نقطة عن كل مستخدم جديد.", parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        return
    if data == "menu:stats":
        await q.edit_message_text(f"📊 <b>إحصائياتك</b>\nعدد الإحالات: {fmt((user or {}).get('total_referrals', 0))}\nعدد المفاتيح: {len((user or {}).get('keys', []))}\nعدد المشتريات: {len((user or {}).get('purchases', []))}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        return
    if data == "menu:shop":
        products = db.all_products()
        active = [(pid, p) for pid, p in products.items() if p.get("active", True)]
        if not active:
            await q.edit_message_text("🛍️ المتجر لا يحتوي على منتجات حالياً.", reply_markup=back_keyboard())
            return
        rows = [[InlineKeyboardButton(f"{p['name'][:30]} — {fmt(p['price'])} نقطة", callback_data=f"product:{pid}")] for pid, p in active]
        rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="menu:home")])
        await q.edit_message_text("🛍️ <b>المتجر</b>\nاختر المنتج:", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("product:"):
        product_id = data.split(":", 1)[1]
        product = db.all_products().get(product_id)
        if not product or not product.get("active", True):
            await q.edit_message_text("المنتج غير متاح.", reply_markup=back_keyboard("menu:shop"))
            return
        price = int(product.get("price", 0))
        if not db.debit_points(uid, price):
            await q.edit_message_text("رصيدك غير كافٍ لشراء هذا المنتج.", reply_markup=back_keyboard("menu:shop"))
            return
        db.record_product_sale(uid, product_id)
        await q.edit_message_text(f"✅ تم شراء <b>{esc(product['name'])}</b>\n\n{esc(product.get('description', ''))}\n\n<b>محتوى المنتج:</b>\n<code>{esc(product.get('content', ''))}</code>", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("menu:shop"))
        return
    if data == "menu:purchases":
        purchases = (user or {}).get("purchases", [])
        if not purchases:
            await q.edit_message_text("لم تقم بأي عملية شراء بعد.", reply_markup=back_keyboard())
            return
        lines = [f"• {esc(p.get('name', 'منتج'))} — {datetime.fromtimestamp(int(p.get('at', 0))).strftime('%Y-%m-%d')}" for p in purchases[-15:][::-1]]
        await q.edit_message_text("🎒 <b>مشترياتك</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        return

    if data.startswith("admin:") and not is_admin(uid):
        await q.edit_message_text("⛔ ليس لديك صلاحية الإدارة.")
        return
    if data == "admin:panel":
        await q.edit_message_text("⚙️ <b>لوحة إدارة HAX_NON_ROOT</b>", parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
        return
    if data == "admin:overview":
        try:
            result = await asyncio.to_thread(hax_api.overview)
            await q.edit_message_text(f"📈 <b>نظرة عامة على HAX</b>\nالموزعون: {fmt(result.get('resellers', 0))}\nالمفاتيح: {fmt(result.get('keys', 0))}\nالمفاتيح النشطة: {fmt(result.get('activeKeys', 0))}\nالرصيد الكلي للموزعين: {fmt(result.get('balance', 0))}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        except HaxApiError as exc:
            await q.edit_message_text(f"تعذر جلب الإحصائيات: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:create":
        durations = db.get_settings().get("key_durations", {})
        rows = [[InlineKeyboardButton(duration_label(int(sec)), callback_data=f"admin:duration:{sec}")] for sec in sorted(durations, key=int)]
        rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:panel")])
        await q.edit_message_text("🔑 اختر مدة المفاتيح التي تريد إنشاءها مباشرة على خادم HAX:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("admin:duration:"):
        seconds = int(data.rsplit(":", 1)[1])
        context.user_data["flow"] = "admin_create_quantity"
        context.user_data["duration_seconds"] = seconds
        await q.edit_message_text(f"المدة: {duration_label(seconds)}\nأرسل عدد المفاتيح (1 إلى 50):", reply_markup=back_keyboard("admin:create"))
        return
    if data == "admin:keys":
        try:
            keys = await asyncio.to_thread(hax_api.list_keys)
            if not keys:
                await q.edit_message_text("لا توجد مفاتيح في خادم HAX.", reply_markup=back_keyboard("admin:panel"))
                return
            lines = []
            for item in keys[:15]:
                lines.append(f"• <code>{esc(item.get('code', ''))}</code> — {esc(item.get('status', 'UNKNOWN'))} — {esc(item.get('durationLabel', ''))}")
            await q.edit_message_text("📋 <b>أحدث المفاتيح في خادمك</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        except HaxApiError as exc:
            await q.edit_message_text(f"تعذر جلب المفاتيح: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:check":
        context.user_data["flow"] = "admin_check_code"
        await q.edit_message_text("أرسل الكود الذي تريد فحصه:", reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:maintenance":
        try:
            state = await asyncio.to_thread(hax_api.maintenance)
            active = bool(state.get("maintenance", {}).get("client"))
            await q.edit_message_text(f"حالة صيانة التطبيق: {'🔴 مفعلة' if active else '🟢 متوقفة'}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 تفعيل الصيانة" if not active else "🟢 إيقاف الصيانة", callback_data=f"admin:mainttoggle:{0 if active else 1}")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:panel")],
            ]))
        except HaxApiError as exc:
            await q.edit_message_text(f"تعذر قراءة حالة الصيانة: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data.startswith("admin:mainttoggle:"):
        active = data.endswith(":1")
        try:
            await asyncio.to_thread(hax_api.set_maintenance, active)
            await q.edit_message_text(f"✅ {'تم تفعيل' if active else 'تم إيقاف'} صيانة التطبيق على خادم HAX.", reply_markup=back_keyboard("admin:panel"))
        except HaxApiError as exc:
            await q.edit_message_text(f"فشل تحديث الصيانة: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:users":
        users = db.all_users()
        recent = sorted(users.values(), key=lambda x: x.get("joined_at", 0), reverse=True)[:12]
        lines = [f"• {esc(u.get('first_name', 'مستخدم'))} — <code>{u['user_id']}</code> — {fmt(u.get('points', 0))} نقطة" for u in recent]
        await q.edit_message_text(f"👥 <b>المستخدمون: {len(users)}</b>\n\n" + ("\n".join(lines) if lines else "لا يوجد مستخدمون."), parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:give":
        context.user_data["flow"] = "admin_give_user"
        await q.edit_message_text("أرسل Telegram ID للمستخدم:", reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:broadcast":
        context.user_data["flow"] = "admin_broadcast"
        await q.edit_message_text("أرسل نص الرسالة الجماعية:", reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:backup":
        snapshot = json.dumps({"users": db.all_users(), "products": db.all_products(), "settings": db.get_settings(), "stats": db.stats()}, ensure_ascii=False, indent=2).encode("utf-8")
        document = io.BytesIO(snapshot)
        document.name = "HAX_NON_ROOT_backup.json"
        await context.bot.send_document(uid, document=document, caption="💾 نسخة احتياطية من بيانات البوت (لا تحتوي على أسرار الخادم).")
        return
    if data == "admin:stats":
        s = db.stats()
        await q.edit_message_text(f"📊 <b>إحصائيات {BOT_BRAND}</b>\nالمستخدمون: {fmt(s.get('total_users', 0))}\nالمنتجات: {fmt(s.get('total_products', 0))}\nالمفاتيح التي أنشأها البوت: {fmt(s.get('keys_created', 0))}\nالمنتجات المباعة: {fmt(s.get('products_sold', 0))}\nالنقاط الممنوحة: {fmt(s.get('points_issued', 0))}", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:addproduct":
        context.user_data["flow"] = "product_name"
        await q.edit_message_text("أرسل اسم المنتج:", reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:products":
        products = db.all_products()
        if not products:
            await q.edit_message_text("لا توجد منتجات في المتجر.", reply_markup=back_keyboard("admin:panel"))
            return
        lines = [f"• {esc(p.get('name'))} — {fmt(p.get('price'))} نقطة — مبيعات: {fmt(p.get('sold_count', 0))}" for p in products.values()]
        await q.edit_message_text("🛍️ <b>منتجات المتجر</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return
    if data == "admin:channels":
        channels = db.get_settings().get("required_channels", [])
        lines = [f"• {esc(c.get('title'))}: <code>{esc(c.get('chat_id'))}</code>" for c in channels]
        await q.edit_message_text("📢 <b>القنوات المطلوبة</b>\n\n" + ("\n".join(lines) if lines else "لا توجد قنوات مطلوبة.") + "\n\nلإضافة قناة أرسل /addchannel متبوعاً بمعرفها.", parse_mode=ParseMode.HTML, reply_markup=back_keyboard("admin:panel"))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data.get("flow")
    if not flow:
        return
    uid = update.effective_user.id
    message = (update.message.text or "").strip()
    if flow.startswith("admin_") or flow.startswith("product_"):
        if not is_admin(uid):
            context.user_data.clear()
            await update.message.reply_text("⛔ غير مصرح.")
            return
    if message.lower() in ("الغاء", "إلغاء", "/cancel"):
        context.user_data.clear()
        await update.message.reply_text("تم إلغاء العملية.", reply_markup=main_keyboard(uid))
        return

    if flow == "admin_create_quantity":
        if not message.isdigit() or not 1 <= int(message) <= 50:
            await update.message.reply_text("أرسل رقماً من 1 إلى 50.")
            return
        context.user_data["create_quantity"] = int(message)
        context.user_data["flow"] = "admin_create_devices"
        await update.message.reply_text("أرسل عدد الأجهزة المسموح بها لكل مفتاح (1 أو 2 أو 3 أو 5):")
        return
    if flow == "admin_create_devices":
        if message not in ("1", "2", "3", "5"):
            await update.message.reply_text("القيم المقبولة: 1 أو 2 أو 3 أو 5.")
            return
        seconds = int(context.user_data.get("duration_seconds", 3600))
        quantity = int(context.user_data.get("create_quantity", 1))
        context.user_data.clear()
        try:
            keys = await asyncio.to_thread(hax_api.create_keys, seconds * 1000, quantity, int(message))
            if not keys:
                raise HaxApiError("لم يُرجع الخادم مفاتيح.")
            lines = [f"<code>{esc(k.get('code'))}</code>" for k in keys]
            await update.message.reply_text(f"✅ تم إنشاء {len(keys)} مفتاحاً على خادم HAX.\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
        except HaxApiError as exc:
            await update.message.reply_text(f"فشل إنشاء المفاتيح: {esc(exc)}", parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
        return
    if flow == "admin_check_code":
        context.user_data.clear()
        try:
            result = await asyncio.to_thread(hax_api.check_key, message)
            labels = {"invalid_format": "صيغة الكود غير صحيحة", "code_not_found": "الكود غير موجود", "code_disabled": "الكود معطل", "code_expired": "الكود منتهي", "maintenance": "التطبيق تحت الصيانة"}
            if result.get("valid"):
                text = f"✅ الكود صالح\nبدأ التفعيل: {'نعم' if result.get('started') else 'لا'}\nتاريخ الانتهاء: {esc(result.get('expires_at') or 'لم يبدأ بعد')}"
            else:
                text = "❌ " + labels.get(result.get("reason", ""), str(result.get("reason", "غير صالح")))
            await update.message.reply_text(text, reply_markup=admin_keyboard())
        except HaxApiError as exc:
            await update.message.reply_text(f"خطأ في الفحص: {esc(exc)}", reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
        return
    if flow == "admin_give_user":
        if not message.isdigit() or not db.get_user(int(message)):
            await update.message.reply_text("لم أجد مستخدماً بهذا المعرف. أرسل Telegram ID صحيحاً.")
            return
        context.user_data["target_user"] = int(message)
        context.user_data["flow"] = "admin_give_amount"
        await update.message.reply_text("أرسل عدد النقاط (استخدم رقماً سالباً للخصم):")
        return
    if flow == "admin_give_amount":
        try:
            amount = int(message)
            if amount == 0 or abs(amount) > 1000000:
                raise ValueError
        except ValueError:
            await update.message.reply_text("أرسل رقماً غير صفري لا يتجاوز مليوناً بالقيمة المطلقة.")
            return
        target = int(context.user_data["target_user"])
        context.user_data.clear()
        db.add_points(target, amount)
        await update.message.reply_text(f"✅ تم تحديث رصيد المستخدم إلى {fmt((db.get_user(target) or {}).get('points', 0))} نقطة.", reply_markup=admin_keyboard())
        try:
            await context.bot.send_message(target, f"تم تحديث رصيدك بمقدار {amount:+d} نقطة.")
        except Exception:
            pass
        return
    if flow == "admin_broadcast":
        context.user_data.clear()
        users = db.all_users()
        sent = failed = 0
        await update.message.reply_text("بدأ إرسال الرسالة الجماعية...")
        for target in list(users):
            try:
                await context.bot.send_message(int(target), message)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.04)
        await update.message.reply_text(f"✅ اكتمل البث.\nتم الإرسال: {sent}\nتعذر الإرسال: {failed}", reply_markup=admin_keyboard())
        return
    if flow == "product_name":
        context.user_data["product_name"] = message[:80]
        context.user_data["flow"] = "product_price"
        await update.message.reply_text("أرسل سعر المنتج بالنقاط:")
        return
    if flow == "product_price":
        if not message.isdigit() or not 0 <= int(message) <= 1000000:
            await update.message.reply_text("السعر يجب أن يكون رقماً من 0 إلى 1000000.")
            return
        context.user_data["product_price"] = int(message)
        context.user_data["flow"] = "product_description"
        await update.message.reply_text("أرسل وصف المنتج:")
        return
    if flow == "product_description":
        context.user_data["product_description"] = message[:500]
        context.user_data["flow"] = "product_content"
        await update.message.reply_text("أرسل محتوى المنتج الذي سيحصل عليه المشتري:")
        return
    if flow == "product_content":
        values = dict(context.user_data)
        context.user_data.clear()
        pid = db.add_product(values["product_name"], values["product_price"], values["product_description"], message)
        await update.message.reply_text(f"✅ تمت إضافة المنتج إلى متجر HAX_NON_ROOT.\nالمعرف: <code>{pid}</code>", parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
        return


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("الاستخدام: /addchannel @channel أو -1001234567890")
        return
    chat_id = context.args[0]
    try:
        chat = await context.bot.get_chat(chat_id)
        channel = {"chat_id": chat_id, "title": chat.title or str(chat_id), "url": f"https://t.me/{chat.username}" if chat.username else ""}
        settings = db.get_settings()
        channels = settings.get("required_channels", [])
        if not any(str(c.get("chat_id")) == str(chat_id) for c in channels):
            channels.append(channel)
            db.update_settings({"required_channels": channels})
        await update.message.reply_text(f"✅ تمت إضافة القناة: {esc(channel['title'])}")
    except Exception as exc:
        await update.message.reply_text(f"تعذر إضافة القناة. تحقق من أن البوت مشرف فيها.\n{esc(exc)}")


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("الاستخدام: /removechannel @channel أو -100...")
        return
    target = context.args[0]
    settings = db.get_settings()
    channels = [c for c in settings.get("required_channels", []) if str(c.get("chat_id")) != target]
    db.update_settings({"required_channels": channels})
    await update.message.reply_text("✅ تم تحديث قائمة القنوات.")


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=main_keyboard(update.effective_user.id))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled bot error", exc_info=context.error)


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("addchannel", add_channel))
    application.add_handler(CommandHandler("removechannel", remove_channel))
    application.add_handler(CommandHandler("cancel", cancel_flow))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(error_handler)
    log.info("Starting %s for %s", BOT_BRAND, OWNER_BRAND)
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
