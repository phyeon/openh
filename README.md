# openh

Terminal chat GUI for Claude and Gemini, with Claude Code-style tools.

## Setup

```bash
cd /Users/hyeon/Projects/openh
python3 -m venv .venv
.venv/bin/pip install -e .
```

API keys are loaded from `/Users/hyeon/Projects/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
```

## Run

```bash
.venv/bin/python -m openh
```

## Keys

- `Ctrl+M` — switch between Claude and Gemini
- `Ctrl+C` — quit
- `Enter` — send message
