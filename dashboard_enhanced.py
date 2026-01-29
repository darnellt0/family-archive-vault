"""Enhanced Family Archive Vault Dashboard - Flask Application.

A comprehensive web dashboard for managing family media archives with:
- Search and filtering
- Bulk operations
- Pagination
- Enhanced sorting
- Keyboard shortcuts
- Toast notifications
- Statistics with charts
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Tuple

from flask import (
    Flask, render_template_string, request, jsonify,
    redirect, url_for, send_file, abort
)
from sqlalchemy import func, and_, or_, desc, asc
from sqlalchemy.orm import Session

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from shared.config import get_settings
from shared.database import DatabaseManager, Asset, Review
from shared.drive_client import DriveClient
from worker.local_folder_poller import LocalFolderPoller

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'family-archive-vault-secret-key')

# Configuration
ITEMS_PER_PAGE = 12
VALID_SORT_OPTIONS = {
    'newest': ('upload_timestamp', 'desc'),
    'oldest': ('upload_timestamp', 'asc'),
    'filename_asc': ('original_filename', 'asc'),
    'filename_desc': ('original_filename', 'desc'),
    'largest': ('file_size_bytes', 'desc'),
    'smallest': ('file_size_bytes', 'asc'),
}

# Status mappings for the application
STATUS_MAPPING = {
    'pending': 'needs_review',
    'approved': 'approved',
    'rejected': 'error',  # Using 'error' status for rejected items
    'archived': 'archived',
}


def get_db() -> DatabaseManager:
    """Get database manager instance."""
    settings = get_settings()
    return DatabaseManager(settings.local_db_path)


def get_drive_client() -> DriveClient:
    """Get Google Drive client instance."""
    settings = get_settings()
    return DriveClient(
        settings.service_account_json_path,
        settings.drive_root_folder_id
    )


def get_local_sync_status() -> Optional[dict]:
    """Get local folder sync status if enabled."""
    settings = get_settings()
    if not settings.enable_local_folder_sync or not settings.local_sync_folder:
        return None

    try:
        poller = LocalFolderPoller(
            sync_folder=settings.local_sync_folder,
            cache_dir=settings.local_cache,
            processed_dir=os.path.join(settings.local_cache, "local_sync_processed")
        )
        return poller.get_sync_status()
    except Exception as e:
        return {'error': str(e), 'is_enabled': False}


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string to datetime object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def get_status_counts(session: Session) -> dict:
    """Get counts for each status."""
    counts = {}
    for display_name, db_status in STATUS_MAPPING.items():
        count = session.query(Asset).filter(Asset.status == db_status).count()
        counts[display_name] = count
    # Total count
    counts['total'] = session.query(Asset).count()
    return counts


def build_query_filters(
    session: Session,
    status: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    size_min: Optional[int] = None,
    size_max: Optional[int] = None,
):
    """Build SQLAlchemy query with filters."""
    query = session.query(Asset)

    # Status filter
    if status and status in STATUS_MAPPING:
        query = query.filter(Asset.status == STATUS_MAPPING[status])

    # Search filter (filename)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Asset.original_filename.ilike(search_term),
                Asset.caption.ilike(search_term),
                Asset.event_name.ilike(search_term),
            )
        )

    # Date range filter
    date_from_parsed = parse_date(date_from)
    date_to_parsed = parse_date(date_to)

    if date_from_parsed:
        query = query.filter(Asset.upload_timestamp >= date_from_parsed)
    if date_to_parsed:
        # Include the entire end date
        date_to_end = date_to_parsed + timedelta(days=1)
        query = query.filter(Asset.upload_timestamp < date_to_end)

    # Size filter (in bytes)
    if size_min is not None:
        query = query.filter(Asset.file_size_bytes >= size_min * 1024 * 1024)  # Convert MB to bytes
    if size_max is not None:
        query = query.filter(Asset.file_size_bytes <= size_max * 1024 * 1024)

    return query


def apply_sorting(query, sort_by: str):
    """Apply sorting to query."""
    if sort_by in VALID_SORT_OPTIONS:
        field, direction = VALID_SORT_OPTIONS[sort_by]
        column = getattr(Asset, field)
        if direction == 'desc':
            query = query.order_by(desc(column))
        else:
            query = query.order_by(asc(column))
    else:
        # Default: newest first
        query = query.order_by(desc(Asset.upload_timestamp))
    return query


def paginate_query(query, page: int, per_page: int) -> Tuple[List[Asset], int, int]:
    """Paginate a query and return items, total count, and total pages."""
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total, total_pages


# HTML Template with all features
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Family Archive Vault - {{ page_title }}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --primary-color: #667eea;
            --primary-dark: #5a67d8;
            --secondary-color: #764ba2;
            --success-color: #48bb78;
            --danger-color: #f56565;
            --warning-color: #ed8936;
            --bg-color: #f7fafc;
            --card-bg: #ffffff;
            --text-color: #2d3748;
            --text-muted: #718096;
            --border-color: #e2e8f0;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
        }

        /* Navigation */
        .navbar {
            background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
            padding: 1rem 2rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .navbar-content {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .navbar h1 {
            color: white;
            font-size: 1.5rem;
            font-weight: 600;
        }

        .nav-links {
            display: flex;
            gap: 0.5rem;
        }

        .nav-link {
            color: rgba(255,255,255,0.9);
            text-decoration: none;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .nav-link:hover, .nav-link.active {
            background: rgba(255,255,255,0.2);
            color: white;
        }

        .nav-badge {
            background: rgba(255,255,255,0.3);
            padding: 0.15rem 0.5rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }

        /* Main container */
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Page header */
        .page-header {
            margin-bottom: 2rem;
        }

        .page-header h2 {
            font-size: 1.75rem;
            color: var(--text-color);
            margin-bottom: 0.5rem;
        }

        .page-header p {
            color: var(--text-muted);
        }

        /* Filters section */
        .filters-section {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .filters-row {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            align-items: flex-end;
        }

        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .filter-group label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .filter-group input,
        .filter-group select {
            padding: 0.5rem 0.75rem;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            font-size: 0.875rem;
            min-width: 150px;
            transition: border-color 0.2s;
        }

        .filter-group input:focus,
        .filter-group select:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .search-input {
            min-width: 250px !important;
        }

        /* Bulk actions */
        .bulk-actions {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem 1.5rem;
            background: #edf2f7;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            opacity: 0;
            transform: translateY(-10px);
            transition: all 0.3s;
            pointer-events: none;
        }

        .bulk-actions.visible {
            opacity: 1;
            transform: translateY(0);
            pointer-events: auto;
        }

        .bulk-actions .selected-count {
            font-weight: 600;
            color: var(--primary-color);
        }

        /* Buttons */
        .btn {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn-primary {
            background: var(--primary-color);
            color: white;
        }

        .btn-primary:hover {
            background: var(--primary-dark);
        }

        .btn-success {
            background: var(--success-color);
            color: white;
        }

        .btn-success:hover {
            background: #38a169;
        }

        .btn-danger {
            background: var(--danger-color);
            color: white;
        }

        .btn-danger:hover {
            background: #e53e3e;
        }

        .btn-outline {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-color);
        }

        .btn-outline:hover {
            background: #edf2f7;
        }

        .btn-sm {
            padding: 0.375rem 0.75rem;
            font-size: 0.75rem;
        }

        /* Media grid */
        .media-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        /* Media card */
        .media-card {
            background: var(--card-bg);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: all 0.3s;
            position: relative;
        }

        .media-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 24px rgba(0,0,0,0.15);
        }

        .media-card.selected {
            box-shadow: 0 0 0 3px var(--primary-color);
        }

        .media-card .checkbox-wrapper {
            position: absolute;
            top: 0.75rem;
            left: 0.75rem;
            z-index: 10;
        }

        .media-card .checkbox-wrapper input[type="checkbox"] {
            width: 20px;
            height: 20px;
            cursor: pointer;
            accent-color: var(--primary-color);
        }

        .media-thumbnail {
            width: 100%;
            height: 200px;
            object-fit: cover;
            background: #edf2f7;
        }

        .media-thumbnail.loading {
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
        }

        .media-info {
            padding: 1rem;
        }

        .media-filename {
            font-weight: 600;
            margin-bottom: 0.5rem;
            word-break: break-word;
            font-size: 0.875rem;
        }

        .media-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 1rem;
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .media-meta span {
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        .media-actions {
            display: flex;
            gap: 0.5rem;
        }

        .media-actions .btn {
            flex: 1;
        }

        /* Status badge */
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .status-pending {
            background: #fef3c7;
            color: #d97706;
        }

        .status-approved {
            background: #d1fae5;
            color: #059669;
        }

        .status-rejected {
            background: #fee2e2;
            color: #dc2626;
        }

        .status-archived {
            background: #dbeafe;
            color: #2563eb;
        }

        /* Pagination */
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0.5rem;
            margin-top: 2rem;
        }

        .pagination-info {
            margin-right: 1rem;
            color: var(--text-muted);
            font-size: 0.875rem;
        }

        .pagination a, .pagination span {
            padding: 0.5rem 0.75rem;
            border-radius: 6px;
            text-decoration: none;
            color: var(--text-color);
            border: 1px solid var(--border-color);
            transition: all 0.2s;
        }

        .pagination a:hover {
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }

        .pagination .active {
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }

        .pagination .disabled {
            opacity: 0.5;
            pointer-events: none;
        }

        /* Stats dashboard */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            text-align: center;
        }

        .stat-card h3 {
            font-size: 2rem;
            color: var(--primary-color);
            margin-bottom: 0.5rem;
        }

        .stat-card p {
            color: var(--text-muted);
            font-size: 0.875rem;
        }

        .stat-card.success h3 { color: var(--success-color); }
        .stat-card.warning h3 { color: var(--warning-color); }
        .stat-card.danger h3 { color: var(--danger-color); }

        /* Chart container */
        .chart-container {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }

        .chart-container h3 {
            margin-bottom: 1rem;
            font-size: 1.125rem;
        }

        .chart-wrapper {
            position: relative;
            height: 300px;
        }

        /* Toast notifications */
        .toast-container {
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .toast {
            padding: 1rem 1.5rem;
            border-radius: 8px;
            background: var(--card-bg);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            animation: slideIn 0.3s ease;
            min-width: 300px;
        }

        .toast.success {
            border-left: 4px solid var(--success-color);
        }

        .toast.error {
            border-left: 4px solid var(--danger-color);
        }

        .toast.info {
            border-left: 4px solid var(--primary-color);
        }

        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }

        /* Loading spinner */
        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid var(--border-color);
            border-top-color: var(--primary-color);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loading-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
        }

        .loading-overlay.visible {
            opacity: 1;
            pointer-events: auto;
        }

        .loading-overlay .spinner {
            width: 40px;
            height: 40px;
            border-width: 3px;
        }

        /* Keyboard shortcuts help */
        .keyboard-help {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: var(--card-bg);
            border-radius: 8px;
            padding: 0.5rem 1rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .keyboard-help kbd {
            background: #edf2f7;
            padding: 0.125rem 0.375rem;
            border-radius: 4px;
            font-family: monospace;
            margin: 0 0.25rem;
        }

        /* Empty state */
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
        }

        .empty-state svg {
            width: 64px;
            height: 64px;
            margin-bottom: 1rem;
            opacity: 0.5;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .navbar-content {
                flex-direction: column;
                gap: 1rem;
            }

            .nav-links {
                flex-wrap: wrap;
                justify-content: center;
            }

            .filters-row {
                flex-direction: column;
            }

            .filter-group input,
            .filter-group select {
                width: 100%;
            }

            .media-grid {
                grid-template-columns: 1fr;
            }
        }

        /* View modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
        }

        .modal-overlay.visible {
            opacity: 1;
            pointer-events: auto;
        }

        .modal-content {
            background: var(--card-bg);
            border-radius: 12px;
            max-width: 90vw;
            max-height: 90vh;
            overflow: auto;
            position: relative;
        }

        .modal-close {
            position: absolute;
            top: 1rem;
            right: 1rem;
            background: rgba(0,0,0,0.5);
            color: white;
            border: none;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 1.25rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .modal-image {
            max-width: 100%;
            max-height: 80vh;
            display: block;
        }
    </style>
</head>
<body>
    <!-- Navigation -->
    <nav class="navbar">
        <div class="navbar-content">
            <h1>Family Archive Vault</h1>
            <div class="nav-links">
                <a href="{{ url_for('dashboard') }}" class="nav-link {% if active_nav == 'dashboard' %}active{% endif %}">
                    Dashboard
                </a>
                <a href="{{ url_for('pending') }}" class="nav-link {% if active_nav == 'pending' %}active{% endif %}">
                    Pending Review
                    <span class="nav-badge">{{ status_counts.get('pending', 0) }}</span>
                </a>
                <a href="{{ url_for('approved') }}" class="nav-link {% if active_nav == 'approved' %}active{% endif %}">
                    Approved
                    <span class="nav-badge">{{ status_counts.get('approved', 0) }}</span>
                </a>
                <a href="{{ url_for('rejected') }}" class="nav-link {% if active_nav == 'rejected' %}active{% endif %}">
                    Rejected
                    <span class="nav-badge">{{ status_counts.get('rejected', 0) }}</span>
                </a>
            </div>
        </div>
    </nav>

    <!-- Toast container -->
    <div class="toast-container" id="toastContainer"></div>

    <!-- Loading overlay -->
    <div class="loading-overlay" id="loadingOverlay">
        <div class="spinner"></div>
    </div>

    <!-- Main content -->
    <div class="container">
        {% block content %}{% endblock %}
    </div>

    <!-- Keyboard shortcuts help (shown on pending page) -->
    {% if active_nav == 'pending' %}
    <div class="keyboard-help">
        Shortcuts: <kbd>A</kbd> Approve first | <kbd>R</kbd> Reject first | <kbd>Esc</kbd> Deselect all
    </div>
    {% endif %}

    <!-- View modal -->
    <div class="modal-overlay" id="viewModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <img class="modal-image" id="modalImage" src="" alt="Full size view">
        </div>
    </div>

    <script>
        // Toast notification system
        function showToast(message, type = 'info') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `
                <span>${type === 'success' ? '&#10004;' : type === 'error' ? '&#10006;' : '&#8505;'}</span>
                <span>${message}</span>
            `;
            container.appendChild(toast);

            setTimeout(() => {
                toast.style.animation = 'slideOut 0.3s ease forwards';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // Loading overlay
        function showLoading() {
            document.getElementById('loadingOverlay').classList.add('visible');
        }

        function hideLoading() {
            document.getElementById('loadingOverlay').classList.remove('visible');
        }

        // Modal functions
        function openModal(imageUrl) {
            document.getElementById('modalImage').src = imageUrl;
            document.getElementById('viewModal').classList.add('visible');
        }

        function closeModal() {
            document.getElementById('viewModal').classList.remove('visible');
        }

        // Close modal on escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeModal();
                deselectAll();
            }
        });

        // Click outside modal to close
        document.getElementById('viewModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });

        // Bulk selection management
        let selectedItems = new Set();

        function updateBulkActions() {
            const bulkActions = document.getElementById('bulkActions');
            const selectedCount = document.getElementById('selectedCount');

            if (bulkActions) {
                if (selectedItems.size > 0) {
                    bulkActions.classList.add('visible');
                    selectedCount.textContent = selectedItems.size;
                } else {
                    bulkActions.classList.remove('visible');
                }
            }
        }

        function toggleSelection(driveId, checkbox) {
            const card = checkbox.closest('.media-card');
            if (checkbox.checked) {
                selectedItems.add(driveId);
                card.classList.add('selected');
            } else {
                selectedItems.delete(driveId);
                card.classList.remove('selected');
            }
            updateBulkActions();
        }

        function selectAll() {
            document.querySelectorAll('.media-card .checkbox-wrapper input[type="checkbox"]').forEach(cb => {
                cb.checked = true;
                const driveId = cb.dataset.driveId;
                selectedItems.add(driveId);
                cb.closest('.media-card').classList.add('selected');
            });
            updateBulkActions();
        }

        function deselectAll() {
            document.querySelectorAll('.media-card .checkbox-wrapper input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
                cb.closest('.media-card').classList.remove('selected');
            });
            selectedItems.clear();
            updateBulkActions();
        }

        // API functions
        async function approveItem(driveId) {
            showLoading();
            try {
                const response = await fetch(`/api/approve/${driveId}`, { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showToast('Item approved successfully', 'success');
                    setTimeout(() => location.reload(), 500);
                } else {
                    showToast(data.error || 'Failed to approve item', 'error');
                }
            } catch (error) {
                showToast('Error approving item', 'error');
            }
            hideLoading();
        }

        async function rejectItem(driveId) {
            showLoading();
            try {
                const response = await fetch(`/api/reject/${driveId}`, { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showToast('Item rejected successfully', 'success');
                    setTimeout(() => location.reload(), 500);
                } else {
                    showToast(data.error || 'Failed to reject item', 'error');
                }
            } catch (error) {
                showToast('Error rejecting item', 'error');
            }
            hideLoading();
        }

        async function bulkApprove() {
            if (selectedItems.size === 0) return;

            if (!confirm(`Are you sure you want to approve ${selectedItems.size} item(s)?`)) {
                return;
            }

            showLoading();
            try {
                const response = await fetch('/api/bulk_approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ drive_ids: Array.from(selectedItems) })
                });
                const data = await response.json();
                if (data.success) {
                    showToast(`${data.approved_count} item(s) approved successfully`, 'success');
                    setTimeout(() => location.reload(), 500);
                } else {
                    showToast(data.error || 'Failed to approve items', 'error');
                }
            } catch (error) {
                showToast('Error approving items', 'error');
            }
            hideLoading();
        }

        async function bulkReject() {
            if (selectedItems.size === 0) return;

            if (!confirm(`Are you sure you want to reject ${selectedItems.size} item(s)?`)) {
                return;
            }

            showLoading();
            try {
                const response = await fetch('/api/bulk_reject', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ drive_ids: Array.from(selectedItems) })
                });
                const data = await response.json();
                if (data.success) {
                    showToast(`${data.rejected_count} item(s) rejected successfully`, 'success');
                    setTimeout(() => location.reload(), 500);
                } else {
                    showToast(data.error || 'Failed to reject items', 'error');
                }
            } catch (error) {
                showToast('Error rejecting items', 'error');
            }
            hideLoading();
        }

        // Keyboard shortcuts for pending page
        document.addEventListener('keydown', function(e) {
            // Only on pending page, when not in input/textarea
            if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
                return;
            }

            const firstCard = document.querySelector('.media-card');
            if (!firstCard) return;

            const driveId = firstCard.querySelector('input[type="checkbox"]')?.dataset.driveId;
            if (!driveId) return;

            if (e.key === 'a' || e.key === 'A') {
                e.preventDefault();
                approveItem(driveId);
            } else if (e.key === 'r' || e.key === 'R') {
                e.preventDefault();
                rejectItem(driveId);
            }
        });

        // Filter form handling with debounce
        let filterTimeout;
        function applyFilters() {
            clearTimeout(filterTimeout);
            filterTimeout = setTimeout(() => {
                document.getElementById('filterForm').submit();
            }, 300);
        }

        // Sort preference storage
        function saveSortPreference(sort) {
            const page = '{{ active_nav }}';
            localStorage.setItem(`sort_${page}`, sort);
        }

        // Load saved sort preference on page load
        document.addEventListener('DOMContentLoaded', function() {
            const sortSelect = document.getElementById('sortSelect');
            if (sortSelect) {
                const page = '{{ active_nav }}';
                const savedSort = localStorage.getItem(`sort_${page}`);
                if (savedSort && !new URLSearchParams(window.location.search).get('sort')) {
                    // Only apply if not already in URL
                    // sortSelect.value = savedSort;
                }
            }
        });

        // Real-time client-side filtering
        function clientSideFilter() {
            const searchInput = document.getElementById('searchInput');
            const searchTerm = searchInput?.value.toLowerCase() || '';

            document.querySelectorAll('.media-card').forEach(card => {
                const filename = card.querySelector('.media-filename')?.textContent.toLowerCase() || '';
                const visible = filename.includes(searchTerm);
                card.style.display = visible ? '' : 'none';
            });
        }
    </script>

    {% block extra_scripts %}{% endblock %}
</body>
</html>
'''

# Dashboard page template
DASHBOARD_PAGE_TEMPLATE = '''
{% extends "base" %}
{% block content %}
<div class="page-header">
    <h2>Dashboard</h2>
    <p>Overview of your family archive</p>
</div>

<!-- Stats grid -->
<div class="stats-grid">
    <div class="stat-card">
        <h3>{{ status_counts.total }}</h3>
        <p>Total Items</p>
    </div>
    <div class="stat-card warning">
        <h3>{{ status_counts.pending }}</h3>
        <p>Pending Review</p>
    </div>
    <div class="stat-card success">
        <h3>{{ status_counts.approved }}</h3>
        <p>Approved</p>
    </div>
    <div class="stat-card danger">
        <h3>{{ status_counts.rejected }}</h3>
        <p>Rejected</p>
    </div>
    <div class="stat-card">
        <h3>{{ reviewed_today }}</h3>
        <p>Reviewed Today</p>
    </div>
    <div class="stat-card">
        <h3>{{ reviewed_this_week }}</h3>
        <p>Reviewed This Week</p>
    </div>
</div>

{% if local_sync_status %}
<!-- Local Sync Status -->
<div class="chart-container" style="margin-bottom: 2rem;">
    <h3>Local Folder Sync</h3>
    <div class="stats-grid" style="margin-top: 1rem;">
        <div class="stat-card">
            <h3>{{ local_sync_status.pending_files }}</h3>
            <p>Pending Files</p>
        </div>
        <div class="stat-card">
            <h3>{{ local_sync_status.pending_size_mb }} MB</h3>
            <p>Pending Size</p>
        </div>
        <div class="stat-card success">
            <h3>{{ local_sync_status.processed_count }}</h3>
            <p>Processed</p>
        </div>
    </div>
    <p style="margin-top: 1rem; color: var(--text-muted); font-size: 0.875rem;">
        Syncing from: <code>{{ local_sync_status.sync_folder }}</code>
    </p>
</div>
{% endif %}

<!-- Chart -->
<div class="chart-container">
    <h3>Items by Status</h3>
    <div class="chart-wrapper">
        <canvas id="statusChart"></canvas>
    </div>
</div>

<!-- Recent items -->
<div class="chart-container">
    <h3>Recently Uploaded</h3>
    {% if recent_items %}
    <div class="media-grid">
        {% for item in recent_items %}
        <div class="media-card">
            <img class="media-thumbnail"
                 src="{{ url_for('get_thumbnail', drive_id=item.drive_file_id) }}"
                 alt="{{ item.original_filename }}"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>&#128247;</text></svg>'">
            <div class="media-info">
                <div class="media-filename">{{ item.original_filename }}</div>
                <div class="media-meta">
                    <span>{{ (item.file_size_bytes / 1024 / 1024)|round(2) }} MB</span>
                    <span>{{ item.upload_timestamp.strftime('%Y-%m-%d') if item.upload_timestamp else 'N/A' }}</span>
                    <span class="status-badge status-{{ item.status }}">{{ item.status }}</span>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="empty-state">
        <p>No items uploaded yet</p>
    </div>
    {% endif %}
</div>

{% endblock %}

{% block extra_scripts %}
<script>
    // Status chart
    const ctx = document.getElementById('statusChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Pending', 'Approved', 'Rejected', 'Archived'],
            datasets: [{
                data: [
                    {{ status_counts.pending }},
                    {{ status_counts.approved }},
                    {{ status_counts.rejected }},
                    {{ status_counts.get('archived', 0) }}
                ],
                backgroundColor: [
                    '#ed8936',
                    '#48bb78',
                    '#f56565',
                    '#667eea'
                ],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
</script>
{% endblock %}
'''

# List page template (for pending, approved, rejected)
LIST_PAGE_TEMPLATE = '''
{% extends "base" %}
{% block content %}
<div class="page-header">
    <h2>{{ page_title }}</h2>
    <p>{{ page_description }}</p>
</div>

<!-- Filters section -->
<div class="filters-section">
    <form id="filterForm" method="GET" action="">
        <div class="filters-row">
            <div class="filter-group">
                <label>Search</label>
                <input type="text" name="search" id="searchInput" class="search-input"
                       value="{{ request.args.get('search', '') }}"
                       placeholder="Search by filename..."
                       onkeyup="clientSideFilter()">
            </div>
            <div class="filter-group">
                <label>Date From</label>
                <input type="date" name="date_from" value="{{ request.args.get('date_from', '') }}">
            </div>
            <div class="filter-group">
                <label>Date To</label>
                <input type="date" name="date_to" value="{{ request.args.get('date_to', '') }}">
            </div>
            <div class="filter-group">
                <label>Min Size (MB)</label>
                <input type="number" name="size_min" value="{{ request.args.get('size_min', '') }}"
                       min="0" step="0.1" placeholder="0">
            </div>
            <div class="filter-group">
                <label>Max Size (MB)</label>
                <input type="number" name="size_max" value="{{ request.args.get('size_max', '') }}"
                       min="0" step="0.1" placeholder="1000">
            </div>
            <div class="filter-group">
                <label>Sort By</label>
                <select name="sort" id="sortSelect" onchange="saveSortPreference(this.value); this.form.submit()">
                    <option value="newest" {% if request.args.get('sort', 'newest') == 'newest' %}selected{% endif %}>Newest First</option>
                    <option value="oldest" {% if request.args.get('sort') == 'oldest' %}selected{% endif %}>Oldest First</option>
                    <option value="filename_asc" {% if request.args.get('sort') == 'filename_asc' %}selected{% endif %}>Filename A-Z</option>
                    <option value="filename_desc" {% if request.args.get('sort') == 'filename_desc' %}selected{% endif %}>Filename Z-A</option>
                    <option value="largest" {% if request.args.get('sort') == 'largest' %}selected{% endif %}>Largest First</option>
                    <option value="smallest" {% if request.args.get('sort') == 'smallest' %}selected{% endif %}>Smallest First</option>
                </select>
            </div>
            <div class="filter-group">
                <label>&nbsp;</label>
                <button type="submit" class="btn btn-primary">Apply Filters</button>
            </div>
            <div class="filter-group">
                <label>&nbsp;</label>
                <a href="{{ request.path }}" class="btn btn-outline">Clear</a>
            </div>
        </div>
    </form>
</div>

<!-- Bulk actions (for pending page) -->
{% if show_bulk_actions %}
<div class="bulk-actions" id="bulkActions">
    <span class="selected-count" id="selectedCount">0</span> items selected
    <button class="btn btn-outline btn-sm" onclick="selectAll()">Select All</button>
    <button class="btn btn-outline btn-sm" onclick="deselectAll()">Deselect All</button>
    <button class="btn btn-success btn-sm" onclick="bulkApprove()">Approve Selected</button>
    <button class="btn btn-danger btn-sm" onclick="bulkReject()">Reject Selected</button>
</div>
{% endif %}

<!-- Media grid -->
{% if items %}
<div class="media-grid">
    {% for item in items %}
    <div class="media-card">
        {% if show_bulk_actions %}
        <div class="checkbox-wrapper">
            <input type="checkbox" data-drive-id="{{ item.drive_file_id }}"
                   onchange="toggleSelection('{{ item.drive_file_id }}', this)">
        </div>
        {% endif %}
        <img class="media-thumbnail"
             src="{{ url_for('get_thumbnail', drive_id=item.drive_file_id) }}"
             alt="{{ item.original_filename }}"
             onclick="openModal('{{ url_for('get_thumbnail', drive_id=item.drive_file_id) }}')"
             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>&#128247;</text></svg>'">
        <div class="media-info">
            <div class="media-filename">{{ item.original_filename }}</div>
            <div class="media-meta">
                <span>{{ (item.file_size_bytes / 1024 / 1024)|round(2) if item.file_size_bytes else 0 }} MB</span>
                <span>{{ item.upload_timestamp.strftime('%Y-%m-%d') if item.upload_timestamp else 'N/A' }}</span>
                <span class="status-badge status-{{ 'pending' if item.status == 'needs_review' else item.status }}">
                    {{ 'pending' if item.status == 'needs_review' else item.status }}
                </span>
            </div>
            <div class="media-actions">
                {% if item.status == 'needs_review' %}
                <button class="btn btn-success btn-sm" onclick="approveItem('{{ item.drive_file_id }}')">Approve</button>
                <button class="btn btn-danger btn-sm" onclick="rejectItem('{{ item.drive_file_id }}')">Reject</button>
                {% elif item.status == 'error' %}
                <button class="btn btn-success btn-sm" onclick="approveItem('{{ item.drive_file_id }}')">Restore</button>
                {% else %}
                <a href="{{ url_for('view_item', drive_id=item.drive_file_id) }}" class="btn btn-outline btn-sm">View</a>
                {% endif %}
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<!-- Pagination -->
{% if total_pages > 1 %}
<div class="pagination">
    <span class="pagination-info">
        Showing {{ ((current_page - 1) * items_per_page) + 1 }}-{{ min(current_page * items_per_page, total_items) }} of {{ total_items }} items
    </span>

    {% if current_page > 1 %}
    <a href="{{ url_for(request.endpoint, page=current_page - 1, **request.args.to_dict(flat=True)) }}">Previous</a>
    {% else %}
    <span class="disabled">Previous</span>
    {% endif %}

    {% for page_num in range(1, total_pages + 1) %}
        {% if page_num == current_page %}
        <span class="active">{{ page_num }}</span>
        {% elif page_num == 1 or page_num == total_pages or (page_num >= current_page - 2 and page_num <= current_page + 2) %}
        <a href="{{ url_for(request.endpoint, page=page_num, **request.args.to_dict(flat=True)) }}">{{ page_num }}</a>
        {% elif page_num == current_page - 3 or page_num == current_page + 3 %}
        <span>...</span>
        {% endif %}
    {% endfor %}

    {% if current_page < total_pages %}
    <a href="{{ url_for(request.endpoint, page=current_page + 1, **request.args.to_dict(flat=True)) }}">Next</a>
    {% else %}
    <span class="disabled">Next</span>
    {% endif %}
</div>
{% endif %}

{% else %}
<div class="empty-state">
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
    <h3>No items found</h3>
    <p>{% if request.args.get('search') %}Try adjusting your search criteria{% else %}No items in this category yet{% endif %}</p>
</div>
{% endif %}
{% endblock %}
'''

# View item page template
VIEW_PAGE_TEMPLATE = '''
{% extends "base" %}
{% block content %}
<div class="page-header">
    <h2>{{ item.original_filename }}</h2>
    <p>Viewing item details</p>
</div>

<div class="chart-container">
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem;">
        <div>
            <img src="{{ url_for('get_thumbnail', drive_id=item.drive_file_id) }}"
                 style="width: 100%; border-radius: 8px;"
                 alt="{{ item.original_filename }}"
                 onclick="openModal('{{ url_for('get_thumbnail', drive_id=item.drive_file_id) }}')">
        </div>
        <div>
            <h3 style="margin-bottom: 1rem;">Item Details</h3>
            <table style="width: 100%;">
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Filename</td>
                    <td style="padding: 0.5rem 0;">{{ item.original_filename }}</td>
                </tr>
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Status</td>
                    <td style="padding: 0.5rem 0;">
                        <span class="status-badge status-{{ 'pending' if item.status == 'needs_review' else item.status }}">
                            {{ 'pending' if item.status == 'needs_review' else item.status }}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Size</td>
                    <td style="padding: 0.5rem 0;">{{ (item.file_size_bytes / 1024 / 1024)|round(2) if item.file_size_bytes else 0 }} MB</td>
                </tr>
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Type</td>
                    <td style="padding: 0.5rem 0;">{{ item.asset_type or 'Unknown' }}</td>
                </tr>
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Uploaded</td>
                    <td style="padding: 0.5rem 0;">{{ item.upload_timestamp.strftime('%Y-%m-%d %H:%M') if item.upload_timestamp else 'N/A' }}</td>
                </tr>
                {% if item.approved_at %}
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Reviewed</td>
                    <td style="padding: 0.5rem 0;">{{ item.approved_at.strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% endif %}
                {% if item.decade %}
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">Decade</td>
                    <td style="padding: 0.5rem 0;">{{ item.decade }}s</td>
                </tr>
                {% endif %}
                {% if item.caption %}
                <tr>
                    <td style="padding: 0.5rem 0; color: var(--text-muted);">AI Caption</td>
                    <td style="padding: 0.5rem 0;">{{ item.caption }}</td>
                </tr>
                {% endif %}
            </table>

            <div style="margin-top: 2rem;">
                {% if item.status == 'needs_review' %}
                <button class="btn btn-success" onclick="approveItem('{{ item.drive_file_id }}')">Approve</button>
                <button class="btn btn-danger" onclick="rejectItem('{{ item.drive_file_id }}')">Reject</button>
                {% endif %}
                <a href="javascript:history.back()" class="btn btn-outline">Back</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''


def render_with_base(template_content: str, **kwargs):
    """Render a template that extends the base template."""
    # Combine base template with page template
    full_template = DASHBOARD_TEMPLATE.replace(
        '{% block content %}{% endblock %}',
        template_content.replace('{% extends "base" %}', '').replace('{% block content %}', '').replace('{% endblock %}', '', 1)
    )

    # Handle extra_scripts block
    if '{% block extra_scripts %}' in template_content:
        scripts_start = template_content.find('{% block extra_scripts %}') + len('{% block extra_scripts %}')
        scripts_end = template_content.rfind('{% endblock %}')
        extra_scripts = template_content[scripts_start:scripts_end]
        full_template = full_template.replace(
            '{% block extra_scripts %}{% endblock %}',
            extra_scripts
        )
    else:
        full_template = full_template.replace('{% block extra_scripts %}{% endblock %}', '')

    return render_template_string(full_template, **kwargs)


# Routes
@app.route('/')
def dashboard():
    """Dashboard home page with statistics."""
    db = get_db()
    session = db.get_session()

    try:
        status_counts = get_status_counts(session)

        # Get counts for reviewed today and this week
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)

        reviewed_today = session.query(Asset).filter(
            Asset.approved_at >= today
        ).count()

        reviewed_this_week = session.query(Asset).filter(
            Asset.approved_at >= week_ago
        ).count()

        # Get recent items
        recent_items = session.query(Asset).order_by(
            desc(Asset.upload_timestamp)
        ).limit(8).all()

        # Convert to dictionaries to avoid session issues
        recent_items_data = []
        for item in recent_items:
            recent_items_data.append({
                'drive_file_id': item.drive_file_id,
                'original_filename': item.original_filename,
                'file_size_bytes': item.file_size_bytes,
                'upload_timestamp': item.upload_timestamp,
                'status': item.status,
            })

        # Get local sync status
        local_sync_status = get_local_sync_status()

        return render_with_base(
            DASHBOARD_PAGE_TEMPLATE,
            page_title='Dashboard',
            active_nav='dashboard',
            status_counts=status_counts,
            reviewed_today=reviewed_today,
            reviewed_this_week=reviewed_this_week,
            recent_items=recent_items_data,
            local_sync_status=local_sync_status,
        )
    finally:
        session.close()


@app.route('/pending')
def pending():
    """Pending review page."""
    return render_list_page('pending', 'Pending Review', 'Items awaiting your review', show_bulk_actions=True)


@app.route('/approved')
def approved():
    """Approved items page."""
    return render_list_page('approved', 'Approved Items', 'Items that have been approved')


@app.route('/rejected')
def rejected():
    """Rejected items page."""
    return render_list_page('rejected', 'Rejected Items', 'Items that have been rejected')


def render_list_page(status: str, title: str, description: str, show_bulk_actions: bool = False):
    """Render a list page with filtering and pagination."""
    db = get_db()
    session = db.get_session()

    try:
        status_counts = get_status_counts(session)

        # Get filter parameters
        page = request.args.get('page', 1, type=int)
        search = request.args.get('search', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        size_min = request.args.get('size_min', type=float)
        size_max = request.args.get('size_max', type=float)
        sort_by = request.args.get('sort', 'newest')

        # Build query
        query = build_query_filters(
            session,
            status=status,
            search=search,
            date_from=date_from,
            date_to=date_to,
            size_min=size_min,
            size_max=size_max,
        )

        # Apply sorting
        query = apply_sorting(query, sort_by)

        # Paginate
        items, total_items, total_pages = paginate_query(query, page, ITEMS_PER_PAGE)

        # Convert to dictionaries to avoid session issues
        items_data = []
        for item in items:
            items_data.append({
                'drive_file_id': item.drive_file_id,
                'original_filename': item.original_filename,
                'file_size_bytes': item.file_size_bytes,
                'upload_timestamp': item.upload_timestamp,
                'status': item.status,
                'approved_at': item.approved_at,
            })

        return render_with_base(
            LIST_PAGE_TEMPLATE,
            page_title=title,
            page_description=description,
            active_nav=status,
            status_counts=status_counts,
            items=items_data,
            current_page=page,
            total_pages=total_pages,
            total_items=total_items,
            items_per_page=ITEMS_PER_PAGE,
            show_bulk_actions=show_bulk_actions,
        )
    finally:
        session.close()


@app.route('/view/<drive_id>')
def view_item(drive_id: str):
    """View a single item."""
    db = get_db()
    session = db.get_session()

    try:
        status_counts = get_status_counts(session)
        item = session.query(Asset).filter_by(drive_file_id=drive_id).first()

        if not item:
            abort(404)

        # Convert to dictionary
        item_data = {
            'drive_file_id': item.drive_file_id,
            'original_filename': item.original_filename,
            'file_size_bytes': item.file_size_bytes,
            'upload_timestamp': item.upload_timestamp,
            'status': item.status,
            'approved_at': item.approved_at,
            'asset_type': item.asset_type,
            'decade': item.decade,
            'caption': item.caption,
        }

        return render_with_base(
            VIEW_PAGE_TEMPLATE,
            page_title=item.original_filename,
            active_nav='',
            status_counts=status_counts,
            item=item_data,
        )
    finally:
        session.close()


@app.route('/thumbnail/<drive_id>')
def get_thumbnail(drive_id: str):
    """Get thumbnail for an item."""
    db = get_db()
    session = db.get_session()

    try:
        item = session.query(Asset).filter_by(drive_file_id=drive_id).first()

        if not item:
            abort(404)

        # Check for local thumbnail
        if item.thumbnail_path and Path(item.thumbnail_path).exists():
            return send_file(item.thumbnail_path)

        # Try to download from Drive
        settings = get_settings()
        drive = DriveClient(
            settings.service_account_json_path,
            settings.drive_root_folder_id
        )

        # Create cache directory if needed
        cache_dir = Path(settings.local_cache) / 'thumbnails'
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_path = cache_dir / f"{drive_id}.jpg"

        if cache_path.exists():
            return send_file(str(cache_path))

        # Download the file or thumbnail from Drive
        if drive.download_file(drive_id, cache_path):
            return send_file(str(cache_path))

        # Return a placeholder image
        abort(404)

    finally:
        session.close()


# API Endpoints
@app.route('/api/approve/<drive_id>', methods=['POST'])
def api_approve(drive_id: str):
    """Approve a single item."""
    db = get_db()
    session = db.get_session()

    try:
        item = session.query(Asset).filter_by(drive_file_id=drive_id).first()

        if not item:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        item.status = 'approved'
        item.approved_at = datetime.utcnow()
        item.approved_by = 'dashboard_user'

        # Log the review action
        review = Review(
            asset_id=item.asset_id,
            action='approve',
            reviewer='dashboard_user',
            changes={'status': 'approved'}
        )
        session.add(review)
        session.commit()

        return jsonify({'success': True, 'message': 'Item approved'})

    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/reject/<drive_id>', methods=['POST'])
def api_reject(drive_id: str):
    """Reject a single item."""
    db = get_db()
    session = db.get_session()

    try:
        item = session.query(Asset).filter_by(drive_file_id=drive_id).first()

        if not item:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        item.status = 'error'  # Using 'error' as rejected status
        item.approved_at = datetime.utcnow()

        # Log the review action
        review = Review(
            asset_id=item.asset_id,
            action='reject',
            reviewer='dashboard_user',
            changes={'status': 'error'}
        )
        session.add(review)
        session.commit()

        return jsonify({'success': True, 'message': 'Item rejected'})

    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/bulk_approve', methods=['POST'])
def api_bulk_approve():
    """Approve multiple items."""
    db = get_db()
    session = db.get_session()

    try:
        data = request.get_json()
        drive_ids = data.get('drive_ids', [])

        if not drive_ids:
            return jsonify({'success': False, 'error': 'No items specified'}), 400

        approved_count = 0
        for drive_id in drive_ids:
            item = session.query(Asset).filter_by(drive_file_id=drive_id).first()
            if item and item.status == 'needs_review':
                item.status = 'approved'
                item.approved_at = datetime.utcnow()
                item.approved_by = 'dashboard_user'

                review = Review(
                    asset_id=item.asset_id,
                    action='approve',
                    reviewer='dashboard_user',
                    changes={'status': 'approved', 'bulk': True}
                )
                session.add(review)
                approved_count += 1

        session.commit()

        return jsonify({
            'success': True,
            'approved_count': approved_count,
            'message': f'{approved_count} item(s) approved'
        })

    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/bulk_reject', methods=['POST'])
def api_bulk_reject():
    """Reject multiple items."""
    db = get_db()
    session = db.get_session()

    try:
        data = request.get_json()
        drive_ids = data.get('drive_ids', [])

        if not drive_ids:
            return jsonify({'success': False, 'error': 'No items specified'}), 400

        rejected_count = 0
        for drive_id in drive_ids:
            item = session.query(Asset).filter_by(drive_file_id=drive_id).first()
            if item and item.status == 'needs_review':
                item.status = 'error'
                item.approved_at = datetime.utcnow()

                review = Review(
                    asset_id=item.asset_id,
                    action='reject',
                    reviewer='dashboard_user',
                    changes={'status': 'error', 'bulk': True}
                )
                session.add(review)
                rejected_count += 1

        session.commit()

        return jsonify({
            'success': True,
            'rejected_count': rejected_count,
            'message': f'{rejected_count} item(s) rejected'
        })

    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/stats')
def api_stats():
    """Get statistics for the dashboard."""
    db = get_db()
    session = db.get_session()

    try:
        status_counts = get_status_counts(session)

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)

        reviewed_today = session.query(Asset).filter(
            Asset.approved_at >= today
        ).count()

        reviewed_this_week = session.query(Asset).filter(
            Asset.approved_at >= week_ago
        ).count()

        # Include local sync status
        local_sync = get_local_sync_status()

        return jsonify({
            'success': True,
            'counts': status_counts,
            'reviewed_today': reviewed_today,
            'reviewed_this_week': reviewed_this_week,
            'local_sync': local_sync,
        })

    finally:
        session.close()


@app.route('/api/local_sync_status')
def api_local_sync_status():
    """Get local folder sync status."""
    status = get_local_sync_status()
    if status:
        return jsonify({'success': True, **status})
    return jsonify({'success': True, 'is_enabled': False, 'message': 'Local folder sync is not enabled'})


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    db = get_db()
    session = db.get_session()
    try:
        status_counts = get_status_counts(session)
        return render_with_base(
            '''
            <div class="empty-state">
                <h2>404 - Not Found</h2>
                <p>The page or item you're looking for doesn't exist.</p>
                <a href="{{ url_for('dashboard') }}" class="btn btn-primary">Back to Dashboard</a>
            </div>
            ''',
            page_title='Not Found',
            active_nav='',
            status_counts=status_counts,
        ), 404
    finally:
        session.close()


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


if __name__ == '__main__':
    # Ensure settings are loaded
    settings = get_settings()
    settings.ensure_local_dirs()

    # Initialize database
    db = get_db()
    db.init_db()

    print("Starting Family Archive Vault Dashboard...")
    print(f"Database: {settings.local_db_path}")
    print(f"Visit: http://localhost:5000")

    app.run(debug=True, host='0.0.0.0', port=5000)
