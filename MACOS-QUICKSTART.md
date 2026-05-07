# 🍎 CloudHorus for macOS - Quick Start Guide

## 🚀 One-Command Launch

```bash
chmod +x launcher-macos.sh && ./launcher-macos.sh
```

## 📋 Step-by-Step Instructions

### 1. Open Terminal
- **Method 1:** Press `⌘ + Space`, type "Terminal", press Enter
- **Method 2:** Applications → Utilities → Terminal
- **Method 3:** Finder → Applications → Utilities → Terminal

### 2. Navigate to CloudHorus Folder
```bash
# If downloaded to Downloads folder:
cd ~/Downloads/CloudHorus

# Or wherever you cloned/downloaded CloudHorus:
cd /path/to/CloudHorus
```

### 3. Run the Launcher
```bash
# Method 1: Make executable and run (recommended)
chmod +x launcher-macos.sh
./launcher-macos.sh

# Method 2: Direct execution (no chmod needed)
bash launcher-macos.sh

# Method 3: Double-click launcher-macos.sh in Finder
# → Right-click → "Open With" → "Terminal"
```

## 🔧 What the Launcher Does

The launcher follows a 6-step consent-based flow:
1. **[1/6] Homebrew + Python** - Checks/installs Homebrew, Python 3, and pip
2. **[2/6] System Dependencies** - Checks Graphviz (required) and Azure CLI (optional)
3. **[3/6] Virtual Environment** - Creates `cloudhorus-env` (recommended)
4. **[4/6] Python Dependencies** - Checks each package individually before installing
5. **[5/6] Bicep CLI** - Optional, for IaC template analysis
6. **[6/6] Verification** - Shows installation summary

Each optional component asks for your consent (Y/n) before installing.

## 🚨 Troubleshooting

### "Permission denied" Error
```bash
chmod +x launcher-macos.sh
```

### "Operation not permitted" Error
```bash
sudo chmod +x launcher-macos.sh
```

### Gatekeeper Warning
- System Preferences → Security & Privacy → General
- Click "Allow" for blocked software

### Alternative (No Permission Issues)
```bash
bash launcher-macos.sh
```

## 📱 System Requirements

- macOS 10.14 (Mojave) or later
- Internet connection for initial dependency downloads
- Administrator privileges may be needed for Homebrew installation

## 🆘 Need Help?

If you encounter issues:
1. Check the main [README.md](README.md) troubleshooting section
2. Ensure you're in the CloudHorus directory
3. Try the alternative execution method: `bash launcher-macos.sh`

## 🎯 After Installation

Once the GUI launches:
- Select your Bicep templates or Azure resources
- Configure visualization settings
- Generate beautiful Azure architecture diagrams!

Happy visualizing! 🦅✨

