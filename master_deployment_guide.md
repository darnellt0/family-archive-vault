# Master Deployment Guide: Family Archive Vault (v8)

This guide consolidates all files and provides a clear, sequential plan to synchronize your local project environment with the latest development state (v8).

## 1. File Synchronization

Please ensure all the attached files are placed in the correct locations within your `F:\FamilyArchive` project folder.

| File Name | Target Location | Purpose |
| :--- | :--- | :--- |
| `dashboard_v8_final.py` | `F:\FamilyArchive\` | **Main Application**: The latest Flask dashboard script. |
| `fix_schema.py` | `F:\FamilyArchive\` | **Utility**: Ensures all necessary database columns exist. |
| `phash_worker.py` | `F:\FamilyArchive\` | **Worker**: Generates perceptual hashes for duplicate detection. |
| `clip_worker.py` | `F:\FamilyArchive\` | **Worker**: Generates image embeddings for semantic search. |
| `whisper_worker.py` | `F:\FamilyArchive\` | **Worker**: Transcribes video files. |
| `semantic_search.py` | `F:\FamilyArchive\` | **Module**: Logic for vector-based search. |
| `duplicate_detection.py` | `F:\FamilyArchive\` | **Module**: Logic for pHash-based duplicate grouping. |
| `sharing.py` | `F:\FamilyArchive\` | **Module**: Logic for secure share link generation and verification. |
| `tailwind.config.js` | `F:\FamilyArchive\` | **Config**: Tailwind CSS configuration file. |
| `input.css` | `F:\FamilyArchive\static\src\` | **CSS**: Tailwind input file (create `static/src` if it doesn't exist). |
| `base.html` | `F:\FamilyArchive\templates\` | **Template**: Base template for all pages (create `templates` if it doesn't exist). |
| `dashboard_tailwind.html` | `F:\FamilyArchive\templates\` | **Template**: Tailwind-styled dashboard view. |
| `gallery_tailwind.html` | `F:\FamilyArchive\templates\` | **Template**: Tailwind-styled gallery view. |
| `sharing.html` | `F:\FamilyArchive\templates\` | **Template**: Sharing management view. |
| `duplicates.html` | `F:\FamilyArchive\templates\` | **Template**: Duplicate review view. |

## 2. Step-by-Step Deployment Plan

Follow these steps sequentially to ensure a clean and successful deployment.

### Step 2.1: Environment Setup

1.  **Install Dependencies**: Run the following command in your terminal to ensure all required Python packages are installed:
    ```bash
    pip install Flask google-api-python-client Pillow imagehash sentence-transformers faster-whisper torch numpy
    ```
2.  **Download Tailwind CLI**: Download the `tailwindcss-windows-x64.exe` and place it in `F:\FamilyArchive\tools\tailwindcss.exe`.
3.  **Database Schema Fix**: Run the schema fix utility to ensure all necessary columns are present:
    ```bash
    python fix_schema.py
    ```

### Step 2.2: Tailwind CSS Compilation

1.  **Compile CSS**: Run the Tailwind CLI to generate the final CSS file. This command should be run from your project root (`F:\FamilyArchive`):
    ```bash
    .\tools\tailwindcss.exe -i .\static\src\input.css -o .\static\dist\output.css
    ```
    *   *Note: This command will create the `static/dist` folder and the `output.css` file.*

### Step 2.3: Worker Initialization

1.  **Initialize Sharing Table**: Run the sharing module once to create the necessary database table:
    ```bash
    python sharing.py
    ```
2.  **Run Workers (Optional but Recommended)**: Run the workers to populate the database with advanced metadata.
    ```bash
    python phash_worker.py
    python clip_worker.py
    python whisper_worker.py
    ```

### Step 2.4: Launch Application

1.  **Start the Dashboard**: Launch the final application:
    ```bash
    python dashboard_v8_final.py
    ```

The application should now be accessible in your browser, featuring the new Tailwind CSS design and the **Sharing** and **Duplicates** management pages.
