"""Сохраняет TikTok-куки из твоего реального Chrome.

Использование:
  python scripts/auth_tiktok.py <account_name> [storage_dir]
"""

import os
import sys
import json
from pathlib import Path


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

        user_data = str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome")

        print()
        print("ВАЖНО: Закройте Google Chrome полностью (Cmd+Q) перед продолжением!")
        input("Нажмите Enter, когда Chrome закрыт...")

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data,
                headless=False,
                args=["--no-sandbox"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.tiktok.com", timeout=60000)

            print()
            print("Браузер открыт. Если нужно — войдите в TikTok.")
            print("Затем вернитесь в терминал и нажмите Enter.")
            input("Нажмите Enter ПОСЛЕ того как вошли...")

            import time
            time.sleep(1)

            cookies = context.cookies()
            if not cookies:
                print("⚠️ Куки не найдены. Возможно, войти не удалось.")
            else:
                filename = f"TK_cookies_{account_name}.json"
                session_cookies = [c for c in cookies if c["name"] in ("sessionid", "sid_tt", "sessionid_ss")]
                with open(filename, "w") as f:
                    json.dump(cookies, f, indent=4)
                print(f"✅ Сохранено {len(cookies)} кук (из них {len(session_cookies)} сессионных)")
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
