# KURAMA: commands to start, stop and restart

Run every command from the project folder first:

```bash
cd /media/leo/Project1/New_project/KURAMA
```

## Everything at once (most common)

| What | Command |
|---|---|
| Start | `scripts/kurama-power.sh on` |
| Stop (frees all RAM and CPU) | `scripts/kurama-power.sh off` |
| Restart | `scripts/kurama-power.sh off && scripts/kurama-power.sh on` |
| Is it running? | `scripts/kurama-power.sh status` |

- `on` starts three things together:
  - the wallpaper (KURAMA's screen)
  - the server
  - the background jobs (Telegram, reminders, alerts)
- `off` stops every KURAMA process and puts your normal wallpaper back.
- After `off`, KURAMA stays off even after a reboot, until you turn it on again.
- Shortcuts: **Super+K**, or the power button in KURAMA's window.

## One part at a time

**Server.** Restart it after backend (Python) changes:

```bash
pkill -f "m jarvis[.]server"; nohup venv/bin/python -m jarvis.server --port 8000 >> data/logs/server.log 2>&1 &
```

**Background jobs.** These are Telegram, reminders and alerts:

```bash
pkill -f "m jarvis[.]workers"; nohup venv/bin/python -m jarvis.workers >> data/logs/workers.out 2>&1 &
```

**Screen.** Reload it after UI changes:

```bash
scripts/kurama-wallpaper.sh stop && scripts/kurama-wallpaper.sh
```

| What | Command |
|---|---|
| Close only the screen (the server keeps running) | `scripts/kurama-wallpaper.sh stop` |
| Open as a normal window instead of the wallpaper | `scripts/kurama-wallpaper.sh --window` |
| Open in any browser (server must be running) | http://127.0.0.1:8000 |

## Mic and device sound

KURAMA can remove the laptop's own sound (videos, music, its own voice) from the mic. Turn this on or off in
Settings → **Hear device sound**. When it's off (the default), "Speakers (through KURAMA)" is your speaker in
the sound settings.

| What | Command |
|---|---|
| Is the device-sound remover on? | `pactl get-default-source` (shows `kurama_ec_source` when it's on) |
| Put normal sound settings back now | `venv/bin/python -m jarvis.core.devaudio off` |
| Apply the saved setting again | `venv/bin/python -m jarvis.core.devaudio` |

`scripts/kurama-power.sh off` also puts the normal sound settings back.

## Checking and troubleshooting

| What | Command |
|---|---|
| Is the server answering? | `curl -s localhost:8000/api/v1/health` |
| Server log, live | `tail -f data/logs/server.log` |
| Background jobs log | `tail -f data/logs/workers.out` |
| Screen (wallpaper) log | `tail -f data/logs/wallpaper.log` |
| What KURAMA heard (voice) | `tail -20 data/logs/stt.log` |

Press Ctrl+C to leave a `tail -f` log view. It doesn't stop KURAMA.

If KURAMA ever seems stuck, restart everything: run `off`, then `on`. That fixes almost everything.
