"""
╔══════════════════════════════════════════════════════════════╗
║                  🟣 MINEAURORA BOT v1.0                      ║
║           Всё-в-одном: тикеты, роли, уровни, приветствия,    ║
║           верификация и антиспам для Discord-сервера         ║
╚══════════════════════════════════════════════════════════════╝

Запуск:
    python mineaurora_bot.py

Команды (только для админов):
    /panel          — отправить панель тикетов в текущий канал
    /roles_panel    — отправить панель реакция-ролей
    /verify_panel   — отправить панель верификации
    /welcome_test   — показать пример приветствия
    /xp @user       — показать опыт участника
    /give_xp @user N — выдать опыт (админ)
    /level_rewards  — список наград за уровни
"""
import os
import sys
import asyncio
import sqlite3
import random
import time
import traceback
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

import discord

# Подробное логирование, чтобы на хостинге было видно реальную ошибку
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("mineaurora")
from discord import ui
from discord.utils import get
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv не установлен — это не страшно, токен возьмём ниже
    pass

# ── ТОКЕН БОТА ────────────────────────────────────────────────
# Вариант 1 (рекомендуется): впиши токен прямо сюда, в кавычки.
#    (тогда .env и python-dotenv вообще не нужны)
TOKEN_HERE = ""

# Вариант 2: токен берётся из переменной окружения DISCORD_TOKEN
#    (или из файла .env, если установлен python-dotenv)
TOKEN = TOKEN_HERE or os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ Токен не задан. Впиши его в TOKEN_HERE в начале файла "
          "или в переменную DISCORD_TOKEN.")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# ⚙️  НАСТРОЙКИ — МОЖНО МЕНЯТЬ ПОД СЕБЯ
# ═══════════════════════════════════════════════════════════════

# --- Каналы (имена, как создал setup_server.py) ---
CH_RULES        = "правила"
CH_WELCOME      = "общий"          # куда присылать приветствия
CH_TICKET_PANEL = "тикет-панель"
CH_ROLES_PANEL  = "роли"
CH_VERIFY       = "верификация"
CH_LOG          = "лог-тикетов"
CH_LEVEL_UP     = "общий"          # куда писать "достиг уровня"
CH_COMMANDS     = "команды"        # сюда не начисляется XP

# --- Категории ---
CAT_SUPPORT = "🛠️ ПОДДЕРЖКА"
CAT_ARCHIVE = "📦 Архив тикетов"

# --- Роли ---
ROLE_VERIFIED   = "✅ Verified"
ROLE_NEWBIE     = "👋 Новичок"
ROLE_STAFF      = ["👑 Владелец", "🛡️ Администратор", "🔨 Стафф", "❓ Хелпер"]

# Цвета для авто-создания ролей
ROLE_COLORS = {
    ROLE_VERIFIED: 0x4CAF50,
    ROLE_NEWBIE:   0x90A4AE,
}

# Роли уведомлений (выдаются кнопками в #роли)
NOTIFY_ROLES = {
    "📰": ("Новости",    "Новости сервера"),
    "🆕": ("Обновления", "Обновления и патчи"),
    "🎉": ("Ивенты",     "Игровые ивенты и конкурсы"),
    "🔴": ("Стримы",     "Стримы и YouTube-ролики"),
}

# --- Награды за уровни (уровень: имя роли) ---
# Роли нужно создать вручную или они создадутся автоматически при первом достижении.
LEVEL_ROLES = {
    5:  "🌱 Новичок",
    10: "⚡ Актив",
    20: "🔥 Завсегдатай",
    30: "💎 Ветеран",
    50: "👑 Легенда",
}

# --- Экономика уровней ---
XP_PER_MESSAGE_MIN = 15
XP_PER_MESSAGE_MAX = 25
XP_COOLDOWN_SEC    = 60      # анти-фарм: не чаще одного сообщения раз в минуту

# --- Антиспам ---
SPAM_THRESHOLD = 6          # сообщений за окно
SPAM_WINDOW    = 7          # секунд
SPAM_MUTE_MIN  = 10         # мут в минутах

# ═══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mineaurora.db")


# ──────────────────────────────────────────────────────────────
#  УТИЛИТЫ
# ──────────────────────────────────────────────────────────────
def utcnow():
    return datetime.now(timezone.utc)


def is_staff(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True
    if member.guild_permissions.administrator:
        return True
    if member.guild_permissions.manage_channels:
        return True
    return any(r.name in ROLE_STAFF for r in member.roles)


def staff_mentions(guild: discord.Guild) -> str:
    return " ".join(r.mention for n in ROLE_STAFF[1:]
                    if (r := get(guild.roles, name=n)))


async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    """Возвращает роль; если её нет — создаёт с нужным цветом."""
    role = get(guild.roles, name=name)
    if role is None:
        color = ROLE_COLORS.get(name, 0x95A5A6)
        try:
            role = await guild.create_role(
                name=name,
                color=discord.Color(color),
                reason="Автосоздание роли MineAurora")
            log.info("Создана недостающая роль: %s", name)
        except discord.Forbidden:
            log.error("Нет прав создать роль %s — подними роль бота выше", name)
            return None
    return role


# ──────────────────────────────────────────────────────────────
#  БАЗА ДАННЫХ УРОВНЕЙ
# ──────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS levels (
                guild_id INTEGER,
                user_id  INTEGER,
                xp       INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        c.commit()


def xp_for_level(level: int) -> int:
    return 5 * level * level + 50 * level + 100


def level_from_xp(xp: int) -> int:
    lvl = 0
    while xp >= xp_for_level(lvl):
        xp -= xp_for_level(lvl)
        lvl += 1
    return lvl


def get_xp(guild_id: int, user_id: int) -> int:
    with db() as c:
        row = c.execute("SELECT xp FROM levels WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id)).fetchone()
        return row["xp"] if row else 0


def add_xp(guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
    """Возвращает (новый_уровень, старый_уровень)."""
    old = get_xp(guild_id, user_id)
    new = old + amount
    with db() as c:
        c.execute("""
            INSERT INTO levels(guild_id, user_id, xp) VALUES(?,?,?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp
        """, (guild_id, user_id, new))
        c.commit()
    return level_from_xp(new), level_from_xp(old)


# ──────────────────────────────────────────────────────────────
#  ВЕРИФИКАЦИЯ
# ──────────────────────────────────────────────────────────────
VERIFY_TEXT = (
    "**👋 Добро пожаловать на MINEAURORA!**\n\n"
    "Нажми кнопку ниже, чтобы подтвердить, что ты не бот. "
    "После верификации ты получишь роль **Verified** и доступ ко всем чатам.\n\n"
    "Не забудь заглянуть в <#правила> и выбрать роли-уведомления в <#роли>."
)


class VerifyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Подтвердить, что я человек",
               emoji="✅",
               style=discord.ButtonStyle.success,
               custom_id="mineaurora_verify_btn")
    async def verify(self, interaction: discord.Interaction, button):
        guild = interaction.guild
        verified = await ensure_role(guild, ROLE_VERIFIED)
        newbie = get(guild.roles, name=ROLE_NEWBIE)

        if verified is None:
            await interaction.response.send_message(
                "⚠️ Не удалось найти/создать роль Verified. Подними роль бота "
                "MineAurora выше остальных в Настройки сервера → Роли.",
                ephemeral=True)
            return

        if verified in interaction.user.roles:
            await interaction.response.send_message(
                "Ты уже верифицирован ✅", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(verified, reason="Верификация")
            if newbie and newbie in interaction.user.roles:
                await interaction.user.remove_roles(newbie)
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ У бота нет прав. Подними роль MineAurora выше Verified в "
                "Настройки сервера → Роли.",
                ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Готово, {interaction.user.mention}! Теперь тебе доступны все чаты.",
            ephemeral=True)


# ──────────────────────────────────────────────────────────────
#  РЕАКЦИЯ-РОЛИ (кнопки)
# ──────────────────────────────────────────────────────────────
ROLES_TEXT = (
    "**🎭 РОЛИ-УВЕДОМЛЕНИЯ**\n\n"
    "Нажимай на кнопки, чтобы включать/выключать роли:\n\n"
    "📰 **Новости** — главные новости сервера\n"
    "🆕 **Обновления** — патчи и апдейты Minecraft-сервера\n"
    "🎉 **Ивенты** — конкурсы и игровые события\n"
    "🔴 **Стримы** — анонсы стримов и YouTube-роликов\n\n"
    "_Кнопка работает как переключатель: нажал ещё раз — роль снялась._"
)


class ReactionRolesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for i, (emoji, (name, _)) in enumerate(NOTIFY_ROLES.items()):
            btn = ui.Button(
                label=name, emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"mineaurora_rr_{i}")
            btn.callback = self._make_callback(name)
            self.add_item(btn)

    def _make_callback(self, role_name: str):
        async def callback(interaction: discord.Interaction):
            role = get(interaction.guild.roles, name=role_name)
            if role is None:
                await interaction.response.send_message(
                    f"⚠️ Роль {role_name} не найдена.", ephemeral=True)
                return
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(
                    f"❌ Роль **{role_name}** снята.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(
                    f"✅ Роль **{role_name}** выдана.", ephemeral=True)
        return callback


# ──────────────────────────────────────────────────────────────
#  ТИКЕТЫ
# ──────────────────────────────────────────────────────────────
SIMPLE_PROMPTS = {
    "support": (
        "Опиши свой вопрос:\n"
        "• **С чем нужна помощь:**\n"
        "• **Что уже пробовал(а) сделать:**\n"
        "• **Скриншот** (если уместен):\n\n"
        "Мы постараемся помочь как можно скорее. {staff}"
    ),
    "report": (
        "Опиши жалобу:\n"
        "• **Ник нарушителя:**\n"
        "• **Что произошло:**\n"
        "• **Доказательства** (скрин/видео — прикрепи сюда же):\n\n"
        "Стафф скоро подключится. {staff}"
    ),
    "bug": (
        "Опиши баг:\n"
        "• **Что случилось:**\n"
        "• **Как воспроизвести** (по шагам):\n"
        "• **Ожидал(а) что произойдёт:**\n"
        "• **Скриншот/видео:**\n\n"
        "Спасибо за помощь проекту! {staff}"
    ),
    "donate": (
        "Опиши вопрос по донату:\n"
        "• **Что хочешь купить / какая привилегия:**\n"
        "• **Проблема с оплатой?** Опиши:\n"
        "• **Ник в Minecraft:**\n\n"
        "Администрация скоро ответит. {staff}"
    ),
}

TYPE_META = {
    "support": {"label": "Тех. поддержка",     "emoji": "🎧", "color": discord.ButtonStyle.primary,   "prefix": "саппорт"},
    "report":  {"label": "Пожаловаться",       "emoji": "🚨", "color": discord.ButtonStyle.danger,    "prefix": "жалоба"},
    "bug":     {"label": "Сообщить о баге",    "emoji": "🐛", "color": discord.ButtonStyle.secondary, "prefix": "баг"},
    "helper":  {"label": "Заявка на Хелпера",  "emoji": "❓", "color": discord.ButtonStyle.success,   "prefix": "хелпер"},
    "youtube": {"label": "Заявка на YouTube",  "emoji": "📺", "color": discord.ButtonStyle.danger,    "prefix": "youtube"},
    "tiktok":  {"label": "Заявка на TikTok",   "emoji": "🎵", "color": discord.ButtonStyle.secondary, "prefix": "tiktok"},
    "donate":  {"label": "Вопрос по донату",   "emoji": "🛒", "color": discord.ButtonStyle.success,   "prefix": "донат"},
}

PANEL_TEXT = (
    "**🎫 ПОДДЕРЖКА MINEAURORA**\n\n"
    "Выбери тип обращения. Для заявок на Хелпера/YouTube/TikTok "
    "от откроется короткая анкета.\n\n"
    "🎧 **Тех. поддержка** — общие вопросы\n"
    "🚨 **Пожаловаться** — жалоба на игрока\n"
    "🐛 **Сообщить о баге**\n"
    "❓ **Заявка на Хелпера** — анкета\n"
    "📺 **Заявка на YouTube** — анкета\n"
    "🎵 **Заявка на TikTok** — анкета\n"
    "🛒 **Вопрос по донату**"
)


def ticket_overwrites(guild, author):
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            read_message_history=True),
    }
    for name in ROLE_STAFF:
        r = get(guild.roles, name=name)
        if r:
            ow[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                read_message_history=True)
    return ow


async def create_ticket_channel(interaction, type_key, body, title, color):
    guild = interaction.guild
    meta = TYPE_META[type_key]
    category = get(guild.categories, name=CAT_SUPPORT)
    if category is None:
        category = await guild.create_category(CAT_SUPPORT)

    for ch in guild.text_channels:
        if ch.topic and ch.topic.startswith(f"ticket:{interaction.user.id}:{type_key}:"):
            await interaction.response.send_message(
                f"У тебя уже есть открытый тикет: {ch.mention}", ephemeral=True)
            return None

    n = sum(1 for c in guild.text_channels
            if c.name.startswith(f"тикет-{meta['prefix']}-")) + 1
    channel = await category.create_text_channel(
        name=f"тикет-{meta['prefix']}-{n:03d}",
        topic=f"ticket:{interaction.user.id}:{type_key}:{utcnow().isoformat()}",
        overwrites=ticket_overwrites(guild, interaction.user))

    embed = discord.Embed(
        title=title, description=body.replace("{staff}", staff_mentions(guild)),
        color=color, timestamp=utcnow())
    embed.set_footer(text=f"Автор: {interaction.user}")
    await channel.send(
        content=f"{interaction.user.mention} {staff_mentions(guild)}",
        embed=embed, view=TicketActionsView())

    log = get(guild.text_channels, name=CH_LOG)
    if log:
        await log.send(
            f"📂 `{utcnow().strftime('%H:%M:%S')}` {interaction.user} "
            f"(`{interaction.user.id}`) открыл(а) **{meta['label']}**: {channel.mention}")
    return channel


# ── Анкеты ──
class HelperModal(ui.Modal, title="Заявка на Хелпера"):
    name = ui.TextInput(label="Имя/ник", required=True, max_length=50)
    age = ui.TextInput(label="Возраст", required=True, max_length=3)
    online = ui.TextInput(label="Онлайн в день (часов)", required=True, max_length=20)
    why = ui.TextInput(label="Почему именно ты?",
                       style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction):
        msg = (
            f"**📝 Анкета на Хелпера**\n\n"
            f"• **Имя:** {self.name.value}\n"
            f"• **Возраст:** {self.age.value}\n"
            f"• **Онлайн:** {self.online.value}\n"
            f"• **Почему я:** {self.why.value}\n\n"
            "Стафф рассмотрит заявку в течение 1-3 дней. {staff}"
        )
        ch = await create_ticket_channel(
            interaction, "helper", msg,
            "❓ Заявка на Хелпера", discord.Color.green())
        if ch is not None:
            await interaction.response.send_message(
                f"✅ Заявка отправлена! Тикет: {ch.mention}", ephemeral=True)


class YouTubeModal(ui.Modal, title="Заявка на YouTube"):
    channel = ui.TextInput(label="Ссылка на канал", required=True, max_length=200)
    subs = ui.TextInput(label="Подписчики", required=True, max_length=20)
    freq = ui.TextInput(label="Частота выхода видео", required=True, max_length=100)
    topic = ui.TextInput(label="Тематика контента",
                         style=discord.TextStyle.paragraph, required=True, max_length=300)

    async def on_submit(self, interaction):
        msg = (
            f"**📺 Анкета YouTube**\n\n"
            f"• **Канал:** {self.channel.value}\n"
            f"• **Подписчики:** {self.subs.value}\n"
            f"• **Частота:** {self.freq.value}\n"
            f"• **Тематика:** {self.topic.value}\n\n"
            "Рассмотрим заявку. {staff}"
        )
        ch = await create_ticket_channel(
            interaction, "youtube", msg,
            "📺 Заявка на YouTube", discord.Color.red())
        if ch is not None:
            await interaction.response.send_message(
                f"✅ Заявка отправлена! Тикет: {ch.mention}", ephemeral=True)


class TikTokModal(ui.Modal, title="Заявка на TikTok"):
    account = ui.TextInput(label="Ссылка на аккаунт", required=True, max_length=200)
    freq = ui.TextInput(label="Частота выхода видео", required=True, max_length=100)
    topic = ui.TextInput(label="Что снимаешь?",
                         style=discord.TextStyle.paragraph, required=True, max_length=300)

    async def on_submit(self, interaction):
        msg = (
            f"**🎵 Анкета TikTok**\n\n"
            f"• **Аккаунт:** {self.account.value}\n"
            f"• **Частота:** {self.freq.value}\n"
            f"• **Контент:** {self.topic.value}\n\n"
            "Рассмотрим заявку. {staff}"
        )
        ch = await create_ticket_channel(
            interaction, "tiktok", msg,
            "🎵 Заявка на TikTok", discord.Color.blurple())
        if ch is not None:
            await interaction.response.send_message(
                f"✅ Заявка отправлена! Тикет: {ch.mention}", ephemeral=True)


# ── Виджеты ──
class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _simple(self, interaction, key, title, color):
        ch = await create_ticket_channel(
            interaction, key, SIMPLE_PROMPTS[key], title, color)
        if ch is not None:
            await interaction.response.send_message(
                f"✅ {TYPE_META[key]['label']}: {ch.mention}", ephemeral=True)

    @ui.button(label="Тех. поддержка", emoji="🎧", style=discord.ButtonStyle.primary,
               custom_id="m_t_support", row=0)
    async def b_support(self, i, b):
        await self._simple(i, "support", "🎧 Тех. поддержка", discord.Color.blue())

    @ui.button(label="Пожаловаться", emoji="🚨", style=discord.ButtonStyle.danger,
               custom_id="m_t_report", row=0)
    async def b_report(self, i, b):
        await self._simple(i, "report", "🚨 Жалоба на игрока", discord.Color.red())

    @ui.button(label="Сообщить о баге", emoji="🐛", style=discord.ButtonStyle.secondary,
               custom_id="m_t_bug", row=0)
    async def b_bug(self, i, b):
        await self._simple(i, "bug", "🐛 Баг-репорт", discord.Color.orange())

    @ui.button(label="Заявка на Хелпера", emoji="❓", style=discord.ButtonStyle.success,
               custom_id="m_t_helper", row=1)
    async def b_helper(self, i, b):
        await i.response.send_modal(HelperModal())

    @ui.button(label="Заявка на YouTube", emoji="📺", style=discord.ButtonStyle.danger,
               custom_id="m_t_youtube", row=1)
    async def b_youtube(self, i, b):
        await i.response.send_modal(YouTubeModal())

    @ui.button(label="Заявка на TikTok", emoji="🎵", style=discord.ButtonStyle.secondary,
               custom_id="m_t_tiktok", row=1)
    async def b_tiktok(self, i, b):
        await i.response.send_modal(TikTokModal())

    @ui.button(label="Вопрос по донату", emoji="🛒", style=discord.ButtonStyle.success,
               custom_id="m_t_donate", row=2)
    async def b_donate(self, i, b):
        await self._simple(i, "donate", "🛒 Вопрос по донату", discord.Color.green())


class TicketActionsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Закрыть тикет", emoji="🔒",
               style=discord.ButtonStyle.danger, custom_id="m_close_ticket")
    async def close(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "Закрыть тикет может только стафф.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{interaction.user.mention} закрывает тикет через 5 секунд...")
        await asyncio.sleep(5)
        try:
            archive = get(interaction.guild.categories, name=CAT_ARCHIVE)
            if archive is None:
                archive = await interaction.guild.create_category(CAT_ARCHIVE)
            ow = dict(interaction.channel.overwrites)
            for tgt in list(ow.keys()):
                if isinstance(tgt, discord.Member):
                    ow[tgt] = discord.PermissionOverwrite(view_channel=False)
            await interaction.channel.edit(
                category=archive, name=f"закрыт-{interaction.channel.name}", overwrites=ow)
            log = get(interaction.guild.text_channels, name=CH_LOG)
            if log:
                await log.send(
                    f"📁 `{utcnow().strftime('%H:%M:%S')}` {interaction.user} "
                    f"закрыл(а) #{interaction.channel.name}")
            await interaction.channel.send("🔒 Тикет закрыт и перенесён в архив.")
        except Exception as e:
            print("Ошибка архивации:", e)

    @ui.button(label="Сохранить переписку", emoji="📝",
               style=discord.ButtonStyle.secondary, custom_id="m_transcript")
    async def transcript(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "Только стаффу.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        lines = []
        async for m in interaction.channel.history(limit=500, oldest_first=True):
            lines.append(f"[{m.created_at:%Y-%m-%d %H:%M:%S}] {m.author}: {m.content or '(вложение)'}")
        fn = f"transcript-{interaction.channel.name}.txt"
        with open(fn, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        await interaction.followup.send(
            "📝 Переписка:", file=discord.File(fn), ephemeral=True)
        os.remove(fn)


# ──────────────────────────────────────────────────────────────
#  СОБЫТИЯ: приветствие, уровни, антиспам
# ──────────────────────────────────────────────────────────────
@client.event
async def on_member_join(member: discord.Member):
    newbie = await ensure_role(member.guild, ROLE_NEWBIE)
    if newbie:
        try:
            await member.add_roles(newbie, reason="Новый участник")
        except discord.Forbidden:
            pass

    ch = get(member.guild.text_channels, name=CH_WELCOME)
    if ch:
        rules_ch = get(member.guild.text_channels, name=CH_RULES)
        ver_ch = get(member.guild.text_channels, name=CH_VERIFY)
        rol_ch = get(member.guild.text_channels, name=CH_ROLES_PANEL)
        lines = [f"Привет, {member.mention}! Добро пожаловать на **MINEAURORA** ✨", ""]
        if rules_ch:
            lines.append(f"📜 Прочитай {rules_ch.mention}")
        if ver_ch:
            lines.append(f"✅ Подтверди, что ты не бот: {ver_ch.mention}")
        if rol_ch:
            lines.append(f"🎭 Выбери роли-уведомления: {rol_ch.mention}")
        lines += ["", f"Ты у нас **#{member.guild.member_count}**!"]
        embed = discord.Embed(
            title="🎉 Новый участник!",
            description="\n".join(lines),
            color=discord.Color.blurple(),
            timestamp=utcnow())
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        await ch.send(content=member.mention, embed=embed)


# ── Антиспам: память последних сообщений ──
recent_msgs = defaultdict(lambda: deque(maxlen=SPAM_THRESHOLD + 2))
last_xp_gain = {}


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ── Антиспам ──
    if not is_staff(message.author):
        now = time.monotonic()
        dq = recent_msgs[(message.guild.id, message.author.id)]
        dq.append(now)
        # чистим старые
        while dq and now - dq[0] > SPAM_WINDOW:
            dq.popleft()
        if len(dq) >= SPAM_THRESHOLD:
            try:
                await message.author.timeout(
                    timedelta(minutes=SPAM_MUTE_MIN),
                    reason=f"Антиспам: {len(dq)} сообщ. за {SPAM_WINDOW}с")
                await message.channel.send(
                    f"🤖 {message.author.mention}, ты замьючен на {SPAM_MUTE_MIN} мин. за спам.",
                    delete_after=15)
                # удалить последние сообщения
                async for m in message.channel.history(limit=15):
                    if m.author == message.author:
                        try:
                            await m.delete()
                        except Exception:
                            pass
            except discord.Forbidden:
                pass
            recent_msgs[(message.guild.id, message.author.id)].clear()

    # ── Уровни ──
    if message.channel.name != CH_COMMANDS and not message.channel.name.startswith("тикет-"):
        if (message.content
                and len(message.content) > 3
                and not message.content.startswith(("/", "!", "?", "."))):

            key = (message.guild.id, message.author.id)
            now_ts = time.time()
            if now_ts - last_xp_gain.get(key, 0) >= XP_COOLDOWN_SEC:
                gain = random.randint(XP_PER_MESSAGE_MIN, XP_PER_MESSAGE_MAX)
                new_lvl, old_lvl = add_xp(message.guild.id, message.author.id, gain)
                last_xp_gain[key] = now_ts

                if new_lvl > old_lvl:
                    # выдать роль-награду, если есть
                    if new_lvl in LEVEL_ROLES:
                        role_name = LEVEL_ROLES[new_lvl]
                        role = get(message.guild.roles, name=role_name)
                        if role is None:
                            try:
                                role = await message.guild.create_role(
                                    name=role_name,
                                    color=discord.Color(0xFFD700),
                                    hoist=True,
                                    reason="Авто-награда за уровень")
                            except Exception:
                                role = None
                        if role and role not in message.author.roles:
                            try:
                                await message.author.add_roles(role)
                            except discord.Forbidden:
                                pass

                    lvl_ch = get(message.guild.text_channels, name=CH_LEVEL_UP)
                    if lvl_ch:
                        embed = discord.Embed(
                            title="🎉 Новый уровень!",
                            description=(
                                f"{message.author.mention} достиг **{new_lvl} уровня**!"
                                + (f"\nВыдана роль **{LEVEL_ROLES[new_lvl]}** 🏆"
                                   if new_lvl in LEVEL_ROLES else "")
                            ),
                            color=discord.Color.gold())
                        await lvl_ch.send(embed=embed)


# ──────────────────────────────────────────────────────────────
#  СЛЭШ-КОМАНДЫ
# ──────────────────────────────────────────────────────────────
@tree.command(name="panel", description="(админ) Отправить панель тикетов")
@discord.app_commands.checks.has_permissions(administrator=True)
async def cmd_panel(interaction: discord.Interaction):
    await interaction.channel.send(PANEL_TEXT, view=PanelView())
    await interaction.response.send_message("✅ Панель тикетов отправлена.", ephemeral=True)


@tree.command(name="roles_panel", description="(админ) Отправить панель ролей-уведомлений")
@discord.app_commands.checks.has_permissions(administrator=True)
async def cmd_roles(interaction: discord.Interaction):
    await interaction.channel.send(ROLES_TEXT, view=ReactionRolesView())
    await interaction.response.send_message("✅ Панель ролей отправлена.", ephemeral=True)


@tree.command(name="verify_panel", description="(админ) Отправить панель верификации")
@discord.app_commands.checks.has_permissions(administrator=True)
async def cmd_verify(interaction: discord.Interaction):
    await interaction.channel.send(VERIFY_TEXT, view=VerifyView())
    await interaction.response.send_message("✅ Панель верификации отправлена.", ephemeral=True)


@tree.command(name="xp", description="Показать опыт и уровень участника")
async def cmd_xp(interaction: discord.Interaction,
                 user: discord.User = None):
    target = user or interaction.user
    xp = get_xp(interaction.guild.id, target.id)
    lvl = level_from_xp(xp)
    need = xp_for_level(lvl)
    in_lvl = need  # упрощённо
    embed = discord.Embed(
        title=f"📊 Уровень {target}",
        color=discord.Color.blurple())
    embed.add_field(name="Уровень", value=str(lvl))
    embed.add_field(name="Всего XP", value=str(xp))
    if target.avatar:
        embed.set_thumbnail(url=target.avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=False)


@tree.command(name="level_rewards", description="Список наград за уровни")
async def cmd_rewards(interaction: discord.Interaction):
    rows = "\n".join(f"• **Уровень {lvl}** → {role}" for lvl, role in sorted(LEVEL_ROLES.items()))
    await interaction.response.send_message(
        embed=discord.Embed(title="🏆 Награды за уровни",
                           description=rows, color=discord.Color.gold()),
        ephemeral=False)


@tree.command(name="welcome_test", description="(админ) Тест приветствия")
@discord.app_commands.checks.has_permissions(administrator=True)
async def cmd_welcome_test(interaction: discord.Interaction):
    class FakeMember:
        mention = interaction.user.mention
        guild = interaction.guild
        avatar = interaction.user.avatar
        id = interaction.user.id
    fake = FakeMember()
    # вручную повторим on_member_join для теста (без выдачи роли)
    ch = get(interaction.guild.text_channels, name=CH_WELCOME)
    if ch:
        rules = get(interaction.guild.text_channels, name=CH_RULES)
        ver = get(interaction.guild.text_channels, name=CH_VERIFY)
        rol = get(interaction.guild.text_channels, name=CH_ROLES_PANEL)
        embed = discord.Embed(
            title="🎉 Новый участник! (тест)",
            description=(
                f"Привет, {interaction.user.mention}! Добро пожаловать на **MINEAURORA** ✨\n\n"
                f"📜 Правила: {rules.mention if rules else '-'}\n"
                f"✅ Верификация: {ver.mention if ver else '-'}\n"
                f"🎭 Роли: {rol.mention if rol else '-'}"
            ),
            color=discord.Color.blurple())
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)
        await ch.send(embed=embed)
    await interaction.response.send_message("Отправил тестовое приветствие.", ephemeral=True)


# ──────────────────────────────────────────────────────────────
#  СТАРТ
# ──────────────────────────────────────────────────────────────
async def ensure_panel(channel_name: str, content: str, view: ui.View, label: str):
    try:
        ch = get(client.get_all_channels(), name=channel_name)
        if ch is None:
            log.warning("Канал #%s не найден — пропускаю %s", channel_name, label)
            return
        async for m in ch.history(limit=30):
            if m.author == client.user and m.components:
                log.info("%s уже существует в #%s", label, channel_name)
                return
        await ch.send(content, view=view)
        log.info("%s отправлена в #%s", label, channel_name)
    except Exception as e:
        log.error("Не удалось отправить %s: %s\n%s", label, e, traceback.format_exc())


@client.event
async def on_ready():
    try:
        init_db()
        print(f"\n{'='*60}\n  🟣 MineAurora Bot запущен как {client.user}\n  Серверов: {len(client.guilds)}\n{'='*60}", flush=True)
        log.info("Синхронизация слэш-команд...")
        try:
            await tree.sync()
            log.info("Слэш-команды синхронизированы.")
        except Exception as e:
            log.error("Ошибка синхронизации команд: %s", e)

        # Регистрируем persistent views (чтобы кнопки работали после перезапуска)
        for v in [PanelView(), TicketActionsView(), VerifyView(), ReactionRolesView()]:
            client.add_view(v)

        # Авто-отправка панелей, если их ещё нет
        if len(client.guilds) == 1:
            await ensure_panel(CH_TICKET_PANEL, PANEL_TEXT, PanelView(), "Панель тикетов")
            await ensure_panel(CH_ROLES_PANEL, ROLES_TEXT, ReactionRolesView(), "Панель ролей")
            await ensure_panel(CH_VERIFY, VERIFY_TEXT, VerifyView(), "Панель верификации")

        log.info("✅ Бот полностью готов и работает.")
        print("✅ Бот готов. Нажми Ctrl+C для остановки.\n", flush=True)
    except Exception:
        log.error("Критическая ошибка в on_ready:\n%s", traceback.format_exc())
        # Не даём боту упасть молча — логи останутся, а процесс продолжит жить


@client.event
async def on_error(event, *args, **kwargs):
    log.error("Необработанная ошибка в событии %s:\n%s",
              event, traceback.format_exc())


# ═══════════════════════════════════════════════════════════════
#  STAFFWORK API — проверка роли стаффа и код в ЛС (для MC-плагина)
#  НАСТРОЙКИ НИЖЕ: ПОМЕНЯЙ ПОД СЕБЯ
# ═══════════════════════════════════════════════════════════════
try:
    from aiohttp import web
except ImportError:
    web = None
    log.warning("aiohttp не установлен — проверка Discord (StaffWork) отключена. "
                "Установи: pip install aiohttp")

SW_HOST = "0.0.0.0"
SW_PORT = 8080

# Секретный ключ. ДОЛЖЕН совпадать с discord.api-token в config.yml плагина!
SW_API_TOKEN = "0e301302fca337436f1528667c56b0c4"

# Роли, которые считаются стаффом. Проверка идёт по ВХОЖДЕНИЮ слова в название
# роли (регистр не важен), поэтому эмодзи/приставки не мешают:
#   "🔨 Модер" -> подходит, "стажёр" -> подходит (ё=е), и т.п.
SW_STAFF_ROLES = [
    "стажер",
    "млхелпер",
    "хелпер",
    "млмодер",
    "модер",
    "глмодер",
    "куратор",
    "владелец",
    "администратор",
    "админ",
]

SW_GUILD_ID = None  # int ID сервера, или None = первый сервер бота
SW_CODE_TTL = 600   # секунд на ввод кода

_sw_pending = {}


def _sw_norm(s):
    return str(s).strip().lower()


def _sw_guild():
    if SW_GUILD_ID is not None:
        return client.get_guild(int(SW_GUILD_ID))
    return next(iter(client.guilds), None)


def _sw_find_member(guild, username):
    target = _sw_norm(username)
    if not target:
        return None
    for m in guild.members:
        if _sw_norm(getattr(m, "name", "")) == target:
            return m
    for m in guild.members:
        if _sw_norm(getattr(m, "global_name", None) or "") == target:
            return m
    for m in guild.members:
        if _sw_norm(getattr(m, "name", "")).startswith(target):
            return m
    return None


def _sw_has_role(member):
    # нормализуем названия ролей: убираем ё->е, эмодзи и лишние символы
    import re as _re
    def clean(s):
        s = _sw_norm(s)
        s = s.replace("ё", "е")
        s = _re.sub(r"[^a-zа-я0-9]", "", s)  # оставляем только буквы и цифры
        return s

    allowed = [clean(r) for r in SW_STAFF_ROLES if clean(r)]
    for r in member.roles:
        rn = clean(r.name)
        for a in allowed:
            if a in rn or rn in a:
                return True
    return False


async def _sw_verify(data):
    guild = _sw_guild()
    if guild is None:
        return web.json_response({"status": "no_guild"})
    member = _sw_find_member(guild, data.get("username", ""))
    if member is None:
        return web.json_response({"status": "not_found"})
    if not _sw_has_role(member):
        return web.json_response({"status": "no_role"})

    code = f"{random.randint(0, 999999):06d}"
    _sw_pending[_sw_norm(data.get("player", ""))] = {
        "code": code, "username": member.name, "expires": time.time() + SW_CODE_TTL,
    }
    try:
        await member.send(
            "**Подтверждение привязки StaffWork**\n"
            f"Игрок: {data.get('player', '?')}\n"
            f"Код: **{code}**\n"
            f"Введите в игре: `/moderds confirm {code}`"
        )
        return web.json_response({"status": "ok"})
    except discord.Forbidden:
        _sw_pending.pop(_sw_norm(data.get("player", "")), None)
        return web.json_response({"status": "dm_failed"})
    except Exception:
        log.exception("StaffWork: ошибка отправки ЛС")
        _sw_pending.pop(_sw_norm(data.get("player", "")), None)
        return web.json_response({"status": "dm_failed"})


async def _sw_confirm(data):
    key = _sw_norm(data.get("player", ""))
    p = _sw_pending.get(key)
    if p is None:
        return web.json_response({"status": "none"})
    if time.time() > p["expires"]:
        _sw_pending.pop(key, None)
        return web.json_response({"status": "expired"})
    if p["code"] != str(data.get("code", "")).strip():
        return web.json_response({"status": "wrong"})
    _sw_pending.pop(key, None)
    return web.json_response({"status": "ok", "username": p["username"]})


async def _sw_route(request):
    if request.path == "/health":
        return web.json_response({"ok": True})
    if request.path not in ("/verify", "/confirm"):
        return web.json_response({"status": "error"}, status=404)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error"}, status=400)
    if data.get("token") != SW_API_TOKEN:
        return web.json_response({"status": "error"}, status=403)
    if request.path == "/verify":
        return await _sw_verify(data)
    return await _sw_confirm(data)


_sw_started = False


async def _sw_on_ready():
    global _sw_started
    if _sw_started:
        return
    _sw_started = True
    app = web.Application()
    app.router.add_post("/verify", _sw_route)
    app.router.add_post("/confirm", _sw_route)
    app.router.add_get("/health", _sw_route)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, SW_HOST, SW_PORT).start()
    log.info("StaffWork API слушает на %s:%s", SW_HOST, SW_PORT)


if web is not None:
    client.add_listener(_sw_on_ready, "on_ready")
    log.info("StaffWork API подключён (старт по on_ready). Ключ: %s...", SW_API_TOKEN[:4])
else:
    log.warning("StaffWork API НЕ запущен (нет aiohttp).")
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    # На всякий случай: токен может попасть с пробелом — убираем
    TOKEN = TOKEN.strip() if TOKEN else TOKEN
    try:
        log.info("Запуск бота...")
        client.run(TOKEN, log_level=logging.INFO)
    except discord.PrivilegedIntentsRequired:
        print("❌ Включи Server Members Intent и Message Content Intent в "
              "https://discord.com/developers/applications -> Bot", flush=True)
    except discord.LoginFailure as e:
        print(f"❌ Неверный токен ({e}). Проверь Bot Token.", flush=True)
    except KeyboardInterrupt:
        print("Остановлено пользователем.")
    except Exception:
        print("❌ Фатальная ошибка:\n" + traceback.format_exc(), flush=True)
