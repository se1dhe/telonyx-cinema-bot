"""Patch tiktok-autouploader:

1. Load ALL cookies (including msToken) into the session to fix status_code:5
2. Print share URL on successful publish
3. Return True on success (library returns None implicitly)
4. Add missing parameters for TikTok content review: content_check_id,
   cloud_edit_* (HD), and use real param values instead of hardcoded
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
    '\t\t\tprint(f"Published successfully! '
    "ID={r.json().get('single_post_resp_list',[{}])[0].get('item_id','')} "
    "URL={r.json().get('single_post_resp_list',[{}])[0].get('share_url','')}\")\n"
    '\t\t\tuploaded = True\n'
    '\t\t\tbreak'
)
if old_2 in content:
    content = content.replace(old_2, new_2)
    patches += 1
else:
    print("WARNING: patch 2 (publish success URL) pattern not found")

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

# --- Patch 4: add missing payload params (content_check_id, cloud_edit_*, real param values) ---
old_4 = (
    '\t\t\t\t"privacy_setting_info": {\n'
    '\t\t\t\t\t"visibility_type": 0,\n'
    '\t\t\t\t\t"allow_duet": 1,\n'
    '\t\t\t\t\t"allow_stitch": 1,\n'
    '\t\t\t\t\t"allow_comment": 1\n'
    '\t\t\t\t}\n'
    '\t\t\t}\n'
    '\t\t],\n'
    '\t\t"single_post_req_list": [\n'
    '\t\t\t{\n'
    '\t\t\t\t"batch_index": 0,\n'
    '\t\t\t\t"video_id": video_id,\n'
    '\t\t\t\t"is_long_video": 0,\n'
    '\t\t\t\t"single_post_feature_info": {\n'
    '\t\t\t\t\t"text": title,\n'
    '\t\t\t\t\t"text_extra": text_extra,\n'
    '\t\t\t\t\t"markup_text": title,\n'
    '\t\t\t\t\t"music_info": {},\n'
    '\t\t\t\t\t"poster_delay": 0,\n'
    '\t\t\t\t}\n'
    '\t\t\t}\n'
    '\t\t]'
)
new_4 = (
    '\t\t\t\t"privacy_setting_info": {\n'
    '\t\t\t\t\t"visibility_type": visibility_type,\n'
    '\t\t\t\t\t"allow_duet": allow_duet,\n'
    '\t\t\t\t\t"allow_stitch": allow_stitch,\n'
    '\t\t\t\t\t"allow_comment": allow_comment\n'
    '\t\t\t\t},\n'
    '\t\t\t\t"content_check_id": ""\n'
    '\t\t\t}\n'
    '\t\t],\n'
    '\t\t"single_post_req_list": [\n'
    '\t\t\t{\n'
    '\t\t\t\t"batch_index": 0,\n'
    '\t\t\t\t"video_id": video_id,\n'
    '\t\t\t\t"is_long_video": 0,\n'
    '\t\t\t\t"single_post_feature_info": {\n'
    '\t\t\t\t\t"text": title,\n'
    '\t\t\t\t\t"text_extra": text_extra,\n'
    '\t\t\t\t\t"markup_text": title,\n'
    '\t\t\t\t\t"music_info": {},\n'
    '\t\t\t\t\t"poster_delay": 0,\n'
    '\t\t\t\t\t"cloud_edit_video_height": 1920,\n'
    '\t\t\t\t\t"cloud_edit_video_width": 1080,\n'
    '\t\t\t\t\t"cloud_edit_is_use_video_canvas": False\n'
    '\t\t\t\t}\n'
    '\t\t\t}\n'
    '\t\t]'
)
if old_4 in content:
    content = content.replace(old_4, new_4)
    patches += 1
else:
    print("WARNING: patch 4 (payload params) pattern not found, trying partial replacements...")
    # Fallback: try replacing individual fields
    replacements = [
        ('"visibility_type": 0,', '"visibility_type": visibility_type,'),
        ('"allow_duet": 1,', '"allow_duet": allow_duet,'),
        ('"allow_stitch": 1,', '"allow_stitch": allow_stitch,'),
        ('"allow_comment": 1\n\t\t\t\t}\n\t\t\t}\n\t\t],', '"allow_comment": allow_comment\n\t\t\t\t},\n\t\t\t\t"content_check_id": ""\n\t\t\t}\n\t\t],'),
        ('"poster_delay": 0,\n\t\t\t\t}\n\t\t\t}\n\t\t]', '"poster_delay": 0,\n\t\t\t\t"cloud_edit_video_height": 1920,\n\t\t\t\t"cloud_edit_video_width": 1080,\n\t\t\t\t"cloud_edit_is_use_video_canvas": False\n\t\t\t\t}\n\t\t\t}\n\t\t]'),
    ]
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            patches += 1

with open(TIKTOK_PY, "w") as f:
    f.write(content)

print(f"Patched tiktok.py — {patches} patches applied")
if patches < 4:
    print("WARNING: expected at least 4 patches")
    sys.exit(1)
