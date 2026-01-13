# AI Agent Instructions

This file contains instructions for AI coding agents (like Claude Code) working on this project.

## Permissions

AI agents have permission to:
- Execute bash commands without asking for confirmation
- Run Python scripts using the venv
- Modify code files
- Test changes by running the monitor
- Fetch any website without asking for permission (for research, monitoring setup, etc.)
- Run read-only commands (wc, ls, cat, head, tail, grep, find, etc.) without asking for permission
- Run any Python code to validate, test, or debug things without asking for permission (including heredoc scripts like `./venv/bin/python3 << 'EOF'`)

No need to ask "Can I run this?" - just execute commands directly.

## Python Environment

**IMPORTANT**: This project uses a virtual environment. Always use it:

```bash
# Option 1: Activate then run
source venv/bin/activate && python3 script.py

# Option 2: Use venv Python directly
./venv/bin/python3 script.py
./venv/bin/pip install package_name
```

Do NOT install packages globally with `pip3 install`. Use the venv.

## Project Structure

```
page-watcher/
├── monitor.py          # Main monitoring script
├── telegram_bot.py     # Telegram notification helper
├── watchdog.py         # Service health monitor
├── keep_render_alive.py # Server ping script
├── urls_config.yaml    # URL configuration (not secrets, can commit)
├── .env                # Secrets (do not commit)
├── .env.example        # Template for .env
├── requirements.txt    # Python dependencies
├── page-history/       # Stored page snapshots
└── venv/               # Python virtual environment
```

## Configuration

- **Secrets** (Telegram tokens, etc.): `.env` file (not committed to git)
- **URLs to monitor**: `urls_config.yaml` file (committed to git)

## Running the Monitor

```bash
source venv/bin/activate
python3 monitor.py
```

## Testing Changes

After modifying monitor.py, test with:
```bash
source venv/bin/activate
python3 -c "
from dotenv import load_dotenv
load_dotenv()
from monitor import monitor_page, URLS
# Test a specific URL
monitor_page(URLS[0])
"
```

## Dependencies

If you need to install a new package:
```bash
source venv/bin/activate
pip install package_name
pip freeze > requirements.txt
```
