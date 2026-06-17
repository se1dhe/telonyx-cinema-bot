"""Одноразовый скрипт: открывает браузер для входа в TikTok и сохраняет куки.

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
        print("  account_name — логин или email от TikTok")
        print("  storage_dir  — куда сохранить куки (по умолчанию ~/.telonyx/storage/)")
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
        from phantomwright.stealth import Stealth

        with sync_playwright() as pw:
            stealth = Stealth(navigator_languages_override=("en-US", "en"))
            browser = pw.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
            )
            stealth.apply_stealth_sync(context)
            page = context.new_page()

            print("Открываю страницу входа TikTok...")
            page.goto(LOGIN_URL, timeout=120000)
            time.sleep(2)

            print()
            print("=" * 60)
            print("ВОЙДИТЕ В АККАУНТ TIKTOK В ОТКРЫВШЕМСЯ ОКНЕ БРАУЗЕРА")
            print("После входа вы должны оказаться в ленте TikTok.")
            print("Затем закройте вкладку и нажмите Enter в терминале.")
            print("=" * 60)
            print()

            input("Нажмите Enter ПОСЛЕ того, как вошли в TikTok...")

            time.sleep(1)
            page.goto(UPLOAD_URL, timeout=60000)
            time.sleep(2)

            cookies = context.cookies()
            if not cookies:
                print("⚠️ Куки пустые — возможно, вход не удался.")
            else:
                filename = f"TK_cookies_{account_name}.json"
                with open(filename, "w") as f:
                    json.dump(cookies, f, indent=4)
                print(f"✅ Куки сохранены ({len(cookies)} штук)")
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
