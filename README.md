# teleprompter
Python teleprompter for Windows

## Features
- Load a script from file (.txt, .md, .rtf basic text)
- Smooth auto-scroll with adjustable speed (pixels/sec)
- "Fit to duration" (auto-compute scroll speed to finish in a target time)
- Adjustable font family, size, line spacing, and margins
- Horizontal mirror mode for beam-splitter glass (toggle)
- Start/Pause/Stop, Jump, and Rewind controls + keyboard shortcuts
- Countdown overlay before start
- Optional focus band to keep eyes centered
- Fullscreen toggle

## Shortcuts
- Space: Start/Pause
- Esc: Exit fullscreen / close dialogs
- F11: Toggle fullscreen
- Up/Down: Increase/Decrease speed
- Left/Right: Small backward/forward jump
- PageUp/PageDown: Large backward/forward jump
- +/-: Increase/Decrease font size
- M: Toggle mirror
- 0 (zero): Jump to top
- G: Go to percentage
- O: Open file
- R: Fit speed to duration (after setting a target)

## Dependencies
- PySide6 (Qt for Python): `pip install PySide6`

## Run
- `python teleprompter_app.py your_script.txt`
- or just `python teleprompter_app.py` and use File → Open
