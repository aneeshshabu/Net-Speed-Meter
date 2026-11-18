# NetSpeedMeter

A tiny, no-nonsense network speed overlay for Windows. It shows your live download/upload speed in MB/s in a small always-on-top bar, and nothing else.

No ads, no popups, no browser pages opening at startup, and no network connections of its own. I had to make this out of sheer frustration from the options available on MS Store. They are riddled with ads, persistent pop ups and to stop that the developer asked for monthly subscription, for a speed indicator. Hence Net Speed Meter.

<img width="281" height="64" alt="image" src="https://github.com/user-attachments/assets/9aa534d0-fc4a-405e-8e65-6b417ec56abd" />

<img width="338" height="55" alt="image" src="https://github.com/user-attachments/assets/1a5ed688-e646-4f2d-9616-d8f6e9ac7732" />


## Features

- Live download and upload speed in MB/s, updated every second
- Stays on top of other windows, including the taskbar
- Drag it anywhere; it remembers its position
- Separate opacity for the background and the text
- One-line or two-line layout
- Dims automatically when a video or app goes fullscreen
- Arrow turns red on a sudden jump in speed
- Optional start with Windows

## Usage

| Action | What it does |
| --- | --- |
| Drag | Move the overlay |
| Double-click | Open Settings |
| Settings → Quit app | Close it |

## Install

### Option 1: Exe (no Python needed)

Download `NetSpeedMeter.exe` from [Releases](../../releases) and double-click it.

Windows may show "Windows protected your PC" because the exe isn't signed. Click **More info** and then **Run anyway**.

### Option 2: Run from source

1. Install [Python 3](https://www.python.org/downloads/) and tick "Add Python to PATH".
2. Install the one dependency:
   ```
   python -m pip install psutil
   ```
3. Double-click `netspeed.pyw`.

## Build the exe yourself

Put `build.bat` next to `netspeed.pyw` and double-click it. The exe appears in `dist\NetSpeedMeter.exe`.

## Settings and logs

Settings are saved in `%APPDATA%\NetSpeedMeter\settings.json`. If the app ever fails silently, check `error.log` in the same folder.

Spacing, font, colors and spike sensitivity can be changed in the constants at the top of `netspeed.pyw`.

## Notes

- Windows only.
- MB/s means megabytes per second. Multiply by 8 for megabits (Mbps).
