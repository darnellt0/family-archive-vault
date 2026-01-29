"""
Family Archive Vault v12 - React API entrypoint

This file reuses the Flask app defined in dashboard_v11_video.py,
which now includes the /api/* routes and CORS configuration.
"""

from dashboard_v11_video import app
from services.api_ops import register_ops_routes
from pathlib import Path

register_ops_routes(app, Path(r"F:\FamilyArchive\data\archive.db"))


if __name__ == "__main__":
    # Run the same app under a clearer API-focused entrypoint name.
    app.run(host="0.0.0.0", port=5000, debug=True)
