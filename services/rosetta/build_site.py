import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from jinja2 import Environment, FileSystemLoader

from services.worker.db import get_conn, set_ops_state
from services.worker.drive import get_drive_service, load_drive_schema, upload_json, ensure_folder
from googleapiclient.http import MediaIoBaseUpload
import io

OUTPUT_DIR = Path(r"F:\FamilyArchive\ROSETTA_STONE\nightly_site")
TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_data():
    conn = get_conn()
    assets = conn.execute("SELECT * FROM assets WHERE status = 'approved'").fetchall()
    clusters = conn.execute("SELECT id, name FROM clusters").fetchall()
    faces = conn.execute("SELECT cluster_id, COUNT(*) AS face_count FROM faces GROUP BY cluster_id").fetchall()
    conn.close()

    assets = [dict(a) for a in assets]
    clusters = [dict(c) for c in clusters]
    face_counts = {row["cluster_id"]: row["face_count"] for row in faces}

    unnamed = []
    for cluster in clusters:
        if not cluster.get("name"):
            cluster["face_count"] = face_counts.get(cluster["id"], 0)
            unnamed.append(cluster)

    return assets, clusters, unnamed


def build():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "decades").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "people").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    assets, clusters, unnamed = load_data()

    decades = defaultdict(list)
    for asset in assets:
        decade = asset.get("decade") or "Unknown"
        decades[decade].append(asset)

    people = sorted([c["name"] for c in clusters if c.get("name")])

    index_tpl = env.get_template("index.html")
    (OUTPUT_DIR / "index.html").write_text(index_tpl.render(title="Rosetta Stone v2", decades=decades, people=people), encoding="utf-8")

    decade_tpl = env.get_template("decade.html")
    for decade, items in decades.items():
        (OUTPUT_DIR / "decades" / f"{decade}.html").write_text(
            decade_tpl.render(title="By Decade", decade=decade, items=items),
            encoding="utf-8",
        )

    person_tpl = env.get_template("person.html")
    for person in people:
        (OUTPUT_DIR / "people" / f"{person.replace(' ', '_')}.html").write_text(
            person_tpl.render(title=person, person=person, items=assets),
            encoding="utf-8",
        )

    who_tpl = env.get_template("who.html")
    (OUTPUT_DIR / "who_is_this.html").write_text(
        who_tpl.render(title="Who is this?", clusters=unnamed),
        encoding="utf-8",
    )

    recovery_tpl = env.get_template("recovery.html")
    (OUTPUT_DIR / "recovery.html").write_text(
        recovery_tpl.render(title="Recovery"),
        encoding="utf-8",
    )

    search_index = [{"asset_id": a.get("asset_id"), "filename": a.get("original_filename"), "caption": a.get("caption")} for a in assets]
    (OUTPUT_DIR / "search_index.json").write_text(json.dumps(search_index, indent=2), encoding="utf-8")

    service = get_drive_service()
    schema = load_drive_schema(service)

    site_root = schema["ROSETTA_SITE"]
    decades_folder = ensure_folder(service, site_root, "decades")
    people_folder = ensure_folder(service, site_root, "people")

    for file in OUTPUT_DIR.rglob("*"):
        if not file.is_file():
            continue

        target_folder = site_root
        if "decades" in file.parts:
            target_folder = decades_folder
        if "people" in file.parts:
            target_folder = people_folder

        if file.suffix == ".json":
            upload_json(service, target_folder, file.name, json.loads(file.read_text(encoding="utf-8")))
        else:
            media = MediaIoBaseUpload(io.BytesIO(file.read_bytes()), mimetype="text/html", resumable=False)
            service.files().create(
                body={"name": file.name, "parents": [target_folder]},
                media_body=media,
                fields="id",
            ).execute()

    set_ops_state("last_rosetta_build", datetime.utcnow().isoformat())


if __name__ == "__main__":
    build()
