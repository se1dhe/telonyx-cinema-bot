"""Одноразовый скрипт: сохраняет куки TikTok из твоего реального Chrome.

Не открывает новый браузер — использует твой собственный Chrome,
в котором ты уже залогинен в TikTok.

Если Chrome вдруг закрыт — скрипт сам его откроет.

Использование:
  python scripts/auth_tiktok.py <account_name> [storage_dir]
"""

import os
import sys
import json
import time
from pathlib import Path


LOGIN_URL = "https://www.tiktok.com/login"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload&lang=en"


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python scripts/auth_tiktok.py <account_name> [storage_dir]")
        sys.exit(1)

    account_name = sys.argv[1]
    storage_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".telonyx" / "storage"
    tiktok_data = storage_dir / "tiktok"
    tiktok_data.mkdir(parents=True, exist_ok=True)

    original_cwd = os.getcwd()
    os.chdir(str(tiktok_data))
    print(f"Куки будут сохранены в: {tiktok_data}")

    try:
        from phantomwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--no-sandbox"],
            )
            context = browser.new_context()
            page = context.new_page()

            print("Открываю TikTok в твоём Chrome...")
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
                print("⚠️ Куки не найдены — возможно, не удалось войти.")
            else:
                filename = f"TK_cookies_{account_name}.json"
                with open(filename, "w") as f:
                    json.dump(cookies, f, indent=4)
                print(f"✅ Сохранено {len(cookies)} кук")
                print(f"   Файл: {tiktok_data / filename}")

            context.close()
            browser.close()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()
