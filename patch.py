# -*- coding: utf-8 -*-
"""
Автопатчер для MineAurora-бота.
Сам добавляет подключение StaffWork API в mineaurora_bot.py.

Как использовать:
    1. Положи этот файл (patch.py) В ТУ ЖЕ ПАПКУ, где лежат:
       - mineaurora_bot.py
       - staffwork_api.py
    2. Останови бота (если запущен): Ctrl+C
    3. Запусти:  python patch.py
    4. Перезапусти бота:  python mineaurora_bot.py

Если всё прошло успешно, в логе бота появятся строки:
    StaffWork API подключён (старт по on_ready). Ключ: ...
    StaffWork API слушает на 0.0.0.0:8080
"""

import io
import os
import sys

FILE = "mineaurora_bot.py"

MARKER = "import staffwork_api"
INSERT_LINES = (
    "    import staffwork_api\n"
    "    staffwork_api.start_staffwork_api(client)\n"
)

ANCHOR = '        log.info("Запуск бота...")'


def main():
    here = os.path.dirname(os.path.abspath(__file__))

    bot_path = os.path.join(here, FILE)
    api_path = os.path.join(here, "staffwork_api.py")

    # Проверяем, что оба файла лежат рядом
    if not os.path.exists(bot_path):
        print(f"❌ Не найден {FILE} рядом с patch.py")
        print(f"   Положи patch.py в ту же папку, где {FILE}.")
        sys.exit(1)
    if not os.path.exists(api_path):
        print("❌ Не найден staffwork_api.py рядом с patch.py")
        print("   Скачай staffwork_api.py и положи его в эту же папку.")
        sys.exit(1)

    with io.open(bot_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Уже пропатчено?
    if MARKER in content:
        print("✅ Строки StaffWork API уже добавлены в файл. Ничего менять не нужно.")
        print("   Если в логе бота их всё равно нет — перезапусти бота: python mineaurora_bot.py")
        sys.exit(0)

    # Ищем место для вставки (перед log.info("Запуск бота..."))
    if ANCHOR not in content:
        print("❌ Не нашёл нужное место в файле (ищу строку запуска бота).")
        print("   Возможно, файл изменился. Добавь вручную перед client.run(...):")
        print("       import staffwork_api")
        print("       staffwork_api.start_staffwork_api(client)")
        sys.exit(1)

    # Вставляем перед блоком запуска
    content = content.replace(ANCHOR, INSERT_LINES + ANCHOR, 1)

    with io.open(bot_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("✅ Готово! В mineaurora_bot.py добавлено подключение StaffWork API.")
    print("   Теперь:")
    print("   1. Запусти бота:  python mineaurora_bot.py")
    print("   2. Проверь, что в логе есть: StaffWork API слушает на 0.0.0.0:8080")


if __name__ == "__main__":
    main()
