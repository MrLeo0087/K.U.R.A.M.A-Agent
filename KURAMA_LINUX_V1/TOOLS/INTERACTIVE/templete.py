gitignore = '''# ==========================================
# Environments & Virtual Envs
# ==========================================
.venv/
venv/
ENV/
env/
env.bak/
venv.bak/
bin/
lib/
include/

# ==========================================
# Environment Variables & Credentials
# ==========================================
.env
.env.local
.env.*.local
*.pem
*.key
*.cert

# ==========================================
# Python Bytecode & Cache
# ==========================================
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# ==========================================
# IDEs & Code Editors
# ==========================================
# VS Code
.vscode/
!.vscode/settings.json
!.vscode/tasks.json
!.vscode/launch.json
!.vscode/extensions.json
*.code-workspace

# PyCharm / JetBrains
.idea/

# Sublime Text
*.sublime-project
*.sublime-workspace

# ==========================================
# Operating System Files
# ==========================================
# Linux / Ubuntu
*~
.directory

# macOS
.DS_Store
.AppleDouble
.LSOverride

# Windows
Thumbs.db
Thumbs.db:encryptable
ehthumbs.db
Desktop.ini

# ==========================================
# Packaging & Distributions
# ==========================================
build/
devel/
dist/
downloads/
eggs/
.eggs/
*.egg-info/
*.egg

# ==========================================
# Logs & Databases
# ==========================================
*.log
*.sqlite
*.db'''

requirement = '''# ==========================================
# Core Application Dependencies
# ==========================================
# Example: Popular HTTP library (Pinnned to exact version)
requests==2.31.0

# Example: Environment variable management (.env support)
python-dotenv==1.0.1

# ==========================================
# Data Processing & Utilities
# ==========================================
# Example: Data manipulation (Compatible with minor updates)
# pandas>=2.2.0,<3.0.0

# ==========================================
# Testing & Quality Assurance
# ==========================================
# Unit testing framework
pytest==8.0.2

# Code formatting & linting
black==24.2.0
flake8==7.0.0'''


readme = '''# Project Name

> A brief, 1–2 sentence pitch explaining what this project does and why it exists.

---

## 📋 Table of Contents
- [Features](#-features)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Usage](#-usage)
- [Project Structure](#-project-structure)
- [Configuration](#-configuration)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features
- **Feature 1:** High-level description of key capability.
- **Feature 2:** High-level description of key capability.
- **Feature 3:** High-level description of key capability.

---

## ⚙️ Prerequisites

Before you begin, ensure you have met the following requirements:
* **OS:** Ubuntu / Linux, macOS, or Windows
* **Language/Runtime:** Python 3.10+ / Node.js 18+ / Docker / etc.
* **Dependencies:** System packages or tools required before setup.

---

## 🚀 Installation

Follow these steps to set up the project locally:

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
   cd your-repo-name'''