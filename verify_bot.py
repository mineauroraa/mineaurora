"""
Встроенный бот верификации для Discord.
Используй как дополнительную защиту от ботов и рейдов, пока не настроены Wick/Dyno.

Логика:
• В указанном канале висит сообщение с кнопкой «✅ Подтвердить, что я человек».
• При нажатии пользователю выдаётся роль Verified и снимается Новичок (если есть).
• Все события пишутся в консоль.

Запуск:
    1. Убедись, что роль Verified и Новичок уже созданы (заусти setup_server.py).
    2. Впиши VERIFY_CHANNEL_ID в .env (ID канала, куда повесить кнопку).
    3. python verify_bot.py
"""
import os
import sys
import discord
from discord import ui
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_RAW = os.getenv("GUILD_ID", "").strip()
VERIFY_CHANNEL_ID = os.getenv("VERIFY_CHANNEL_ID", "").strip()

if not TOKEN:
    print("❌ Впиши DISCORD_TOKEN в файл .env")
    sys.exit(1)
if not VERIFY_CHANNEL_ID:
    print("❌ Впиши VERIFY_CHANNEL_ID в файл .env (ID канала с кнопкой верификации)")
    sys.exit(1)
GUILD_ID = int(GUILD_ID_RAW) if GUILD_ID_RAW else None
VERIFY_CHANNEL_ID = int(VERIFY_CHANNEL_ID)

VERIFY_TEXT = (
    "**👋 Добро пожаловать на сервер!**\n\n"
    "Прежде чем получить доступ к чатам, нажми кнопку ниже — "
    "это защищает сервер от ботов и рейдов.\n\n"
    "После верификации ты получишь роль **Verified** и сможешь писать в чаты. "
    "Не забудь заглянуть в <#правила> и в канал <#роли>, чтобы включить уведомления."
)

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


class VerifyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Подтвердить, что я человек",
               style=discord.ButtonStyle.success,
               emoji="✅",
               custom_id="persistent_verify_button_v1")
    async def verify(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        verified = discord.utils.get(guild.roles, name="Verified")
        newbie = discord.utils.get(guild.roles, name="Новичок")
        if verified is None:
            await interaction.response.send_message(
                "⚠️ Роль Verified не найдена. Сначала запусти setup_server.py.",
                ephemeral=True)
            return
        if verified in interaction.user.roles:
            await interaction.response.send_message("Ты уже верифицирован ✅", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(verified, reason="Верификация через кнопку")
            if newbie and newbie in interaction.user.roles:
                await interaction.user.remove_roles(newbie, reason="Верификация")
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ У бота нет прав выдавать роли. Проверь иерархию: роль бота должна быть ВЫШЕ Verified.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Готово, {interaction.user.mention}! Теперь тебе доступны все чаты сервера.",
            ephemeral=True)


GUILD_OBJ = None

@client.event
async def on_ready():
    global GUILD_OBJ
    print(f"Verify-bot запущен как {client.user}")
    if GUILD_ID:
        GUILD_OBJ = discord.Object(id=GUILD_ID)
        await tree.sync(guild=GUILD_OBJ)
    else:
        GUILD_OBJ = None
        await tree.sync()
    channel = client.get_channel(VERIFY_CHANNEL_ID)
    if channel is None:
        print(f"❌ Канал {VERIFY_CHANNEL_ID} не найден.")
        return
    # Переотправляем сообщение с кнопкой, только если его ещё нет
    async for msg in channel.history(limit=20):
        if msg.author == client.user and msg.components:
            print("Кнопка верификации уже существует — пропускаю.")
            client.add_view(VerifyView())
            return
    await channel.send(VERIFY_TEXT, view=VerifyView())
    client.add_view(VerifyView())
    print("Кнопка верификации отправлена.")


@tree.command(name="resend-verify", description="(админ) Переотправить сообщение верификации")
@discord.app_commands.checks.has_permissions(administrator=True)
async def resend(interaction: discord.Interaction):
    await interaction.channel.send(VERIFY_TEXT, view=VerifyView())
    await interaction.response.send_message("Отправлено.", ephemeral=True)


client.run(TOKEN)
