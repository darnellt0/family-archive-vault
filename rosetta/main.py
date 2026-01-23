"""Generate static Rosetta Stone site for offline browsing."""
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.drive_client import DriveClient
from shared.database import DatabaseManager, Asset, Cluster


class RosettaGenerator:
    """Generate static site for offline archive browsing."""

    def __init__(self):
        self.settings = get_settings()
        self.db = DatabaseManager(self.settings.local_db_path)
        self.drive = DriveClient(
            self.settings.service_account_json_path,
            self.settings.drive_root_folder_id
        )

        self.output_dir = Path(self.settings.local_cache) / "rosetta_site"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Setup Jinja2
        template_dir = Path(__file__).parent / "templates"
        template_dir.mkdir(exist_ok=True)
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    def generate(self):
        """Generate the complete static site."""
        logger.info("Starting Rosetta Stone generation...")

        # Create directory structure
        (self.output_dir / "assets").mkdir(exist_ok=True)
        (self.output_dir / "thumbnails").mkdir(exist_ok=True)
        (self.output_dir / "css").mkdir(exist_ok=True)
        (self.output_dir / "js").mkdir(exist_ok=True)

        # Copy thumbnails
        self._copy_thumbnails()

        # Generate CSS
        self._generate_css()

        # Get data
        session = self.db.get_session()
        try:
            assets = session.query(Asset).filter_by(status='archived').all()
            clusters = session.query(Cluster).filter(Cluster.person_name.isnot(None)).all()

            logger.info(f"Generating site for {len(assets)} archived assets")

            # Generate pages
            self._generate_index(assets)
            self._generate_decades_pages(assets)
            self._generate_people_pages(assets, clusters)
            self._generate_events_pages(assets)
            self._generate_who_is_this_page(session)
            self._generate_readme()
            self._generate_search_index(assets)

            # Upload to Drive
            self._upload_to_drive()

            logger.info(f"Rosetta Stone site generated at {self.output_dir}")

        finally:
            session.close()

    def _copy_thumbnails(self):
        """Copy thumbnails to output directory."""
        session = self.db.get_session()
        try:
            assets = session.query(Asset).filter(
                Asset.status == 'archived',
                Asset.thumbnail_path.isnot(None)
            ).all()

            for asset in assets:
                if asset.thumbnail_path and Path(asset.thumbnail_path).exists():
                    src = Path(asset.thumbnail_path)
                    dst = self.output_dir / "thumbnails" / f"{asset.asset_id}.jpg"
                    shutil.copy2(src, dst)

        finally:
            session.close()

    def _generate_css(self):
        """Generate CSS file."""
        css = """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 30px;
        }
        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        nav {
            background: white;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        nav a {
            color: #667eea;
            text-decoration: none;
            margin: 0 15px;
            font-weight: 600;
        }
        nav a:hover {
            text-decoration: underline;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .card {
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        .card img {
            width: 100%;
            height: 200px;
            object-fit: cover;
        }
        .card-content {
            padding: 15px;
        }
        .card-title {
            font-weight: 600;
            margin-bottom: 5px;
            color: #333;
        }
        .card-meta {
            font-size: 0.9em;
            color: #666;
        }
        .section {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .section h2 {
            color: #667eea;
            margin-bottom: 20px;
        }
        .badge {
            display: inline-block;
            padding: 5px 10px;
            background: #667eea;
            color: white;
            border-radius: 5px;
            font-size: 0.9em;
            margin: 5px 5px 5px 0;
        }
        .search-box {
            width: 100%;
            padding: 15px;
            font-size: 1.1em;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        footer {
            text-align: center;
            padding: 40px 20px;
            color: #666;
            font-size: 0.9em;
        }
        """

        css_file = self.output_dir / "css" / "style.css"
        css_file.write_text(css)

    def _generate_index(self, assets: List[Asset]):
        """Generate index page."""
        # Group by decade
        by_decade = defaultdict(list)
        by_people = defaultdict(int)
        by_event = defaultdict(int)

        for asset in assets:
            if asset.decade:
                by_decade[asset.decade].append(asset)

            if asset.event_name:
                by_event[asset.event_name] += 1

            for face in asset.faces:
                if face.person_name:
                    by_people[face.person_name] += 1

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Family Archive - Rosetta Stone</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>📸 Family Archive</h1>
        <p>Rosetta Stone - Offline Archive Browser</p>
        <p style="opacity: 0.8; font-size: 0.9em;">Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
    </header>

    <div class="container">
        <nav>
            <a href="index.html">Home</a>
            <a href="decades.html">By Decade</a>
            <a href="people.html">People</a>
            <a href="events.html">Events</a>
            <a href="who-is-this.html">Who Is This?</a>
            <a href="readme.html">README</a>
        </nav>

        <div class="section">
            <h2>Archive Statistics</h2>
            <p><strong>Total Photos & Videos:</strong> {len(assets)}</p>
            <p><strong>Decades Covered:</strong> {len(by_decade)}</p>
            <p><strong>People Identified:</strong> {len(by_people)}</p>
            <p><strong>Events Documented:</strong> {len(by_event)}</p>
        </div>

        <div class="section">
            <h2>Browse by Decade</h2>
            <div class="grid">
                {"".join(f'<a href="decade-{decade}.html" class="card"><div class="card-content"><div class="card-title">{decade}s</div><div class="card-meta">{len(items)} items</div></div></a>' for decade, items in sorted(by_decade.items()))}
            </div>
        </div>

        <div class="section">
            <h2>Browse by People</h2>
            <div>
                {"".join(f'<a href="person-{name.replace(" ", "-").lower()}.html" class="badge">{name} ({count})</a>' for name, count in sorted(by_people.items(), key=lambda x: -x[1])[:20])}
            </div>
        </div>

        <div class="section">
            <h2>Recent Additions</h2>
            <div class="grid">
                {"".join(self._render_asset_card(asset) for asset in sorted(assets, key=lambda a: a.created_at, reverse=True)[:12])}
            </div>
        </div>
    </div>

    <footer>
        <p>Family Archive Rosetta Stone</p>
        <p>This is a static snapshot of the family archive, designed to be preserved and browsable offline.</p>
        <p>All originals are stored in Google Drive. See README for recovery instructions.</p>
    </footer>
</body>
</html>"""

        (self.output_dir / "index.html").write_text(html)

    def _generate_decades_pages(self, assets: List[Asset]):
        """Generate decade pages."""
        by_decade = defaultdict(list)
        for asset in assets:
            if asset.decade:
                by_decade[asset.decade].append(asset)

        for decade, decade_assets in by_decade.items():
            html = self._generate_gallery_page(
                f"{decade}s",
                f"Photos and videos from the {decade}s",
                decade_assets
            )
            (self.output_dir / f"decade-{decade}.html").write_text(html)

    def _generate_people_pages(self, assets: List[Asset], clusters: List[Cluster]):
        """Generate people pages."""
        for cluster in clusters:
            if not cluster.person_name:
                continue

            # Find assets with this person
            person_assets = []
            for asset in assets:
                for face in asset.faces:
                    if face.person_name == cluster.person_name:
                        person_assets.append(asset)
                        break

            html = self._generate_gallery_page(
                cluster.person_name,
                f"Photos featuring {cluster.person_name}",
                person_assets
            )

            filename = f"person-{cluster.person_name.replace(' ', '-').lower()}.html"
            (self.output_dir / filename).write_text(html)

    def _generate_events_pages(self, assets: List[Asset]):
        """Generate event pages."""
        by_event = defaultdict(list)
        for asset in assets:
            if asset.event_name:
                by_event[asset.event_name].append(asset)

        # Create events index
        events_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Events - Family Archive</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>📅 Events</h1>
    </header>
    <div class="container">
        <nav>
            <a href="index.html">Home</a>
            <a href="decades.html">By Decade</a>
            <a href="people.html">People</a>
            <a href="events.html">Events</a>
            <a href="who-is-this.html">Who Is This?</a>
        </nav>
        <div class="section">
            <h2>All Events</h2>
            {"".join(f'<a href="event-{event.replace(" ", "-").lower()}.html" class="badge">{event} ({len(items)})</a>' for event, items in sorted(by_event.items()))}
        </div>
    </div>
</body>
</html>"""

        (self.output_dir / "events.html").write_text(events_html)

        # Individual event pages
        for event, event_assets in by_event.items():
            html = self._generate_gallery_page(event, f"Photos from {event}", event_assets)
            filename = f"event-{event.replace(' ', '-').lower()}.html"
            (self.output_dir / filename).write_text(html)

    def _generate_who_is_this_page(self, session):
        """Generate 'Who Is This?' page for unnamed clusters."""
        from shared.database import Cluster, Face

        unnamed_clusters = session.query(Cluster).filter(
            Cluster.person_name.is_(None),
            Cluster.face_count >= 5
        ).order_by(Cluster.face_count.desc()).limit(20).all()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Who Is This? - Family Archive</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>❓ Who Is This?</h1>
        <p>Help us identify these people!</p>
    </header>
    <div class="container">
        <nav>
            <a href="index.html">Home</a>
            <a href="decades.html">By Decade</a>
            <a href="people.html">People</a>
            <a href="events.html">Events</a>
            <a href="who-is-this.html">Who Is This?</a>
        </nav>
        <div class="section">
            <p>These faces appear in multiple photos but haven't been identified yet. If you recognize anyone, please let the archive curator know!</p>
        </div>
        {"".join(f'''
        <div class="section">
            <h2>Cluster #{cluster.cluster_id} - Appears in {cluster.face_count} photos</h2>
            <div class="grid">
                {"".join(self._render_cluster_sample(session, asset_id) for asset_id in (cluster.sample_asset_ids or [])[:6])}
            </div>
        </div>
        ''' for cluster in unnamed_clusters)}
    </div>
</body>
</html>"""

        (self.output_dir / "who-is-this.html").write_text(html)

    def _generate_readme(self):
        """Generate README page with recovery instructions."""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>README - Family Archive</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>📖 README</h1>
        <p>About This Archive</p>
    </header>
    <div class="container">
        <nav>
            <a href="index.html">Home</a>
            <a href="decades.html">By Decade</a>
            <a href="people.html">People</a>
            <a href="events.html">Events</a>
            <a href="who-is-this.html">Who Is This?</a>
            <a href="readme.html">README</a>
        </nav>

        <div class="section">
            <h2>About the Family Archive Vault</h2>
            <p>This is a static snapshot of our family's digital archive, generated to ensure our memories can be accessed even if the main system is unavailable.</p>
        </div>

        <div class="section">
            <h2>What's Included</h2>
            <ul>
                <li>Curated photos and videos from family members</li>
                <li>AI-generated captions and metadata</li>
                <li>Face detection and people identification</li>
                <li>Organization by decade, event, and person</li>
            </ul>
        </div>

        <div class="section">
            <h2>Where Are the Originals?</h2>
            <p>All original files are stored in Google Drive under the "Family_Archive" folder with the following structure:</p>
            <ul>
                <li><strong>ARCHIVE/Originals/</strong> - Original photos organized by decade</li>
                <li><strong>ARCHIVE/Videos/</strong> - Original videos organized by decade</li>
                <li><strong>METADATA/sidecars_json/</strong> - JSON metadata files for each asset</li>
                <li><strong>METADATA/thumbnails/</strong> - Preview images</li>
            </ul>
        </div>

        <div class="section">
            <h2>Recovery Instructions</h2>
            <p>If you need to recover or access the full archive:</p>
            <ol>
                <li>Access the Google Drive folder "Family_Archive"</li>
                <li>All original files are in ARCHIVE/Originals and ARCHIVE/Videos</li>
                <li>Each file has a corresponding JSON sidecar in METADATA/sidecars_json with full metadata</li>
                <li>The SQLite database can be rebuilt from sidecar files if needed</li>
            </ol>
        </div>

        <div class="section">
            <h2>Technology</h2>
            <p>This archive uses:</p>
            <ul>
                <li>Google Drive for storage</li>
                <li>Local AI for face detection and captioning (no cloud processing)</li>
                <li>Static HTML for offline browsing (this site)</li>
                <li>Immutable originals - never modified</li>
            </ul>
        </div>

        <div class="section">
            <h2>Contact</h2>
            <p>For questions about the archive or to contribute photos, contact the family archive curator.</p>
        </div>
    </div>
</body>
</html>"""

        (self.output_dir / "readme.html").write_text(html)

    def _generate_search_index(self, assets: List[Asset]):
        """Generate JSON search index."""
        index = []
        for asset in assets:
            index.append({
                "id": asset.asset_id,
                "filename": asset.original_filename,
                "caption": asset.caption,
                "decade": asset.decade,
                "event": asset.event_name,
                "people": [f.person_name for f in asset.faces if f.person_name],
                "tags": asset.tags
            })

        search_js = f"const searchIndex = {json.dumps(index, indent=2)};"
        (self.output_dir / "js" / "search-index.js").write_text(search_js)

    def _generate_gallery_page(self, title: str, description: str, assets: List[Asset]) -> str:
        """Generate a gallery page."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Family Archive</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>{title}</h1>
        <p>{description}</p>
    </header>
    <div class="container">
        <nav>
            <a href="index.html">Home</a>
            <a href="decades.html">By Decade</a>
            <a href="people.html">People</a>
            <a href="events.html">Events</a>
            <a href="who-is-this.html">Who Is This?</a>
        </nav>
        <div class="grid">
            {"".join(self._render_asset_card(asset) for asset in assets)}
        </div>
    </div>
</body>
</html>"""

    def _render_asset_card(self, asset: Asset) -> str:
        """Render an asset card."""
        thumbnail = f"thumbnails/{asset.asset_id}.jpg" if asset.thumbnail_path else ""
        caption = asset.caption[:100] + "..." if asset.caption and len(asset.caption) > 100 else (asset.caption or "")

        return f"""
        <div class="card">
            <img src="{thumbnail}" alt="{asset.original_filename}">
            <div class="card-content">
                <div class="card-title">{asset.original_filename}</div>
                <div class="card-meta">{asset.decade}s • {asset.asset_type}</div>
                {f'<div class="card-meta" style="margin-top: 5px; font-size: 0.85em;">{caption}</div>' if caption else ''}
            </div>
        </div>
        """

    def _render_cluster_sample(self, session, asset_id: str) -> str:
        """Render a cluster sample image."""
        asset = session.query(Asset).filter_by(asset_id=asset_id).first()
        if not asset or not asset.thumbnail_path:
            return ""

        thumbnail = f"thumbnails/{asset.asset_id}.jpg"
        return f"""
        <div class="card">
            <img src="{thumbnail}" alt="Sample">
        </div>
        """

    def _upload_to_drive(self):
        """Upload generated site to Drive."""
        try:
            rosetta_folder_id = self.drive.get_or_create_folder("ROSETTA_STONE")
            site_folder_id = self.drive.get_or_create_folder("nightly_site", rosetta_folder_id)

            # Upload all files
            for file_path in self.output_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(self.output_dir)
                    logger.info(f"Uploading {relative_path} to Drive...")
                    self.drive.upload_file(file_path, site_folder_id)

            logger.info("Rosetta Stone site uploaded to Drive")

        except Exception as e:
            logger.error(f"Error uploading to Drive: {e}")


def main():
    """Entry point for Rosetta generator."""
    generator = RosettaGenerator()
    generator.generate()
    logger.info("Rosetta Stone generation complete!")


if __name__ == "__main__":
    main()
