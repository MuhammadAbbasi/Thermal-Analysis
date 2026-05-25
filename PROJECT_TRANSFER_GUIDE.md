# AutoThermo Project Transfer Guide

## Overview
This guide provides step-by-step instructions to transfer the AutoThermo thermal analysis project to another PC entirely.

---

## Prerequisites

- **Git** installed and configured (https://git-scm.com/)
- **Python 3.8+** installed
- **pip** package manager
- Access to the remote Git repository
- Network connectivity

---

## Step 1: Clone the Repository

### On the New PC:

1. Open PowerShell or Command Prompt
2. Navigate to the location where you want to store the project:
   ```powershell
   cd "C:\Users\YourUsername\Documents"
   ```

3. Clone the repository:
   ```powershell
   git clone <REMOTE_REPOSITORY_URL> AutoThermo
   ```
   Replace `<REMOTE_REPOSITORY_URL>` with your actual repository URL (e.g., GitHub, GitLab, Azure DevOps)

4. Navigate into the project directory:
   ```powershell
   cd AutoThermo
   ```

---

## Step 2: Set Up Python Environment

### Option A: Using venv (Recommended)

1. Create a virtual environment:
   ```powershell
   python -m venv venv
   ```

2. Activate the virtual environment:
   ```powershell
   # On Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   
   # Or on Command Prompt:
   venv\Scripts\activate.bat
   ```

3. Upgrade pip:
   ```powershell
   python -m pip install --upgrade pip
   ```

4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

### Option B: Using Conda

```powershell
# Create environment
conda create -n autothermo python=3.10

# Activate environment
conda activate autothermo

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3: Download Large Binary Files

The project includes large binary files that may not be included in the repository:

### YOLOv8 Model
- File: `yolov8m.pt` (~49 MB)
- If missing, download from:
  ```
  https://github.com/ultralytics/assets/releases/download/v8.0.0/yolov8m.pt
  ```
- Place in the project root directory

### DWF Layout File
- File: `24S002_2E400 - Layout stringhe REV03 per thermografia.dwf`
- If missing, check if it's stored in a shared location or contact the project maintainer

---

## Step 4: Verify Database and Data Files

Check for the following directories and files:

```
data/
├── plant_catalog.json
├── plant_layout.geojson
├── plant_metadata.json
├── plant_panels.geojson
├── plant_strings_raw.json
└── SP3/
    └── 2026_05_13/

autothermo.db (SQLite database)
```

If these files are missing:
- Check if they need to be downloaded from a separate source
- Or run the data generation scripts (see Step 5)

---

## Step 5: Initialize Data (If Needed)

If working with a fresh setup, run the data processing scripts:

```powershell
# Parse DWF layout
python parse_dwf.py

# Extract W3D data
python extract_w3d.py

# Build plant layout
python build_plant_layout.py

# Check coordinates
python check_coords.py
```

---

## Step 6: Run the Application

### Start the Web Server:

```powershell
# Make sure virtual environment is activated
python app/main.py
```

The application should start on `http://localhost:8000`

### Access the Web Interface:

Open your browser and navigate to:
```
http://localhost:8000
```

---

## Step 7: Configure Git (If Contributing)

Set up your Git credentials for pushing changes:

```powershell
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

---

## Project Structure Overview

```
AutoThermo/
├── app/                          # FastAPI application
│   ├── main.py                  # Main application entry point
│   ├── config.py               # Configuration settings
│   ├── models.py               # Data models
│   ├── tracker_pipeline.py     # Tracking pipeline
│   ├── geolocator.py           # Geolocation utilities
│   ├── layout_mapper.py        # Layout mapping
│   ├── exif_parser.py          # EXIF data parsing
│   └── static/
│       └── index.html          # Web interface
│
├── data/                         # Data directory
│   ├── plant_catalog.json      # Plant catalog
│   ├── plant_layout.geojson    # Layout GeoJSON
│   ├── plant_metadata.json     # Metadata
│   └── SP3/                    # Thermal image data
│
├── dwf_extracted/              # DWF extraction files
├── weights/                    # Model weights
├── requirements.txt            # Python dependencies
├── config.py                   # Global configuration
├── run.py                      # Alternative run script
└── README.md                   # Project documentation
```

---

## Troubleshooting

### 1. **ModuleNotFoundError for dependencies**
```powershell
# Ensure virtual environment is activated
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### 2. **Port 8000 already in use**
```powershell
# Use a different port
python app/main.py --port 8001
```

### 3. **GPU/CUDA Issues**
- YOLOv8 can work on CPU (slower but functional)
- For GPU acceleration, install CUDA-compatible PyTorch:
  ```powershell
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
  ```

### 4. **Database Issues**
```powershell
# Delete and regenerate database
rm autothermo.db
python app/main.py  # Will recreate on startup
```

### 5. **Missing Data Files**
- Check the `data/` directory structure
- Re-run data processing scripts
- Contact the project maintainer for data archives

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 | Windows 10/11 or Linux |
| Python | 3.8 | 3.10+ |
| RAM | 4 GB | 8 GB+ |
| Storage | 2 GB | 10 GB+ |
| GPU | Optional | NVIDIA (CUDA support) |

---

## Network & Remote Access

### For Remote Access to the Web Interface:

1. Modify `app/main.py` to bind to all interfaces:
   ```python
   uvicorn.run(app, host="0.0.0.0", port=8000)
   ```

2. Update firewall rules to allow port 8000

3. Access from another machine:
   ```
   http://<PC_IP_ADDRESS>:8000
   ```

---

## Backing Up the Project

Before transferring, create a backup:

```powershell
# Create a compressed archive
Compress-Archive -Path "C:\path\to\AutoThermo" -DestinationPath "AutoThermo_backup_$(Get-Date -Format 'yyyy-MM-dd').zip"
```

---

## Version Control Best Practices

When working on the transferred project:

```powershell
# Check current branch
git status

# Create a new branch for changes
git checkout -b feature/new-feature

# Commit changes regularly
git add .
git commit -m "Descriptive commit message"

# Push to remote
git push origin feature/new-feature

# Create pull request for review
```

---

## Support & Contact

For issues or questions:
- Check the project README.md
- Review the `analisi_portale_webgis_termografico_fv.md` documentation
- Contact the project maintainer

---

**Last Updated:** May 25, 2026
