"""Patch tiktok-autouploader to load ALL cookies (including msToken) into the session.

Replaces the two hardcoded session.cookie.set() calls with a loop over all cookies
from the cookie file. This fixes TikTok's "status_code: 5 / Invalid parameters"
because msToken was never being loaded into the requests session.
"""

import re

TIKTOK_PY = "/opt/tiktok-autouploader/tiktok_uploader/tiktok.py"

with open(TIKTOK_PY) as f:
    content = f.read()

pattern = (
    r'\t*session\.cookies\.set\("sessionid", session_id, domain="\.tiktok\.com"\)\s*\n'
    r'\t*session\.cookies\.set\("tt-target-idc", dc_id, domain="\.tiktok\.com"\)'
)

replacement = (
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

if not re.search(pattern, content):
    print("ERROR: could not find the expected code block to patch")
    print("Lines containing 'session.cookies.set':")
    for i, line in enumerate(content.splitlines(), 1):
        if "session.cookies.set" in line:
            print(f"  {i}: {line}")
    raise SystemExit(1)

content = re.sub(pattern, replacement, content)

with open(TIKTOK_PY, "w") as f:
    f.write(content)

print("Patched tiktok.py - now loading all cookies (incl. msToken) into session")
