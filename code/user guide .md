# MH2 Clap-Snap Keyboard
## Complete Morse Code & User Guide

**Developer:** MH2 HRIDOY

---

## 1. Basic Sound Rules

| Action | Sound | Result |
|---|---|---|
| Single clap/snap | 1 sound | DOT (`.`) |
| Double clap/snap | 2 sounds within 0.40 seconds | DASH (`-`) |
| Letter decoding | 0.60 seconds of silence | Decodes and types the character |

### Important Rules

- One detected sound represents one DOT (`.`).
- Two sounds within the same 0.40-second group represent one DASH (`-`).
- Three sounds in one group represent DASH + DOT (`-.`).
- Four sounds in one group represent DASH + DASH (`--`).
- After completing a Morse sequence, wait for 0.60 seconds of silence.
- The application uses microphone input to detect claps and finger snaps.

---

## 2. Complete A–Z Morse Code

| Letter | Morse Code | Sound Pattern |
|---|---|---|
| A | `.-` | DOT + DASH |
| B | `-...` | DASH + DOT + DOT + DOT |
| C | `-.-.` | DASH + DOT + DASH + DOT |
| D | `-..` | DASH + DOT + DOT |
| E | `.` | DOT |
| F | `..-.` | DOT + DOT + DASH + DOT |
| G | `--.` | DASH + DASH + DOT |
| H | `....` | DOT + DOT + DOT + DOT |
| I | `..` | DOT + DOT |
| J | `.---` | DOT + DASH + DASH + DASH |
| K | `-.-` | DASH + DOT + DASH |
| L | `.-..` | DOT + DASH + DOT + DOT |
| M | `--` | DASH + DASH |
| N | `-.` | DASH + DOT |
| O | `---` | DASH + DASH + DASH |
| P | `.--.` | DOT + DASH + DASH + DOT |
| Q | `--.-` | DASH + DASH + DOT + DASH |
| R | `.-.` | DOT + DASH + DOT |
| S | `...` | DOT + DOT + DOT |
| T | `-` | DASH |
| U | `..-` | DOT + DOT + DASH |
| V | `...-` | DOT + DOT + DOT + DASH |
| W | `.--` | DOT + DASH + DASH |
| X | `-..-` | DASH + DOT + DOT + DASH |
| Y | `-.--` | DASH + DOT + DASH + DASH |
| Z | `--..` | DASH + DASH + DOT + DOT |

---

## 3. Number Morse Codes (0–9)

| Number | Morse Code |
|---|---|
| 0 | `-----` |
| 1 | `.----` |
| 2 | `..---` |
| 3 | `...--` |
| 4 | `....-` |
| 5 | `.....` |
| 6 | `-....` |
| 7 | `--...` |
| 8 | `---..` |
| 9 | `----.` |

---

## 4. Special Keyboard Commands

| Function | Morse Code | Output |
|---|---|---|
| SPACE | `..--` | Inserts a space |
| BACKSPACE | `---.` | Deletes the previous character |
| BACKSPACE (Alternative) | `........` | Deletes the previous character |
| ENTER | `.-.-` | Inserts a new line |

---

## 5. Understanding DOT (.) and DASH (-)

### DOT (`.`)

- Give one clap or finger snap.
- One detected sound represents one DOT.
- Example: `E = .`

### DASH (`-`)

- Give two quick claps or finger snaps.
- Both sounds must be detected within 0.40 seconds.
- Two sounds in the same group represent one DASH.
- Example: `T = -`

### Example: Typing Letter A

Morse Code: `.-`

1. Give one clap → DOT (`.`).
2. Give two quick claps within 0.40 seconds → DASH (`-`).
3. Wait for 0.60 seconds of silence.
4. The application decodes and types `A`.

**Important:** The application groups detected sounds automatically. The sound count in each group determines the DOT and DASH sequence.

---

## 6. Complete Example: Typing MH2

| Character | Morse Code |
|---|---|
| M | `--` |
| H | `....` |
| 2 | `..---` |

Follow the Morse sequence for each character. Allow the application to decode each character before starting the next one.

---

## 7. Application Controls

| Control | Function |
|---|---|
| START | Start microphone listening |
| STOP | Stop microphone listening |
| CLEAR | Clear output, Morse sequence and counters |
| TYPING: ON | Enable automatic keyboard typing |
| TYPING: OFF | Disable automatic keyboard typing |
| AUTO CONNECT | Reconnect to an available microphone |
| MINI MODE | Switch to the compact interface |
| EXPAND | Return to the full interface |
| PIN: ON | Keep the application window on top |
| PIN: OFF | Disable always-on-top mode |

---

## 8. Sensitivity Settings

The application provides adjustable sound sensitivity from 1 to 10, including half-step values.

- **Lower values:** Require stronger sound signals.
- **Higher values:** Make the application more sensitive to sound.
- **Values around 8–10:** Can help detect softer finger snaps, depending on microphone quality and background noise.

Adjust the sensitivity slider according to your microphone and environment.

---

## 9. Important Timing Configuration

| Setting | Value |
|---|---:|
| DASH grouping window | 0.40 seconds |
| Letter decoding silence | 0.60 seconds |
| Sound detection cooldown | 0.12 seconds |
| Automatic microphone retry | 4 seconds |

These are the timing values configured in the application source code.

---

## 10. Installation Requirements

The Python source version requires the following packages:

- NumPy
- SoundDevice
- PyAutoGUI

Install them using:

```bash
py -m pip install --upgrade numpy sounddevice pyautogui
```

Tkinter is also required for the graphical interface and is normally included with standard Windows Python installations.

---

## 11. How to Launch the Application

The application supports two launch methods.

### Method 1: Using the Windows EXE

1. Open the application folder.
2. Find `MH2 HRIDOY.exe`.
3. Double-click the EXE file.
4. The application will launch.

No manual Python command is required. If the EXE is packaged with all required dependencies, Python does not need to be installed separately.

### Method 2: Using the Python Source File

1. Open the application folder in CMD or Terminal.
2. Make sure the required Python packages are installed.
3. Run:

```bash
py mh2_clap_snap_keyboard.py
```

Both methods are intended to provide the same application functionality.

---

## 12. Important Notes

- Keep your microphone connected and enabled.
- Allow microphone access in Windows.
- Use clear claps or finger snaps.
- Avoid excessive background noise.
- Adjust sensitivity according to your microphone.
- Make sure the target application or text field is ready to receive keyboard input.
- Keep TYPING enabled if you want decoded characters to be typed automatically.
- When TYPING is OFF, the application can still decode Morse sequences, but it will not send keyboard input.
- Unknown Morse sequences are displayed as `?` in the LAST KEY indicator and are not typed.
- The application automatically attempts to reconnect if microphone input is lost.

---

## Application Information

| Item | Details |
|---|---|
| Application | MH2 Clap-Snap Keyboard |
| Developer | MH2 HRIDOY |
| Programming Language | Python |
| GUI Framework | Tkinter |
| Audio Processing | NumPy, SoundDevice |
| Keyboard Automation | PyAutoGUI |
| Input Method | Microphone-based Clap/Snap Detection |
| Encoding System | Morse Code |
