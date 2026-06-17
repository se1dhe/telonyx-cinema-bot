"""Сохраняет TikTok-сессию из твоего реального Chrome.

Открывает твой собственный Chrome с твоими профилем и куками
(закрыть Chrome перед запуском не обязательно — запускается копия).

Использование:
  python scripts/auth_tiktok.py <account_name> [storage_dir]
"""

import os
import sys
import json
import time
from pathlib import Path


CHROME_USER_DATA = str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome")


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python scripts/auth_tiktok.py <account_name> [storage_dir]")
        sys.exit(1)

    account_name = sys.argv[1]
    storage_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".telonyx" / "storage"
    tiktok_data = storage_dir / "tiktok"
    tiktok_data.mkdir(parents=True, exist_ok=True)

    apps = [
        ("Google Chrome", Path(CHROME_USER_DATA)),
    ]

    chosen_profile = None
    for name, path in apps:
        if path.exists():
            chosen_profile = path
            print(f"Найден профиль Chrome: {path}")
            break

    if not chosen_profile:
        print("❌ Профиль Chrome не найден. Убедитесь что Chrome установлен.")
        sys.exit(1)

    original_cwd = os.getcwd()
    os.chdir(str(tiktok_data))
    print(f"Куки будут сохранены в: {tiktok_data}")

    try:
        from phantomwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(chosen_profile),
                channel="chrome",
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = context.pages[0] if context.pages else context.new_page()

            print("Открываю TikTok...")
            page.goto("https://www.tiktok.com", timeout=60000)
            time.sleep(3)
            print("Текущий URL:", page.url)

            if "login" in page.url.lower():
                print()
                print("=" * 60)
                print("ВОЙДИТЕ В TIKTOK В ОТКРЫВШЕМСЯ ОКНЕ")
                print("После входа нажмите Enter в терминале")
                print("=" * 60)
                input()
                page.goto("https://www.tiktok.com", timeout=60000)
                time.sleep(2)
                print("Текущий URL:", page.url)

            cookies = context.cookies()
            if not cookies:
                print("⚠️ Куки не найдены.")
            else:
                filename = f"TK_cookies_{account_name}.json"
                with open(filename, "w") as f:
                    json.dump(cookies, f, indent=4)
                print(f"✅ Сохранено {len(cookies)} кук")
                print(f"   Файл: {tiktok_data / filename}")

            context.close()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()
