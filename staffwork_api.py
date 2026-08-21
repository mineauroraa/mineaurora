"""
╔══════════════════════════════════════════════════════════════╗
║          StaffWork API — проверка роли и код в ЛС            ║
║   Дополнение к MineAurora-боту для плагина StaffWork (MC)    ║
╚══════════════════════════════════════════════════════════════╝

Что делает:
  1. Принимает HTTP-запрос от плагина (Java) с ником игрока и
     Discord-юзернеймом.
  2. Проверяет, есть ли у этого участника роль стаффа на сервере.
  3. Если роли нет — возвращает отказ (привязать чужой аккаунт нельзя).
  4. Если роль есть — шлёт случайный код в личные сообщения Discord.
  5. По второму запросу подтверждает код и возвращает плагину
     настоящий Discord-юзернейм для привязки.

Как подключить (в mineaurora_bot.py):
    import staffwork_api
    ...
    # ПЕРЕД client.run(TOKEN):
    staffwork_api.start_staffwork_api(client)

    Если токен читаешь через os.getenv("DISCORD_TOKEN"), просто добавь
    строки выше — ничего больше менять не нужно.

Эндпоинты (JSON):
    POST /verify   {"player": "...", "username": "...", "token": "..."}
    POST /confirm  {"player": "...", "code": "......", "token": "..."}
"""

import asyncio
import logging
import random
import time

from aiohttp import web
import discord
from discord.utils import get

log = logging.getLogger("mineaurora.staffwork")

# ═══════════════════════════════════════════════════════════════
# ⚙️  НАСТРОЙКИ — ПОМЕНЯЙ ПОД СЕБЯ
# ═══════════════════════════════════════════════════════════════

# Адрес и порт HTTP-сервера. Порт должен быть доступен с Minecraft-сервера.
# Если плагин и бот на одной машине — оставь 127.0.0.1:8080.
HOST = "0.0.0.0"
PORT = 8080

# Секретный ключ. ДОЛЖЕН совпадать с discord.api-token в config.yml плагина!
API_TOKEN = "СМЕНИ_МЕНЯ_НА_СЕКРЕТНЫЙ_КЛЮЧ"

# Роли, которые считаются стаффом. Напиши ТОЧНЫЕ названия ролей
# твоего Discord-сервера (регистр НЕ важен).
STAFF_ROLES = [
    "👑 Владелец",
    "🛡️ Администратор",
    "🔨 Стафф",
    "❓ Хелпер",
]

# ID сервера (int). Если None — берётся первый сервер, где есть бот.
# (правый клик по серверу -> Копировать ID)
GUILD_ID = None

# Время жизни кода подтверждения, в секундах
CODE_TTL = 600

# ═══════════════════════════════════════════════════════════════

_pending = {}  # nick_lower -> {"code": str, "user_id": int, "username": str, "expires": float}


def _norm(s):
    return s.strip().lower()


def _staff_roles_norm():
    return {_norm(r) for r in STAFF_ROLES}


def _resolve_guild(client):
    if GUILD_ID is not None:
        return client.get_guild(int(GUILD_ID))
    return next(iter(client.guilds), None)


def _find_member(guild, username):
    target = _norm(username)
    # сначала точное совпадение по name / global_name
    for m in guild.members:
        if _norm(getattr(m, "name", "")).strip() == target:
            return m
    for m in guild.members:
        gn = getattr(m, "global_name", None) or ""
        if _norm(gn).strip() == target:
            return m
    # потом поиск по префиксу (вдруг ввели без #0000)
    for m in guild.members:
        if _norm(getattr(m, "name", "")).startswith(target):
            return m
    return None


def _has_staff_role(member):
    allowed = _staff_roles_norm()
    for r in member.roles:
        if _norm(r.name) in allowed:
            return True
    return False


async def _handle_verify(client, data):
    guild = _resolve_guild(client)
    if guild is None:
        return web.json_response({"status": "no_guild"}, status=200)

    username = data.get("username", "")
    if not username:
        return web.json_response({"status": "not_found"}, status=200)

    member = _find_member(guild, username)
    if member is None:
        return web.json_response({"status": "not_found"}, status=200)

    if not _has_staff_role(member):
        return web.json_response({"status": "no_role"}, status=200)

    code = f"{random.randint(0, 999999):06d}"
    _pending[_norm(data.get("player", ""))] = {
        "code": code,
        "user_id": member.id,
        "username": member.name,
        "expires": time.time() + CODE_TTL,
    }

    try:
        await member.send(
            "**Подтверждение привязки StaffWork**\n"
            f"Игрок: {data.get('player', '?')}\n"
            f"Код: **{code}**\n"
            f"Введите в игре: `/moderds confirm {code}`"
        )
        return web.json_response({"status": "ok"}, status=200)
    except discord.Forbidden:
        _pending.pop(_norm(data.get("player", "")), None)
        return web.json_response({"status": "dm_failed"}, status=200)
    except Exception as e:  # noqa: BLE001
        log.exception("Ошибка отправки ЛС: %s", e)
        _pending.pop(_norm(data.get("player", "")), None)
        return web.json_response({"status": "dm_failed"}, status=200)


async def _handle_confirm(data):
    key = _norm(data.get("player", ""))
    p = _pending.get(key)
    if p is None:
        return web.json_response({"status": "none"}, status=200)
    if time.time() > p["expires"]:
        _pending.pop(key, None)
        return web.json_response({"status": "expired"}, status=200)
    if p["code"] != str(data.get("code", "")).strip():
        return web.json_response({"status": "wrong"}, status=200)

    _pending.pop(key, None)
    return web.json_response({"status": "ok", "username": p["username"]}, status=200)


async def _route(request):
    if request.path == "/health":
        return web.json_response({"ok": True}, status=200)

    if request.path not in ("/verify", "/confirm"):
        return web.json_response({"status": "error"}, status=404)

    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"status": "error"}, status=400)

    if data.get("token") != API_TOKEN:
        return web.json_response({"status": "error"}, status=403)

    if request.path == "/verify":
        return await _handle_verify(request.app["client"], data)
    return await _handle_confirm(data)


def start_staffwork_api(client: discord.Client, host: str = HOST, port: int = PORT):
    """Запускает HTTP-сервер в том же event loop, что и discord-бот."""

    app = web.Application()
    app["client"] = client
    app.router.add_post("/verify", _route)
    app.router.add_post("/confirm", _route)
    app.router.add_get("/health", _route)

    async def _start():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        log.info("StaffWork API слушает на %s:%s", host, port)

    # регистрируем задачу в цикле бота
    try:
        client.loop.create_task(_start())
    except RuntimeError:
        # на случай, если loop ещё не создан
        asyncio.get_event_loop().create_task(_start())

    log.info("StaffWork API подключён. Ключ: %s...", API_TOKEN[:4])
