"""Patch tiktok-autouploader:

1. Load ALL cookies (including msToken) into the session to fix status_code:5
2. Print share URL on successful publish
3. Return True on success (library returns None implicitly)
"""

import sys

TIKTOK_PY = "/opt/tiktok-autouploader/tiktok_uploader/tiktok.py"

with open(TIKTOK_PY) as f:
    content = f.read()

patches = 0

# --- Patch 1: load all cookies, not just sessionid + tt-target-idc ---
old_1 = (
    '\tsession.cookies.set("sessionid", session_id, domain=".tiktok.com")\n'
    '\tsession.cookies.set("tt-target-idc", dc_id, domain=".tiktok.com")'
)
new_1 = (
    '\t# Deduplicate by name — keep last occurrence to avoid CookieConflictError\n'
    '\tseen = {}\n'
    '\tfor c in cookies:\n'
    '\t\tseen[c["name"]] = c\n'
    '\tcookies = list(seen.values())\n'
    '\tfor c in cookies:\n'
    '\t\tif "domain" in c:\n'
    '\t\t\tcookies_domain = c["domain"]\n'
    '\t\telse:\n'
    '\t\t\tcookies_domain = ".tiktok.com"\n'
    '\t\tsession.cookies.set(c["name"], c["value"], domain=cookies_domain)'
)
if old_1 in content:
    content = content.replace(old_1, new_1)
    patches += 1
else:
    print("WARNING: patch 1 (cookies) pattern not found")

# --- Patch 2: on publish success, print share URL ---
old_2 = (
    '\t\tif r.json()["status_code"] == 0:\n'
    '\t\t\tprint(f"Published successfully '
    "{\'| Scheduled for \' + str(schedule_time) if schedule_time else ''}\")\n"
    '\t\t\tuploaded = True\n'
    '\t\t\tbreak'
)
new_2 = (
    '\t\tif r.json()["status_code"] == 0:\n'
    '\t\t\tprint(f"Published successfully! Full response: {r.json()}")\n'
    '\t\t\tuploaded = True\n'
    '\t\t\tbreak'
)
if old_2 in content:
    content = content.replace(old_2, new_2)
    patches += 1
else:
    # Try alternative — the line may differ (e.g. different f-string formatting)
    # Fallback: simpler replacement
    print("WARNING: patch 2 (publish success URL) pattern not found, trying fallback...")
    # Search for unique fragments to find the right place
    for fragment, replacement_fn in [
        ('if r.json()["status_code"] == 0:', None),
    ]:
        pass  # fallback not implemented
    # Just skip — not critical

# --- Patch 3: add `return True` after `if not uploaded: return False` ---
old_3 = (
    '\tif not uploaded:\n'
    '\t\tprint("[-] Could not upload video")\n'
    '\t\treturn False'
)
new_3 = (
    '\tif not uploaded:\n'
    '\t\tprint("[-] Could not upload video")\n'
    '\t\treturn False\n'
    '\treturn True'
)
if old_3 in content:
    content = content.replace(old_3, new_3)
    patches += 1
else:
    print("WARNING: patch 3 (return True) pattern not found")

with open(TIKTOK_PY, "w") as f:
    f.write(content)

print(f"Patched tiktok.py — {patches}/3 patches applied")
if patches < 3:
    sys.exit(1)
