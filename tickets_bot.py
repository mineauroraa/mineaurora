"""
Бот тикетов для Discord с разными типами обращений и формами-анкетами.
В канале #тикет-панель висит панель с 6 кнопками. Для заявок на Хелпера,
YouTube и TikTok открывается модальное окно с полями; после отправки бот
создаёт приватный канал с заполненной анкетой.

Запуск:
    python tickets_bot.py
"""
import os
import sys
from datetime import datetime, timezone

import discord
from discord import ui
from discord.utils import get
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ Впиши DISCORD_TOKEN в .env")
    sys.exit(1)

PANEL_CHANNEL_NAME = "тикет-панель"
LOG_CHANNEL_NAME = "лог-тикетов"
CATEGORY_NAME = "🛠️ ПОДДЕРЖКА"
ARCHIVE_CATEGORY_NAME = "📦 Архив тикетов"

STAFF_ROLES = ["👑 Владелец", "🛡️ Администратор", "🔨 Стафф", "❓ Хелпер"]

PANEL_TEXT = (
    "**🎫 ПОДДЕРЖКА MINEAURORA**\n\n"
    "Выбери тип обращения — нажми одну из кнопок ниже. "
    "Для заявок на Хелпера/YouTube/TikTok откроется короткая анкета.\n\n"
    "🎧 **Тех. поддержка** — общие вопросы, не знаешь куда писать\n"
    "🚨 **Пожаловаться** — жалоба на игрока или нарушение\n"
    "🐛 **Сообщить о баге** — нашёл баг, опиши как воспроизвести\n"
    "❓ **Заявка на Хелпера** — анкета в команду модерации\n"
    "📺 **Заявка на YouTube** — анкета для контент-мейкеров\n"
    "🎵 **Заявка на TikTok** — анкета для тиктокеров\n"
    "🛒 **Вопрос по донату** — покупки, привилегии, оплата"
)

SIMPLE_PROMPTS = {
    "report": (
        "Опиши жалобу:\n"
        "• **Ник нарушителя:**\n"
        "• **Что произошло:**\n"
        "• **Доказательства** (скриншот/видео — прикрепи сюда же):\n\n"
        "Стафф скоро подключится. {staff}"
    ),
    "bug": (
        "Опиши баг:\n"
        "• **Что случилось:**\n"
        "• **Как воспроизвести** (по шагам):\n"
        "• **Ожидал что произойдёт:**\n"
        "• **Скриншот/видео** (если есть):\n\n"
        "Спасибо за помощь проекту! {staff}"
    ),
    "donate": (
        "Опиши вопрос по донату:\n"
        "• **Что хочешь купить / какая привилегия:**\n"
        "• **Проблема с оплатой?** Опиши:\n"
        "• **Ник в Minecraft:**\n\n"
        "Администрация скоро ответит. {staff}"
    ),
    "support": (
        "Опиши свой вопрос:\n"
        "• **С чем нужна помощь:**\n"
        "• **Что уже пробовал(а) сделать:**\n"
        "• **Скриншот** (если уместен):\n\n"
        "Мы постараемся помочь как можно скорее. {staff}"
    ),
}

TYPE_META = {
    "report":  {"label": "Пожаловаться",        "emoji": "🚨", "color": discord.ButtonStyle.danger,  "prefix": "жалоба"},
    "bug":     {"label": "Сообщить о баге",     "emoji": "🐛", "color": discord.ButtonStyle.primary, "prefix": "баг"},
    "helper":  {"label": "Заявка на Хелпера",   "emoji": "❓", "color": discord.ButtonStyle.success,  "prefix": "хелпер"},
    "youtube": {"label": "Заявка на YouTube",   "emoji": "📺", "color": discord.ButtonStyle.danger,   "prefix": "youtube"},
    "tiktok":  {"label": "Заявка на TikTok",    "emoji": "🎵", "color": discord.ButtonStyle.secondary,"prefix": "tiktok"},
    "donate":  {"label": "Вопрос по донату",    "emoji": "🛒", "color": discord.ButtonStyle.success,  "prefix": "донат"},
    "support": {"label": "Тех. поддержка",      "emoji": "🎧", "color": discord.ButtonStyle.primary,  "prefix": "саппорт"},
}

intents = discord.Intents.default()
intents.members = True
intents.messages = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


def utcnow():
    return datetime.now(timezone.utc)


def is_staff(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True
    if member.guild_permissions.administrator:
        return True
    if member.guild_permissions.manage_channels:
        return True
    return any(r.name in STAFF_ROLES for r in member.roles)


def staff_overwrites(guild: discord.Guild, author: discord.Member):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            read_message_history=True),
    }
    for role_name in STAFF_ROLES:
        role = get(guild.roles, name=role_name)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                read_message_history=True)
    return overwrites


def staff_mentions(guild: discord.Guild) -> str:
    mentions = []
    for name in STAFF_ROLES:
        if name == "👑 Владелец":
            continue
        r = get(guild.roles, name=name)
        if r:
            mentions.append(r.mention)
    return " ".join(mentions)


async def create_ticket_channel(
    interaction: discord.Interaction,
    type_key: str,
    first_message: str,
    embed_title: str,
    embed_color: discord.Color,
):
    guild = interaction.guild
    meta = TYPE_META[type_key]
    category = get(guild.categories, name=CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(CATEGORY_NAME)

    # Не даём плодить одинаковые тикеты
    for ch in guild.text_channels:
        if ch.topic and ch.topic.startswith(f"ticket:{interaction.user.id}:{type_key}:"):
            await interaction.response.send_message(
                f"У тебя уже есть открытый тикет этого типа: {ch.mention}",
                ephemeral=True)
            return None

    count = sum(1 for c in guild.text_channels
                if c.name.startswith(f"тикет-{meta['prefix']}-")) + 1
    overwrites = staff_overwrites(guild, interaction.user)
    channel = await category.create_text_channel(
        name=f"тикет-{meta['prefix']}-{count:03d}",
        topic=f"ticket:{interaction.user.id}:{type_key}:{utcnow().isoformat()}",
        overwrites=overwrites)

    embed = discord.Embed(
        title=embed_title,
        description=first_message.replace("{staff}", staff_mentions(guild)),
        color=embed_color,
        timestamp=utcnow())
    embed.set_footer(text=f"Автор: {interaction.user}")
    await channel.send(
        content=f"{interaction.user.mention} {staff_mentions(guild)}",
        embed=embed,
        view=TicketActionsView())

    log = get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if log:
        await log.send(
            f"📂 `{utcnow().strftime('%H:%M:%S')}` {interaction.user} "
            f"(`{interaction.user.id}`) открыл(а) **{meta['label']}**: {channel.mention}")

    return channel


# ---------- МОДАЛЬНЫЕ ФОРМЫ ----------
class HelperModal(ui.Modal, title="Заявка на Хелпера"):
    name = ui.TextInput(label="Имя/ник", placeholder="Как тебя называть",
                        required=True, max_length=50)
    age = ui.TextInput(label="Возраст", placeholder="Например: 16",
                       required=True, max_length=3)
    online = ui.TextInput(label="Онлайн в день (часов)",
                          placeholder="Например: 3-4", required=True, max_length=20)
    why = ui.TextInput(label="Почему именно ты?",
                       placeholder="Расскажи об опыте, своих качествах...",
                       style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
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
    channel = ui.TextInput(label="Ссылка на канал",
                           placeholder="https://youtube.com/@...",
                           required=True, max_length=200)
    subs = ui.TextInput(label="Подписчики",
                        placeholder="Например: 120", required=True, max_length=20)
    freq = ui.TextInput(label="Частота выхода видео",
                        placeholder="1 видео в неделю", required=True, max_length=100)
    topic = ui.TextInput(label="Тематика контента",
                         placeholder="Выживание, мини-игры, гайды...",
                         style=discord.TextStyle.paragraph, required=True, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        msg = (
            f"**📺 Анкета YouTube**\n\n"
            f"• **Канал:** {self.channel.value}\n"
            f"• **Подписчики:** {self.subs.value}\n"
            f"• **Частота:** {self.freq.value}\n"
            f"• **Тематика:** {self.topic.value}\n\n"
            "Мы рассмотрим заявку и свяжемся с тобой. {staff}"
        )
        ch = await create_ticket_channel(
            interaction, "youtube", msg,
            "📺 Заявка на YouTube", discord.Color.red())
        if ch is not None:
            await interaction.response.send_message(
                f"✅ Заявка отправлена! Тикет: {ch.mention}", ephemeral=True)


class TikTokModal(ui.Modal, title="Заявка на TikTok"):
    account = ui.TextInput(label="Ссылка на аккаунт",
                           placeholder="https://tiktok.com/@...",
                           required=True, max_length=200)
    freq = ui.TextInput(label="Частота выхода видео",
                        placeholder="3-4 ролика в неделю", required=True, max_length=100)
    topic = ui.TextInput(label="Что снимаешь?",
                         placeholder="Shorts по выживанию, постройки, смешные моменты...",
                         style=discord.TextStyle.paragraph, required=True, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        msg = (
            f"**🎵 Анкета TikTok**\n\n"
            f"• **Аккаунт:** {self.account.value}\n"
            f"• **Частота:** {self.freq.value}\n"
            f"• **Контент:** {self.topic.value}\n\n"
            "Рассмотрим заявку в ближайшее время. {staff}"
        )
        ch = await create_ticket_channel(
            interaction, "tiktok", msg,
            "🎵 Заявка на TikTok", discord.Color.blurple())
        if ch is not None:
            await interaction.response.send_message(
                f"✅ Заявка отправлена! Тикет: {ch.mention}", ephemeral=True)


# ---------- ПАНЕЛЬ С КНОПКАМИ ----------
class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _open_simple(self, interaction, type_key, title, color):
        prompt = SIMPLE_PROMPTS[type_key]
        ch = await create_ticket_channel(interaction, type_key, prompt, title, color)
        if ch is not None:
            label = TYPE_META[type_key]["label"]
            await interaction.response.send_message(
                f"✅ {label}: тикет создан {ch.mention}", ephemeral=True)

    @ui.button(label="Тех. поддержка", emoji="🎧", style=discord.ButtonStyle.primary,
               custom_id="ticket_btn_support_v2", row=0)
    async def btn_support(self, interaction, button):
        await self._open_simple(interaction, "support", "🎧 Тех. поддержка", discord.Color.blue())

    @ui.button(label="Пожаловаться", emoji="🚨", style=discord.ButtonStyle.danger,
               custom_id="ticket_btn_report_v2", row=0)
    async def btn_report(self, interaction, button):
        await self._open_simple(interaction, "report", "🚨 Жалоба на игрока", discord.Color.red())

    @ui.button(label="Сообщить о баге", emoji="🐛", style=discord.ButtonStyle.secondary,
               custom_id="ticket_btn_bug_v2", row=0)
    async def btn_bug(self, interaction, button):
        await self._open_simple(interaction, "bug", "🐛 Баг-репорт", discord.Color.orange())

    @ui.button(label="Заявка на Хелпера", emoji="❓", style=discord.ButtonStyle.success,
               custom_id="ticket_btn_helper_v2", row=1)
    async def btn_helper(self, interaction, button):
        await interaction.response.send_modal(HelperModal())

    @ui.button(label="Заявка на YouTube", emoji="📺", style=discord.ButtonStyle.danger,
               custom_id="ticket_btn_youtube_v2", row=1)
    async def btn_youtube(self, interaction, button):
        await interaction.response.send_modal(YouTubeModal())

    @ui.button(label="Заявка на TikTok", emoji="🎵", style=discord.ButtonStyle.secondary,
               custom_id="ticket_btn_tiktok_v2", row=1)
    async def btn_tiktok(self, interaction, button):
        await interaction.response.send_modal(TikTokModal())

    @ui.button(label="Вопрос по донату", emoji="🛒", style=discord.ButtonStyle.success,
               custom_id="ticket_btn_donate_v2", row=2)
    async def btn_donate(self, interaction, button):
        await self._open_simple(interaction, "donate", "🛒 Вопрос по донату", discord.Color.green())


# ---------- КНОПКИ ВНУТРИ ТИКЕТА ----------
class TicketActionsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Закрыть тикет", emoji="🔒",
               style=discord.ButtonStyle.danger,
               custom_id="close_ticket_btn_v2")
    async def close(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "Закрыть тикет может только стафф.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{interaction.user.mention} закрывает тикет через 5 секунд...")
        await _archive_ticket(interaction.channel, interaction.user)

    @ui.button(label="Сохранить переписку", emoji="📝",
               style=discord.ButtonStyle.secondary,
               custom_id="transcript_btn_v2")
    async def transcript(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "Эта кнопка доступна только стаффу.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msgs = []
        async for m in interaction.channel.history(limit=500, oldest_first=True):
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = m.content or "(вложение/эмбед)"
            msgs.append(f"[{ts}] {m.author}: {content}")
        filename = f"transcript-{interaction.channel.name}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(msgs))
        await interaction.followup.send(
            "📝 Переписка сохранена:", file=discord.File(filename), ephemeral=True)
        os.remove(filename)


async def _archive_ticket(channel: discord.TextChannel, closed_by: discord.Member):
    import asyncio
    await asyncio.sleep(5)
    try:
        archive = get(channel.guild.categories, name=ARCHIVE_CATEGORY_NAME)
        if archive is None:
            archive = await channel.guild.create_category(ARCHIVE_CATEGORY_NAME)
        overwrites = dict(channel.overwrites)
        for target in list(overwrites.keys()):
            if isinstance(target, discord.Member):
                overwrites[target] = discord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=archive,
                           name=f"закрыт-{channel.name}",
                           overwrites=overwrites,
                           reason=f"Закрыл {closed_by}")
        log = get(channel.guild.text_channels, name=LOG_CHANNEL_NAME)
        if log:
            await log.send(
                f"📁 `{utcnow().strftime('%H:%M:%S')}` {closed_by} "
                f"закрыл(а) тикет #{channel.name}")
        await channel.send("🔒 Тикет закрыт и перемещён в архив.")
    except Exception as e:
        print("Ошибка архивации:", e)


@tree.command(name="panel", description="(админ) Отправить панель тикетов")
@discord.app_commands.checks.has_permissions(administrator=True)
async def panel_cmd(interaction: discord.Interaction):
    await interaction.channel.send(PANEL_TEXT, view=PanelView())
    await interaction.response.send_message("✅ Панель отправлена.", ephemeral=True)


@client.event
async def on_ready():
    print(f"Tickets-бот запущен как {client.user}")
    await tree.sync()
    channel = get(client.get_all_channels(), name=PANEL_CHANNEL_NAME)
    if channel is None:
        print(f"⚠️ Канал #{PANEL_CHANNEL_NAME} не найден. Используй /panel.")
    else:
        found = False
        async for msg in channel.history(limit=50):
            if msg.author == client.user and msg.components:
                found = True
                break
        if not found:
            await channel.send(PANEL_TEXT, view=PanelView())
            print(f"Панель отправлена в #{channel.name}.")
        else:
            print("Панель уже существует.")
    # Регистрируем persistent views
    client.add_view(PanelView())
    client.add_view(TicketActionsView())
    print("Готов. Бот работает. Нажми Ctrl+C для остановки.")


if __name__ == "__main__":
    try:
        client.run(TOKEN)
    except discord.PrivilegedIntentsRequired:
        print("❌ Включи Server Members Intent на "
              "https://discord.com/developers/applications -> Bot")
