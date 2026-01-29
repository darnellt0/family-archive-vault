# --- Family Archive Frontend Setup Script ---

# 1. Check for Node.js
if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Node.js is not installed. Please install it from [https://nodejs.org/](https://nodejs.org/)" -ForegroundColor Red
    Read-Host -Prompt "Press Enter to exit"
    exit
}

Write-Host "--- Setting up Family Archive Frontend ---" -ForegroundColor Cyan

# 2. Create React App with Vite
# This creates a folder named 'frontend'
# NOTE: If the script pauses and asks you to select a framework:
# 1. Select "React" using arrow keys and Enter.
# 2. Select "JavaScript" (Yellow/Blue option).
npm create vite@latest frontend -- --template react
Set-Location frontend

# 3. Install Dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
npm install
npm install lucide-react tailwindcss postcss autoprefixer

# 4. Initialize Tailwind
npx tailwindcss init -p

# 5. Configure Tailwind (Overwrite tailwind.config.js)
$tailwindConfig = @"
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
"@
Set-Content tailwind.config.js $tailwindConfig

# 6. Configure Global CSS (Overwrite src/index.css)
$cssContent = @"
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
    background-color: #0f172a; /* slate-900 */
    color: white;
}
"@
Set-Content src\index.css $cssContent

# 7. Update Entry Point (Overwrite src/main.jsx)
$mainJsx = @"
import React from 'react'
import ReactDOM from 'react-dom/client'
import FamilyArchiveVault from './FamilyArchiveVault.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <FamilyArchiveVault />
  </React.StrictMode>,
)
"@
Set-Content src\main.jsx $mainJsx

# 8. Create Placeholder for the UI
New-Item -Path "src\FamilyArchiveVault.jsx" -ItemType File -Value "// PASTE THE REACT CODE HERE" -Force

Write-Host "--- Setup Complete! ---" -ForegroundColor Green
Write-Host "Action Required:" -ForegroundColor Yellow
Write-Host "1. Copy the code from the 'family_archive_ui.jsx' file."
Write-Host "2. Paste it into: F:\FamilyArchive\frontend\src\FamilyArchiveVault.jsx"
Write-Host "3. In a terminal, run: cd frontend; npm run dev"
Read-Host -Prompt "Press Enter to exit"
