"""
Dota 2 Telegram-бот — простая версия под одного пользователя (тебя).

Steam ID вписывается один раз прямо в этот файл, дальше просто запускаешь
и пользуешься. Меню на кнопках, разбито на категории.

Настройка:
1. pip install -r requirements.txt
2. Впиши BOT_TOKEN и STEAM_ID32 ниже
3. python bot.py
"""

import os
import asyncio
import logging
from datetime import datetime
from collections import defaultdict

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКИ ==========
# На Railway задаются через Variables в панели проекта.
# Локально можно оставить как есть — сработают значения по умолчанию ниже.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8622567639:AAEw-Zh6UDN7ROxjlI3AY_rfol67StN0Ilc")
STEAM_ID32 = os.getenv("STEAM_ID32", "1125119990")
# =============================================================

OPENDOTA_API = "https://api.opendota.com/api"
MIN_GAMES_FOR_TOP = 10
HIDDEN_GEM_MAX_GAMES = 9
STREAK_WARNING_THRESHOLD = 3

_hero_names_cache = None


# ========== ЗАПРОСЫ К OPENDOTA ==========

def get_hero_names():
    global _hero_names_cache
    if _hero_names_cache is None:
        resp = requests.get(f"{OPENDOTA_API}/heroes", timeout=15)
        resp.raise_for_status()
        _hero_names_cache = {h["id"]: h["localized_name"] for h in resp.json()}
    return _hero_names_cache


def get_player_heroes():
    resp = requests.get(f"{OPENDOTA_API}/players/{STEAM_ID32}/heroes", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    logger.info("get_player_heroes: получено %s записей, суммарно игр=%s",
                len(data), sum(h.get("games", 0) for h in data))
    return data


def get_recent_matches(limit=100):
    resp = requests.get(
        f"{OPENDOTA_API}/players/{STEAM_ID32}/matches",
        params={"limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info("get_recent_matches: получено %s матчей", len(data))
    return data


def get_player_totals():
    resp = requests.get(f"{OPENDOTA_API}/players/{STEAM_ID32}/totals", timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_hero_stats():
    resp = requests.get(f"{OPENDOTA_API}/heroStats", timeout=15)
    resp.raise_for_status()
    return resp.json()


def match_won(m):
    return (m["player_slot"] < 128) == m["radiant_win"]


# ========== МЕНЮ ==========

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Герои", callback_data="menu_heroes")],
        [InlineKeyboardButton("📈 Тренды", callback_data="menu_trends")],
        [InlineKeyboardButton("🎮 Игра", callback_data="menu_game")],
        [InlineKeyboardButton("🔥 Мета", callback_data="menu_meta")],
    ]
    return InlineKeyboardMarkup(keyboard)


def heroes_menu():
    keyboard = [
        [InlineKeyboardButton("🏆 Топ по винрейту", callback_data="top_heroes")],
        [InlineKeyboardButton("🎮 Топ по кол-ву игр", callback_data="most_played")],
        [InlineKeyboardButton("💎 Качай чаще", callback_data="hidden_gems")],
        [InlineKeyboardButton("📉 Худшие герои", callback_data="worst_heroes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def trends_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Динамика винрейта", callback_data="trend")],
        [InlineKeyboardButton("🔥 Текущая серия", callback_data="streak")],
        [InlineKeyboardButton("🕐 Время суток", callback_data="mood")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def game_menu():
    keyboard = [
        [InlineKeyboardButton("🕹 Последняя игра", callback_data="last_match")],
        [InlineKeyboardButton("👁 Варды", callback_data="vision")],
        [InlineKeyboardButton("📊 Средние показатели", callback_data="benchmarks")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def meta_menu():
    keyboard = [
        [InlineKeyboardButton("⚔️ Кор (Carry)", callback_data="meta_core")],
        [InlineKeyboardButton("🌲 Мидлейн", callback_data="meta_mid")],
        [InlineKeyboardButton("🛡 Оффлейн", callback_data="meta_offlane")],
        [InlineKeyboardButton("💚 Саппорт", callback_data="meta_support")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_button(target="menu_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=target)]])


MENUS = {
    "menu_main": ("Выбери раздел:", main_menu),
    "menu_heroes": ("📊 Герои — что смотрим?", heroes_menu),
    "menu_trends": ("📈 Тренды — что смотрим?", trends_menu),
    "menu_game": ("🎮 Игра — что смотрим?", game_menu),
    "menu_meta": ("🔥 Мета — выбери роль:", meta_menu),
}


# ========== ГЕНЕРАЦИЯ ТЕКСТА ==========

def build_top_heroes_text():
    heroes = get_player_heroes()
    names = get_hero_names()
    qualified = [h for h in heroes if h["games"] >= MIN_GAMES_FOR_TOP]
    qualified.sort(key=lambda h: h["win"] / h["games"], reverse=True)

    lines = [f"🏆 Топ по винрейту (мин. {MIN_GAMES_FOR_TOP} игр):\n"]
    if not qualified:
        lines.append(f"Пока нет героев с {MIN_GAMES_FOR_TOP}+ играми.")
    for h in qualified[:5]:
        wr = h["win"] / h["games"] * 100
        name = names.get(h["hero_id"], f"ID {h['hero_id']}")
        lines.append(f"{name} — {wr:.0f}% ({h['win']}/{h['games']})")
    return "\n".join(lines)


def build_most_played_text():
    heroes = get_player_heroes()
    names = get_hero_names()
    by_games = sorted(heroes, key=lambda h: h["games"], reverse=True)[:5]

    lines = ["🎮 Топ по кол-ву игр:\n"]
    for h in by_games:
        wr = h["win"] / h["games"] * 100 if h["games"] else 0
        name = names.get(h["hero_id"], f"ID {h['hero_id']}")
        lines.append(f"{name} — {h['games']} игр, винрейт {wr:.0f}%")
    return "\n".join(lines)


def build_hidden_gems_text():
    heroes = get_player_heroes()
    names = get_hero_names()
    gems = [
        h for h in heroes
        if 1 <= h["games"] <= HIDDEN_GEM_MAX_GAMES and h["win"] / h["games"] >= 0.6
    ]
    gems.sort(key=lambda h: h["win"] / h["games"], reverse=True)

    if not gems:
        return "💎 Пока не нашёл героев с малым кол-вом игр и хорошим винрейтом."

    lines = ["💎 Качай чаще (1-9 игр, винрейт от 60%):\n"]
    for h in gems[:7]:
        wr = h["win"] / h["games"] * 100
        name = names.get(h["hero_id"], f"ID {h['hero_id']}")
        lines.append(f"{name} — {wr:.0f}% ({h['win']}/{h['games']})")
    return "\n".join(lines)


def build_worst_heroes_text():
    heroes = get_player_heroes()
    names = get_hero_names()
    qualified = [h for h in heroes if h["games"] >= MIN_GAMES_FOR_TOP]
    qualified.sort(key=lambda h: h["win"] / h["games"])

    if not qualified:
        return f"📉 Недостаточно данных (нужно от {MIN_GAMES_FOR_TOP} игр на герое)."

    lines = ["📉 Самый низкий винрейт:\n"]
    for h in qualified[:5]:
        wr = h["win"] / h["games"] * 100
        name = names.get(h["hero_id"], f"ID {h['hero_id']}")
        lines.append(f"{name} — {wr:.0f}% ({h['win']}/{h['games']})")
    return "\n".join(lines)


def build_trend_text():
    matches = get_recent_matches(limit=100)

    def winrate(ms):
        if not ms:
            return None
        wins = sum(1 for m in ms if match_won(m))
        return wins / len(ms) * 100

    wr_20 = winrate(matches[:20])
    wr_100 = winrate(matches)

    lines = ["📈 Тренд винрейта:\n"]
    if wr_20 is not None:
        lines.append(f"Последние 20 игр: {wr_20:.0f}%")
    if wr_100 is not None:
        lines.append(f"Последние {len(matches)} игр: {wr_100:.0f}%")

    if wr_20 is not None and wr_100 is not None:
        diff = wr_20 - wr_100
        if diff >= 5:
            lines.append("\n🔥 Ты в форме, винрейт растёт")
        elif diff <= -5:
            lines.append("\n⚠️ Просадка в последних играх, может стоит отдохнуть")
        else:
            lines.append("\n➖ Стабильно, без резких скачков")
    return "\n".join(lines)


def build_streak_text():
    matches = get_recent_matches(limit=20)
    if not matches:
        return "Нет данных по последним играм."

    streak_type = None
    streak_len = 0
    for m in matches:
        won = match_won(m)
        if streak_type is None:
            streak_type = won
            streak_len = 1
        elif won == streak_type:
            streak_len += 1
        else:
            break

    label = "побед" if streak_type else "поражений"
    emoji = "🔥" if streak_type else "⚠️"
    lines = [f"{emoji} Текущая серия: {streak_len} {label} подряд"]

    if not streak_type and streak_len >= STREAK_WARNING_THRESHOLD:
        lines.append("\nПохоже на даунстрик. Может стоит сделать паузу перед следующей игрой.")
    elif streak_type and streak_len >= STREAK_WARNING_THRESHOLD:
        lines.append("\nХорошая серия, лови момент 🎯")
    return "\n".join(lines)


def build_mood_text():
    matches = get_recent_matches(limit=100)
    if not matches:
        return "Нет данных по последним играм."

    buckets = defaultdict(lambda: {"win": 0, "total": 0})
    for m in matches:
        start = m.get("start_time")
        if not start:
            continue
        hour = datetime.fromtimestamp(start).hour
        if 6 <= hour < 12:
            bucket = "Утро (6-12)"
        elif 12 <= hour < 18:
            bucket = "День (12-18)"
        elif 18 <= hour < 23:
            bucket = "Вечер (18-23)"
        else:
            bucket = "Ночь (23-6)"
        buckets[bucket]["total"] += 1
        if match_won(m):
            buckets[bucket]["win"] += 1

    lines = ["🕐 Винрейт по времени суток (последние 100 игр):\n"]
    order = ["Утро (6-12)", "День (12-18)", "Вечер (18-23)", "Ночь (23-6)"]
    for b in order:
        data = buckets.get(b)
        if data and data["total"] >= 3:
            wr = data["win"] / data["total"] * 100
            lines.append(f"{b}: {wr:.0f}% ({data['win']}/{data['total']})")
        elif data:
            lines.append(f"{b}: маловато игр ({data['total']}) для вывода")
    return "\n".join(lines)


def build_last_match_text():
    matches = get_recent_matches(limit=1)
    names = get_hero_names()
    if not matches:
        return "Не нашёл последних игр."

    m = matches[0]
    won = match_won(m)
    hero = names.get(m["hero_id"], f"ID {m['hero_id']}")
    result = "Победа ✅" if won else "Поражение ❌"

    return "\n".join([
        f"Последняя игра — {hero}",
        f"Результат: {result}",
        f"KDA: {m['kills']}/{m['deaths']}/{m['assists']}",
        f"Длительность: {m['duration'] // 60} мин",
    ])


def build_vision_text():
    matches = get_recent_matches(limit=10)
    obs_total = sen_total = counted = 0
    for m in matches:
        try:
            detail = requests.get(f"{OPENDOTA_API}/matches/{m['match_id']}", timeout=15).json()
            player = next(
                (p for p in detail.get("players", []) if p.get("account_id") == int(STEAM_ID32)),
                None,
            )
            if player:
                obs_total += player.get("obs_placed", 0) or 0
                sen_total += player.get("sen_placed", 0) or 0
                counted += 1
        except Exception:
            continue

    if counted == 0:
        return "Не удалось получить данные по вардам."

    lines = [
        f"👁 Варды за последние {counted} игр:\n",
        f"Наблюдатели (obs): {obs_total / counted:.1f} за игру",
        f"Сентри (sen): {sen_total / counted:.1f} за игру",
    ]
    if obs_total / counted < 2:
        lines.append("\n⚠️ Маловато вардов — ставь чаще, особенно на 4/5 позиции")
    return "\n".join(lines)


def build_benchmarks_text():
    totals = get_player_totals()
    metrics = {m["field"]: m for m in totals}

    def avg(field):
        m = metrics.get(field)
        if not m or not m.get("n"):
            return None
        return m["sum"] / m["n"]

    gpm, xpm = avg("gold_per_min"), avg("xp_per_min")
    kills, deaths, assists = avg("kills"), avg("deaths"), avg("assists")
    lh = avg("last_hits")

    lines = ["📊 Твои средние показатели за все игры:\n"]
    if gpm is not None:
        lines.append(f"GPM: {gpm:.0f}")
    if xpm is not None:
        lines.append(f"XPM: {xpm:.0f}")
    if kills is not None and deaths is not None and assists is not None:
        kda = (kills + assists) / max(deaths, 1)
        lines.append(f"KDA: {kills:.1f}/{deaths:.1f}/{assists:.1f} (отношение {kda:.2f})")
    if lh is not None:
        lines.append(f"Ласт-хиты за игру: {lh:.0f}")
    return "\n".join(lines)


ROLE_TAGS = {
    "meta_core": (["Carry"], "⚔️ Кор (Carry)"),
    "meta_mid": (["Nuker", "Escape"], "🌲 Мидлейн"),
    "meta_offlane": (["Durable", "Initiator"], "🛡 Оффлейн"),
    "meta_support": (["Support"], "💚 Саппорт"),
}


def build_meta_text(role_key):
    stats = get_hero_stats()
    tags, label = ROLE_TAGS[role_key]

    candidates = []
    for h in stats:
        roles = h.get("roles", [])
        if not any(t in roles for t in tags):
            continue
        pro_pick = h.get("pro_pick") or 0
        pro_win = h.get("pro_win") or 0
        if pro_pick < 10:
            continue
        wr = pro_win / pro_pick * 100
        candidates.append((h["localized_name"], wr, pro_pick))

    candidates.sort(key=lambda x: x[1], reverse=True)

    lines = [f"{label} — топ по винрейту в про-сцене:\n"]
    if not candidates:
        lines.append("Недостаточно данных.")
    for name, wr, picks in candidates[:7]:
        lines.append(f"{name} — {wr:.0f}% ({picks} игр)")

    lines.append(
        "\nℹ️ Разделение по ролям приблизительное (OpenDota не даёт "
        "точных позиций 1-5), но общий вектор меты рабочий."
    )
    return "\n".join(lines)


ACTIONS = {
    "top_heroes": (lambda: build_top_heroes_text(), "menu_heroes"),
    "most_played": (lambda: build_most_played_text(), "menu_heroes"),
    "hidden_gems": (lambda: build_hidden_gems_text(), "menu_heroes"),
    "worst_heroes": (lambda: build_worst_heroes_text(), "menu_heroes"),
    "trend": (lambda: build_trend_text(), "menu_trends"),
    "streak": (lambda: build_streak_text(), "menu_trends"),
    "mood": (lambda: build_mood_text(), "menu_trends"),
    "last_match": (lambda: build_last_match_text(), "menu_game"),
    "vision": (lambda: build_vision_text(), "menu_game"),
    "benchmarks": (lambda: build_benchmarks_text(), "menu_game"),
}


# ========== ХЭНДЛЕРЫ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет! Steam ID: {STEAM_ID32}\nВыбери раздел:",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ROLE_TAGS:
        try:
            text = build_meta_text(data)
        except Exception as e:
            logger.exception("Ошибка в build_meta_text")
            text = f"Ошибка запроса к OpenDota: {e}"
        await query.edit_message_text(text, reply_markup=back_button("menu_meta"))
        return

    if data in MENUS:
        text, menu_fn = MENUS[data]
        await query.edit_message_text(text, reply_markup=menu_fn())
        return

    if data in ACTIONS:
        build_fn, back_target = ACTIONS[data]
        try:
            text = build_fn()
        except Exception as e:
            logger.exception("Ошибка в build_fn для %s", data)
            text = f"Ошибка запроса к OpenDota: {e}"
        await query.edit_message_text(text, reply_markup=back_button(back_target))
        return


def main():
    if "ВСТАВЬ_СЮДА" in BOT_TOKEN:
        print("⚠️  Впиши BOT_TOKEN в bot.py!")
        return

    # Фикс для Python 3.14: asyncio.get_event_loop() больше не создаёт
    # петлю автоматически, поэтому создаём её сами перед стартом бота.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print(f"Бот запущен со Steam ID {STEAM_ID32}, жду сообщений...")
    app.run_polling()


if __name__ == "__main__":
    main()
