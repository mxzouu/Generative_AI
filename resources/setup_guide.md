# Generative AI — Development Environment Setup Guide

## Introduction
This guide will help you set up a professional Python development environment for the Generative AI module (Master 2, work-study program). It covers everything you need for the hands-on labs (TD notebooks) and the final hackathon project.

## 1. Install Git
Git is essential for version control and collaboration.

### Windows/macOS:
- **Download**: Go to the [Git website](https://git-scm.com/) and download the installer for your operating system.
- **Install**: Run the installer and follow the on-screen instructions.
  - **Important**: Check the option "Add Git to PATH" during installation.
  - **macOS users**: You can also install Git using Homebrew: `brew install git`

### Verification:
Open a terminal/command prompt and run:
```bash
git --version
```
You should see the installed Git version.

## 2. Install a Code Editor

You can use any code editor you prefer. Here are some recommended options:

### Option A: VS Code (Recommended)
- **Download**: Go to the [VS Code website](https://code.visualstudio.com/) and download the installer.
- Install the **Python** and **Jupyter** extensions from the Extensions sidebar.

### Option B: Any editor of your choice
- PyCharm, Sublime Text, or any editor you're comfortable with.

## 3. Install Claude Code

Claude Code is an AI-powered coding assistant that runs in your terminal. It can understand your codebase, write code, run commands, and help you build projects faster.

### Installation:

Claude Code requires Node.js. Install it first if you don't have it:
- **Download Node.js**: Go to the [Node.js website](https://nodejs.org/) and download the LTS version.

Then install Claude Code globally:
```bash
npm install -g @anthropic-ai/claude-code
```

### Usage:
Navigate to your project directory and launch Claude Code:
```bash
cd your-project-folder
claude
```

Claude Code will be your AI pair-programmer throughout this course. Use it to:
- Generate code from natural language descriptions
- Debug and fix issues in your code
- Understand unfamiliar code
- Run and test your application
- Help with Git operations

### Authentication:
When you first run Claude Code, log in with the **Claude Pro account** provided for the course (see the next section to understand the difference with the API key).

For more information, see the [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code).

## 3b. Two ways to access Claude — don't mix them up!

You have **two separate access channels**, with different billing logic. Understanding the difference is important to avoid running out of budget.

### Claude Code = your Pro subscription
- The coding assistant in your terminal, billed through your **Claude Pro plan** (quota-based).
- Use it to **help you write code**: build and debug your app and notebooks.
- The model choice affects your quota: a lighter model (**Haiku**) consumes far less than a heavy one (**Opus**). Reserve the heavy model for hard reasoning; switch to the light one for everything else.
- Save quota: use `/compact` to shrink the context, keep sessions short and focused, use `/clear` between tasks.
- The same Pro subscription also gives you access to Claude outside the terminal: through the **Claude Desktop app** and on **[claude.ai](https://claude.ai)**. Handy for brainstorming, asking questions, or working through ideas before you write code.

### API key = programmatic calls from your code
- This is what **your code calls at runtime** (the LLM you call inside your RAG, agent, classifier…). Billed per token, on a **limited budget**. The API key is private and allows you to send requests to Anthropic LLMs directly via code.
- **⚠️ Budget rule: in your code, use only Claude Haiku** (the cheapest model) for all labs and projects.

#### Store your key in a `.env` file (recommended)
The instructor provides your key. Create a file named `.env` at the **root of the project** (next to `requirements.txt`) containing a single line:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```
A `.env` file is just text — something has to load it into the environment. We use the `python-dotenv` package (already in `requirements.txt`): call `load_dotenv()` once at the top of your code, and the Anthropic SDK then reads the key automatically.
```python
from dotenv import load_dotenv
import anthropic

load_dotenv()              # reads .env into the environment
client = anthropic.Anthropic()   # picks up ANTHROPIC_API_KEY automatically
```
- **Never commit your API key** to Git. The `.env` file is already listed in `.gitignore`, so it stays out of your commits — keep it that way.

> The right reflex: **code/debug with Claude Code (Pro)**, but run **only Haiku API calls** inside your code.

## 4. Install Python
We'll use Python 3.12 for this course.

### Windows/macOS:
- **Download**: Visit the [Python website](https://www.python.org/downloads/) and download Python 3.12.
- **Install**: Run the installer with these important steps:
  - Check "Add Python 3.12 to PATH"
  - Choose "Customize installation"
  - Select all optional features
  - Choose "Install for all users" (recommended)

### Verification:
Open a terminal/command prompt and run:
```bash
python --version
```
You should see "Python 3.12.x"

## 5. Set Up Your Development Environment

### Why use a virtual environment?
A virtual environment is an isolated Python installation dedicated to a single project. Instead of installing packages globally on your machine, you install them into a self-contained folder. This matters because:
- **No version conflicts**: different projects can require different versions of the same package. Without isolation, installing one project's dependencies can silently break another.
- **Reproducibility**: everyone on the course works from the same `requirements.txt`, so the environment is the same for everyone — fewer "but it works on my machine" surprises.
- **Clean and disposable**: if something goes wrong, you just delete the folder and recreate it. Your system Python stays untouched.

**Where to create it**: create the environment **inside this project folder** (the folder containing `requirements.txt`), so it lives next to the code it serves. The folder is named `genai_env` below; it's already covered by `.gitignore`, so it won't be committed to Git.

You have two options for managing your Python environment:

### Option 1: Using Python's built-in venv (Recommended for beginners)
```bash
# From the root of this project folder, create a new virtual environment
python -m venv genai_env

# Activate the environment
# On Windows:
genai_env\Scripts\activate
# On macOS/Linux:
source genai_env/bin/activate
```

### Option 2: Using Anaconda (Optional)
Anaconda provides a more comprehensive environment management system with additional scientific computing packages.

#### Installation:
- **Download**: Go to the [Anaconda website](https://www.anaconda.com/products/individual) and download Anaconda for Python 3.12.
- **Install**: Run the installer and follow the on-screen instructions.
  - Choose "Install for all users" (recommended)
  - Add Anaconda to PATH (recommended)

#### Create and Activate Environment:
```bash
# Create a new environment
conda create -n genai_env python=3.12

# Activate the environment
conda activate genai_env
```

### Verification (for both options):
```bash
# Verify Python version
python --version

# Verify environment is active (should show genai_env)
which python  # On macOS/Linux
where python  # On Windows
```

### Install Required Packages
In your activated environment (using either venv or conda), run:
```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install pandas numpy anthropic python-dotenv chromadb sentence-transformers scikit-learn matplotlib mcp jupyter ipykernel
```

### Verify Package Installation:
The simplest check is to open and run `notebooks/getting_started.ipynb` top to bottom — it verifies your Python version, every package, the Anthropic API call, and the embedding model in one go.

For a quick sanity check from the terminal:
```bash
# Test the Anthropic SDK
python -c "import anthropic; print('Anthropic SDK installed successfully')"
# Test the core data packages
python -c "import pandas as pd; import numpy as np; print('All packages installed successfully')"
```

## 6. Configure Your Editor

### If using VS Code:

#### Install Required Extensions
1. Open VS Code
2. Go to Extensions (sidebar)
3. Install these essential extensions:
   - Python
   - Jupyter

#### Configure Python Interpreter
1. Open Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
2. Type "Python: Select Interpreter"
3. Choose the `genai_env` environment you created

## 7. Best Practices

### Version Control
- Initialize Git in your project directory
- Create a `.gitignore` file
- Make regular commits with meaningful messages

### Virtual Environment
- Always work in your virtual environment
- Keep `requirements.txt` up to date
- Document all dependencies

### Code Organization
- Follow PEP 8 style guide
- Use meaningful variable and function names
- Add comments and docstrings
- Write tests for your code

### Using Claude Code effectively
- Be specific in your prompts: describe what you want clearly
- Use it to scaffold boilerplate code, then refine
- Ask it to explain code you don't understand
- Use it to debug: paste error messages and ask for help

## Need Help?
If you encounter any issues during setup:
1. **Ask Claude Code first!** Seriously — make it a reflex. You literally have an AI pair-programmer sitting in your terminal, and it doesn't sleep, judge, or sigh when you paste a cryptic error for the third time. Drop the error message in and ask. (Yes, even before you message a classmate.)
2. Search for similar issues online
3. Contact your instructor (the human fallback, for when even the robot is stumped)
