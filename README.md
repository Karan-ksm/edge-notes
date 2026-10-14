# Edge Notes

A colored binder-divider tab that always sticks out of the edge of your Mac's screen.
Click it and a notes panel slides out with your to dos and ideas, so you can jot things
down without switching apps.

## Requirements

- A Mac. Edge Notes is macOS only.
- Python 3.9 or newer. The one that comes with Apple's Command Line Tools works fine.
- Liquid Glass needs macOS 26 (Tahoe). Older macOS gets a frosted blur instead, or you
  can use the Paper style.

## Install

Open Terminal and run:

```bash
git clone https://github.com/Karan-ksm/edge-notes.git
cd edge-notes
./setup.sh
./run.sh
```

`setup.sh` creates a private Python environment in a `.venv` folder inside the project and
installs everything Edge Notes needs into it. Nothing is installed system-wide. You only
run it once.

If Terminal says `git` or `python3` isn't found, run `xcode-select --install`, follow the
prompt, then try again.

The tab appears on the right edge of your screen, just below the menu bar.

To have it start automatically when you log in, see **Start at login** below.

## Use

- **Click the tab** to open or close the panel. Esc or clicking anywhere else also closes it.
- **Drag the tab** anywhere. When you let go it snaps to the nearest left or right edge, so it
  can sit in any corner. The panel slides out from whichever side it's on.
- **To dos:** type and press Enter to add. Tick the box to complete. Double-click to edit.
  Backspace/Delete or right-click > Delete removes one. "clear done" removes all completed.
- **Ideas:** free-form text box at the bottom.
- The tab shows the number of unfinished to dos, and nothing when you're all done.
- **Right-click the tab** for:
  - **Tab color…** opens the macOS color wheel with a live preview.
  - **Style**: Liquid glass (default, macOS glass behind the panel, follows light/dark mode) or Paper.
  - **See-through** (Paper style only: Off, Light, Medium, Strong) fades the panel and tab background.

## Quit

Right-click the tab and choose **Quit Edge Notes**.

If the login agent is installed, it has KeepAlive on, so launchd restarts the app after you
quit. Run `./uninstall_launch_agent.sh` to stop it for good.

## Data

Everything lives in `~/.edge_notes/notes.json`. It autosaves about 400ms after each change,
and also when the panel closes and when the app quits. A missing or broken file just starts
you with empty notes.

## Start at login

```bash
./install_launch_agent.sh     # creates and loads ~/Library/LaunchAgents/com.karan.edgenotes.plist
./uninstall_launch_agent.sh   # unloads it and deletes the plist
```

Run `./setup.sh` before installing the login agent so it uses the project's environment.
Errors from the login agent go to `/tmp/edgenotes.err`. Re-run the install script if you
move this folder.

## Update

```bash
cd edge-notes
git pull
./setup.sh
```

Then quit Edge Notes from the tab's right-click menu and start it again with `./run.sh`.
If the login agent is installed, it restarts on its own.

## Customize

Constants at the top of `edge_notes.py` control the default tab color, sizes, see-through levels,
and animation speed and easing.
