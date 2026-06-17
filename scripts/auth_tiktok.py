"""Одноразовый скрипт: открывает браузер для входа в TikTok и сохраняет куки.

Использование:
  python scripts/auth_tiktok.py <account_name> [storage_dir]

После входа куки сохранятся в {storage_dir}/tiktok/TK_cookies_{account_name}.json.
По умолчанию storage_dir = /data/storage.
"""

import os
import sys
import json
import time
from pathlib import Path

from tiktokautouploader.function import UPLOAD_URL


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python scripts/auth_tiktok.py <account_name> [storage_dir]")
        print("  account_name — логин или email от TikTok (например: my_tiktok_login)")
        print("  storage_dir  — куда сохранить куки (по умолчанию ~/.telonyx/storage/)")
        print("\nПосле входа файл куков будет в: ~/.telonyx/storage/tiktok/TK_cookies_{account}.json")
        print("Его нужно будет загрузить в Railway по пути $STORAGE_DIR/tiktok/")
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
        from phantomwright.user_simulator import SyncUserSimulator

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                timezone_id="America/New_York",
            )
            Stealth(context)
            page = context.new_page()

            print("Открываю страницу загрузки TikTok...")
            print("Пожалуйста, войдите в аккаунт в открывшемся окне.")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            input("После успешного входа нажмите Enter, чтобы сохранить куки...")

            page.wait_for_timeout(2000)
            cookies = context.cookies()
            with open(f"TK_cookies_{account_name}.json", "w") as f:
                json.dump(cookies, f, indent=4)
            print(f"✅ Куки сохранены для аккаунта {account_name}")
            print(f"   Файл: {tiktok_data / f'TK_cookies_{account_name}.json'}")

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
