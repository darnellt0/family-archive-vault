from pathlib import Path

html = Path(r"F:\\familyarchive\\apps\\intake-web\\templates\\uploader.html").read_text(encoding="utf-8")

checks = {
    "localStorage": "localStorage" in html,
    "upload_id_header": "X-Upload-Id" in html,
    "resume_status": "next_offset" in html,
}

print("Resumable client checks:")
for key, ok in checks.items():
    print(f"- {key}: {'OK' if ok else 'MISSING'}")
