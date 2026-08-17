"""
Скрипт-настройщик Discord-сервера для Minecraft-сообщества.
Создаёт: роли, категории, каналы и базовые права. Идемпотентный — можно запускать повторно.

Запуск:
    1. Создай бота на https://discord.com/developers/applications -> Bot -> Reset Token
    2. На вкладке Bot включи: Server Members Intent, Message Content Intent
    3. Пригласи бота на сервер с правами администратора (или Manage Server + Manage Roles + Manage Channels)
       Ссылка-приглашение (замени CLIENT_ID):
       https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=8&scope=bot%20applications.commands
    4. Впиши токен и GUILD_ID в .env
    5. pip install -r requirements.txt
    6. python setup_server.py
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_RAW = os.getenv("GUILD_ID", "").strip()

if not TOKEN:
    print("❌ Сначала впиши DISCORD_TOKEN в файл .env")
    sys.exit(1)

GUILD_ID = None
if GUILD_ID_RAW and GUILD_ID_RAW not in ("0", "000000000000000000"):
    try:
        GUILD_ID = int(GUILD_ID_RAW)
    except ValueError:
        print(f"⚠️  GUILD_ID='{GUILD_ID_RAW}' не похож на число — буду искать сервер автоматически.")

# Цвета ролей (hex)
C = {
    "owner":   0xE91E63,
    "admin":   0xD32F2F,
    "staff":   0xFF9800,
    "helper":  0xFFC107,
    "media":   0x9C27B0,
    "dev":     0x00BCD4,
    "verified":0x4CAF50,
    "booster": 0xF47FFF,
    "new":     0x90A4AE,
    "notify_ann": 0x3B82F6,
    "notify_upd": 0x10B981,
    "notify_event":0xF59E0B,
    "notify_stream":0xEF4444,
}

@dataclass
class RoleDef:
    name: str
    color: int = 0x95A5A6
    hoist: bool = False          # показывать отдельно в списке
    mentionable: bool = False
    permissions: discord.Permissions = field(default_factory=lambda: discord.Permissions(0))
    reason: str = "Начальная настройка сервера"

@dataclass
class ChannelDef:
    name: str
    topic: str = ""
    category: Optional[str] = None
    channel_type: type = discord.TextChannel
    overwrites: dict = field(default_factory=dict)  # role_name -> (overwrite)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


# ---------- ОПИСАНИЕ СТРУКТУРЫ ----------

ROLES = [
    # Управленческий состав
    RoleDef("Владелец",      C["owner"],  hoist=True, permissions=discord.Permissions.all()),
    RoleDef("Администратор", C["admin"],  hoist=True, permissions=discord.Permissions(
        manage_guild=True, manage_roles=True, manage_channels=True, kick_members=True,
        ban_members=True, manage_messages=True, mention_everyone=True, manage_nicknames=True,
        view_audit_log=True, moderate_members=True)),
    RoleDef("Стафф",         C["staff"],  hoist=True, permissions=discord.Permissions(
        manage_messages=True, kick_members=True, mute_members=True, view_audit_log=True,
        moderate_members=True)),
    RoleDef("Хелпер",        C["helper"], hoist=True, permissions=discord.Permissions(
        manage_messages=True, view_audit_log=True)),

    # Особые
    RoleDef("YouTube",  C["media"], hoist=True),
    RoleDef("TikTok",   C["media"], hoist=True),
    RoleDef("Разработчик", C["dev"], hoist=True),
    RoleDef("Бустер",   C["booster"], hoist=True),

    # Базовые
    RoleDef("Verified", C["verified"], hoist=False,
            permissions=discord.Permissions(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, add_reactions=True, connect=True, speak=True,
                use_application_commands=True)),
    RoleDef("Новичок",  C["new"],
            permissions=discord.Permissions(
                view_channel=True, read_message_history=True)),  # писать не может до верификации

    # Роли-уведомления (реакция-роли)
    RoleDef("Новости",    C["notify_ann"], mentionable=True),
    RoleDef("Обновления", C["notify_upd"], mentionable=True),
    RoleDef("Ивенты",     C["notify_event"], mentionable=True),
    RoleDef("Стримы",     C["notify_stream"], mentionable=True),
]

# Категории и каналы
CATEGORIES = [
    "📢 ИНФОРМАЦИЯ",
    "💬 ОБЩЕНИЕ",
    "🎮 ИГРА",
    "🛠️ ПОДДЕРЖКА",
    "🔊 ГОЛОСОВЫЕ КАНАЛЫ",
    "📺 МЕДИА",
]

def base_text_overwrites(guild, default_role):
    """Базовое ограничение: писать может только Verified, читать могут все."""
    v = discord.utils.get(guild.roles, name="Verified")
    return {
        default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                   read_message_history=True),
        v: discord.PermissionOverwrite(send_messages=True),
    }


def build_channels(guild):
    everyone = guild.default_role
    admin = discord.utils.get(guild.roles, name="Администратор")
    owner = discord.utils.get(guild.roles, name="Владелец")
    staff = discord.utils.get(guild.roles, name="Стафф")
    helper = discord.utils.get(guild.roles, name="Хелпер")
    verified = discord.utils.get(guild.roles, name="Verified")
    newbie = discord.utils.get(guild.roles, name="Новичок")
    dev = discord.utils.get(guild.roles, name="Разработчик")

    chans = []

    # --- ИНФОРМАЦИЯ ---
    chans.append(ChannelDef("правила", "📜 Правила сервера и Minecraft-проекта",
        "📢 ИНФОРМАЦИЯ", overwrites={
            everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                  read_message_history=True),
        }))
    chans.append(ChannelDef("новости", "📰 Новости проекта", "📢 ИНФОРМАЦИЯ", overwrites={
        everyone: discord.PermissionOverwrite(send_messages=False, add_reactions=True,
                                              read_message_history=True),
        owner: discord.PermissionOverwrite(send_messages=True),
        admin: discord.PermissionOverwrite(send_messages=True),
        staff: discord.PermissionOverwrite(send_messages=True),
    }))
    chans.append(ChannelDef("обновления", "🆕 Апдейты и патчи сервера", "📢 ИНФОРМАЦИЯ", overwrites={
        everyone: discord.PermissionOverwrite(send_messages=False, add_reactions=True,
                                              read_message_history=True),
        owner: discord.PermissionOverwrite(send_messages=True),
        admin: discord.PermissionOverwrite(send_messages=True),
        dev:   discord.PermissionOverwrite(send_messages=True),
    }))
    chans.append(ChannelDef("анонсы", "📢 Анонсы ивентов, стримов", "📢 ИНФОРМАЦИЯ", overwrites={
        everyone: discord.PermissionOverwrite(send_messages=False, add_reactions=True,
                                              read_message_history=True),
        owner: discord.PermissionOverwrite(send_messages=True),
        admin: discord.PermissionOverwrite(send_messages=True),
        staff: discord.PermissionOverwrite(send_messages=True),
    }))
    chans.append(ChannelDef("роли", "🎭 Выбери роли-уведомления реакцией", "📢 ИНФОРМАЦИЯ", overwrites={
        everyone: discord.PermissionOverwrite(send_messages=False, add_reactions=True,
                                              read_message_history=True),
    }))

    # --- ОБЩЕНИЕ ---
    chans.append(ChannelDef("общий", "💬 Основной чат", "💬 ОБЩЕНИЕ",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("знакомства", "👋 Расскажи о себе", "💬 ОБЩЕНИЕ",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("мемы", "😂 Мемы и медиа", "💬 ОБЩЕНИЕ",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("оффтоп", "🎲 Общение на любые темы", "💬 ОБЩЕНИЕ",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("команды", "🤖 Команды ботов", "💬 ОБЩЕНИЕ", overwrites={
        everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                              read_message_history=False),
        verified: discord.PermissionOverwrite(send_messages=True, read_message_history=True),
    }))

    # --- ИГРА (Minecraft) ---
    chans.append(ChannelDef("minecraft-чат", "🌉 Мост с игровым чатом (DiscordSRV)",
        "🎮 ИГРА", overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("консоль", "🖥️ Лог и консоль сервера (только стафф)",
        "🎮 ИГРА", overwrites={
            everyone: discord.PermissionOverwrite(view_channel=False),
            owner: discord.PermissionOverwrite(view_channel=True),
            admin: discord.PermissionOverwrite(view_channel=True),
            dev:   discord.PermissionOverwrite(view_channel=True),
        }))
    chans.append(ChannelDef("баг-репорты", "🐛 Сообщи о баге", "🎮 ИГРА", overwrites={
        everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                              read_message_history=True),
        verified: discord.PermissionOverwrite(send_messages=True),
    }))
    chans.append(ChannelDef("предложения", "💡 Идеи по улучшению сервера", "🎮 ИГРА",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("магазин", "💎 Донат и покупки (только чтение)",
        "🎮 ИГРА", overwrites={
            everyone: discord.PermissionOverwrite(send_messages=False, read_message_history=True),
            owner: discord.PermissionOverwrite(send_messages=True),
            admin: discord.PermissionOverwrite(send_messages=True),
        }))

    # --- ПОДДЕРЖКА (тикеты) ---
    chans.append(ChannelDef("тикет-панель", "🎫 Нажми кнопку, чтобы создать тикет",
        "🛠️ ПОДДЕРЖКА", overwrites={
            everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                  read_message_history=True),
        }))
    chans.append(ChannelDef("заявки", "📨 Канал-информация о приёме заявок (хелпер/ютубер/тиктокер)",
        "🛠️ ПОДДЕРЖКА", overwrites={
            everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                  read_message_history=True),
        }))
    # Остальные тикеты создаются динамически ботом Ticket Tool; здесь только фоновая категория
    # для упорядочивания. Создадим один приватный канал-лог для стаффа.
    chans.append(ChannelDef("лог-тикетов", "📝 Лог действий тикет-бота",
        "🛠️ ПОДДЕРЖКА", overwrites={
            everyone: discord.PermissionOverwrite(view_channel=False),
            owner:   discord.PermissionOverwrite(view_channel=True),
            admin:   discord.PermissionOverwrite(view_channel=True),
            staff:   discord.PermissionOverwrite(view_channel=True),
            helper:  discord.PermissionOverwrite(view_channel=True),
        }))

    # --- ГОЛОСОВЫЕ ---
    chans.append(ChannelDef("🔊 Общий", "", "🔊 ГОЛОСОВЫЕ КАНАЛЫ", discord.VoiceChannel))
    chans.append(ChannelDef("🔊 Музыка", "", "🔊 ГОЛОСОВЫЕ КАНАЛЫ", discord.VoiceChannel))
    chans.append(ChannelDef("🔊 Ивент", "", "🔊 ГОЛОСОВЫЕ КАНАЛЫ", discord.VoiceChannel))
    chans.append(ChannelDef("🔒 Афк (5 мин)", "", "🔊 ГОЛОСОВЫЕ КАНАЛЫ", discord.VoiceChannel))

    # --- МЕДИА ---
    chans.append(ChannelDef("скриншоты", "📸 Скриншоты из игры", "📺 МЕДИА",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("видео", "🎬 Твои видео и клипы", "📺 МЕДИА",
        overwrites=base_text_overwrites(guild, everyone)))
    chans.append(ChannelDef("арт", "🎨 Творчество", "📺 МЕДИА",
        overwrites=base_text_overwrites(guild, everyone)))

    return chans


# ---------- ЛОГИКА СОЗДАНИЯ ----------

async def ensure_role(guild: discord.Guild, rd: RoleDef):
    role = discord.utils.get(guild.roles, name=rd.name)
    if role is None:
        role = await guild.create_role(
            name=rd.name, color=discord.Color(rd.color), hoist=rd.hoist,
            mentionable=rd.mentionable, permissions=rd.permissions, reason=rd.reason)
        print(f"  ➕ Роль создана: {role.name}")
    else:
        await role.edit(color=discord.Color(rd.color), hoist=rd.hoist,
                        mentionable=rd.mentionable, permissions=rd.permissions)
        print(f"  ✏️  Роль обновлена: {role.name}")
    return role


async def ensure_category(guild: discord.Guild, name: str):
    cat = discord.utils.get(guild.categories, name=name)
    if cat is None:
        cat = await guild.create_category(name)
        print(f"  ➕ Категория создана: {name}")
    return cat


async def ensure_channel(guild: discord.Guild, ch: ChannelDef, categories: dict):
    existing = discord.utils.get(guild.channels, name=ch.name)
    cat = categories.get(ch.category)
    overwrites = {}
    for role, ow in ch.overwrites.items():
        if role is not None:
            overwrites[role] = ow
    if existing is None:
        if ch.channel_type == discord.VoiceChannel:
            await cat.create_voice_channel(ch.name, overwrites=overwrites, reason="Настройка")
        else:
            await cat.create_text_channel(ch.name, topic=ch.topic, overwrites=overwrites, reason="Настройка")
        print(f"  ➕ Канал создан: {ch.name}")
    else:
        try:
            if ch.channel_type != discord.VoiceChannel and ch.topic:
                await existing.edit(topic=ch.topic, category=cat, overwrites=overwrites)
            else:
                await existing.edit(category=cat, overwrites=overwrites)
            print(f"  ✏️  Канал обновлён: {ch.name}")
        except Exception as e:
            print(f"  ⚠️  Не удалось обновить {ch.name}: {e}")


async def reorder_roles(guild: discord.Guild):
    """Выстраиваем иерархию ролей сверху вниз.
    Discord не разрешает боту двигать роли выше своей собственной позиции,
    поэтому все роли, которые оказались выше бота, пропускаем.
    """
    order_names = [
        "Владелец", "Администратор", "Стафф", "Хелпер",
        "Разработчик", "YouTube", "TikTok", "Бустер",
        "Новости", "Обновления", "Ивенты", "Стримы",
        "Verified", "Новичок",
    ]
    # Определяем высшую позицию роли бота
    me = guild.me
    bot_top_pos = max(r.position for r in me.roles)
    top = len(guild.roles) - 1
    positions = {}
    for i, name in enumerate(order_names):
        r = discord.utils.get(guild.roles, name=name)
        if r is None:
            continue
        target = top - i
        # Бот не может двигать роли на позицию выше своей собственной
        if target > bot_top_pos:
            target = bot_top_pos - 1
        if target < 0:
            continue
        positions[r] = target
    if not positions:
        print("  ⚠️  Порядок ролей пропущен (подними роль бота вверх вручную).")
        return
    try:
        await guild.edit_role_positions(positions)
        print("  📐 Порядок ролей выстроен.")
    except discord.HTTPException as e:
        print(f"  ⚠️  Не удалось выстроить порядок ролей ({e}). "
              f"Это косметика — перетащи роли вручную в Настройки → Роли.")


@tree.command(name="setup", description="(Только админ) Развернуть структуру сервера")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await run_setup(interaction.guild)
    await interaction.followup.send("✅ Структура сервера настроена! Проверь каналы и роли.", ephemeral=True)


async def run_setup(guild: discord.Guild):
    print("\n=== Настройка сервера:", guild.name, "===")

    print("\n1) Роли:")
    for rd in ROLES:
        await ensure_role(guild, rd)
    await reorder_roles(guild)

    print("\n2) Категории:")
    cats = {}
    for name in CATEGORIES:
        cats[name] = await ensure_category(guild, name)

    print("\n3) Каналы:")
    channels = build_channels(guild)
    for ch in channels:
        await ensure_channel(guild, ch, cats)

    # AFK voice
    afk = discord.utils.get(guild.voice_channels, name="🔒 Афк (5 мин)")
    if afk and guild.afk_channel != afk:
        await guild.edit(afk_channel=afk, afk_timeout=300)
        print("  🔇 AFK-канал установлен.")

    print("\n=== Готово ===\n")
    print("Дальше:\n"
          " • В канал #правила вставь правила сервера.\n"
          " • В #роли бот Carl-bot настроит реакция-роли (роли: Новости/Обновления/Ивенты/Стримы).\n"
          " • В #тикет-панель Ticket Tool добавит панель с выбором категории тикета.\n"
          " • В #заявки опиши условия подачи на Хелпера/YouTube/TikTok.\n"
          " • DiscordSRV привяжи к каналу #minecraft-чат и #консоль.")


@client.event
async def on_ready():
    print(f"Залогинен как {client.user} (id={client.user.id})")
    if GUILD_ID is None:
        # Автопоиск сервера, где состоит бот
        if len(client.guilds) == 0:
            print("❌ Бот ещё не добавлен ни на один сервер. Пригласи его по OAuth-ссылке.")
            await client.close()
            return
        if len(client.guilds) == 1:
            guild = client.guilds[0]
            print(f"ℹ️  GUILD_ID не указан — автоматически выбран сервер: {guild.name} (id={guild.id})")
        else:
            print("ℹ️  Бот находится на нескольких серверах. Укажи GUILD_ID в .env. Доступные:")
            for g in client.guilds:
                print(f"    - {g.name} (id={g.id})")
            await client.close()
            return
    else:
        guild = client.get_guild(GUILD_ID)
        if guild is None:
            print(f"❌ Бот не на сервере {GUILD_ID}. Пригласи его по OAuth-ссылке.")
            await client.close()
            return
    # Синхронизируем слэш-команды
    try:
        await tree.sync(guild=discord.Object(id=guild.id))
        print("Слэш-команды синхронизированы.")
    except Exception as e:
        print("Не удалось синхронизировать команды:", e)
    # Запускаем автоматическую настройку сразу
    await run_setup(guild)
    await client.close()


client.run(TOKEN)
