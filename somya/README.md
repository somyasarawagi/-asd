# Somya — your Jarvis

A personal voice assistant. Say "Somya, ..." and a command.

## Setup
    pip install -r somya/requirements.txt
    python somya/somya.py          # voice mode
    python somya/somya.py --text   # type commands instead

## Commands
- "Somya open youtube / gmail / github / <app>"
- "Somya play <song>"  (YouTube)
- "Somya search <anything>"
- "Somya what's the time" / "date" / "tell me a joke"
- "Somya bye"

Add more in `handle()` inside `somya.py`.

## Easiest way (no install)
Double-click `somya/index.html` (open in Chrome), tap the orb and talk.
