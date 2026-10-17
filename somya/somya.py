"""Somya - a Jarvis-style personal assistant.

Say "Somya" followed by a command (voice), or type commands (text mode).
Run:  python somya/somya.py          (voice, falls back to text)
      python somya/somya.py --text   (force text mode)
"""
import datetime
import os
import platform
import subprocess
import sys
import urllib.parse
import webbrowser

NAME = "Somya"

try:
    import pyttsx3
    _engine = pyttsx3.init()
except Exception:
    _engine = None

try:
    import speech_recognition as sr
except Exception:
    sr = None


def speak(text):
    print(f"{NAME}: {text}")
    if _engine:
        try:
            _engine.say(text)
            _engine.runAndWait()
        except Exception:
            pass


def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
        print("Listening...")
        audio = r.listen(source, phrase_time_limit=8)
    try:
        return r.recognize_google(audio).lower()
    except Exception:
        return ""


SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
}


def open_app(name):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(name)
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name])
        return True
    except Exception:
        return False


def handle(cmd):
    """Return False to exit."""
    cmd = cmd.strip().lower()
    for w in (NAME.lower(), "hey", "jarvis"):
        cmd = cmd.replace(w, "").strip()
    if not cmd:
        speak("Yes? I'm listening.")
    elif any(w in cmd for w in ("bye", "exit", "quit", "stop")):
        speak("Goodbye! Call me anytime.")
        return False
    elif "hello" in cmd or "hi" == cmd:
        speak(f"Hello! I'm {NAME}, your assistant. How can I help?")
    elif "who are you" in cmd or "your name" in cmd:
        speak(f"I am {NAME}, your personal Jarvis.")
    elif "time" in cmd:
        speak(datetime.datetime.now().strftime("It's %I:%M %p"))
    elif "date" in cmd or "today" in cmd:
        speak(datetime.datetime.now().strftime("Today is %A, %d %B %Y"))
    elif cmd.startswith("play "):
        q = urllib.parse.quote(cmd[5:])
        speak(f"Playing {cmd[5:]} on YouTube")
        webbrowser.open(f"https://www.youtube.com/results?search_query={q}")
    elif cmd.startswith(("search ", "google ")):
        term = cmd.split(" ", 1)[1].replace("for ", "", 1)
        speak(f"Searching for {term}")
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(term))
    elif cmd.startswith("open "):
        target = cmd[5:].strip()
        if target in SITES:
            speak(f"Opening {target}")
            webbrowser.open(SITES[target])
        elif open_app(target):
            speak(f"Opening {target}")
        else:
            speak(f"Sorry, I couldn't open {target}")
    elif "joke" in cmd:
        speak("Why do programmers prefer dark mode? Because light attracts bugs!")
    else:
        speak("I didn't get that. Try: open youtube, play a song, search something, or ask the time.")
    return True


def main():
    text_mode = "--text" in sys.argv or sr is None
    speak(f"Hello, I am {NAME}. Systems online.")
    if text_mode:
        print("(text mode - type commands, 'bye' to quit)")
    while True:
        try:
            if text_mode:
                cmd = input("You: ")
            else:
                cmd = listen()
                if not cmd:
                    continue
                print(f"You: {cmd}")
                if NAME.lower() not in cmd and "jarvis" not in cmd:
                    continue  # wake word required
        except (EOFError, KeyboardInterrupt):
            break
        except OSError:
            print("No microphone found, switching to text mode.")
            text_mode = True
            continue
        if not handle(cmd):
            break


if __name__ == "__main__":
    main()
