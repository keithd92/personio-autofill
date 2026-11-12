# personio-autofill

Logs your usual working hours in Personio for you, once a day, through a real
browser session. It runs when you log in to your laptop (and after it wakes up), and
it never logs on holidays, public holidays or days you're off.

It drives the "Time tracking" card on your Personio home page, the same one you'd
fill in by hand. There's no Personio API key involved; it uses your own sign-in.

> **Your attendance record has to reflect the hours you actually worked** (Spain's
> *registro de jornada*). This logs the same hours every working day, so on days you
> work differently, fix the entry in Personio yourself. Entries stay editable while
> they're Pending.

## Before you start

You need:

- **Linux with systemd**: tested on Ubuntu with GNOME. Not macOS or Windows.
- **uv**, the Python tool. If `uv --version` doesn't work, install it, then open a new terminal:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- **Personio in English**: Personio → your profile → Settings → Language. The script
  reads labels like `8h 30m`. If Personio is in another language, it stops and tells
  you rather than guessing.
- **A "Time tracking" card on your Personio home page**, with Work start/end and Break
  times.

## Setup

1. Get the code:

   ```bash
   git clone <repo-url> ~/personio-autofill
   cd ~/personio-autofill
   ```

2. Run the installer. The first time, it installs dependencies, creates
   `config.toml` and stops:

   ```bash
   ./install.sh
   ```

3. Put your usual hours in `config.toml`. Each day must add up to your Personio
   target for that day (shown on your Attendance tab, e.g. `0h/8h 30m`):

   ```toml
   [days.mon]
   work = ["09:00", "18:00"]
   breaks = [["13:00", "13:30"]]   # 9h minus 30m = 8h 30m

   [days.fri]
   work = ["09:00", "15:00"]
   breaks = []                     # 6h
   ```

   Leave out days you never work (weekends are already left out).

4. Run the installer again:

   ```bash
   ./install.sh
   ```

   - A browser window opens. Sign in to Personio as you normally would (SSO, 2FA,
     whatever you use). When your home page has loaded, close the window. Your
     password never touches the script; only the browser session is kept, in
     `.profile/` inside this folder.
   - It does a **dry run** for today: fills in the card, takes a screenshot
     (`dumps/<date>-filled.png`) and does **not** submit. Weekends and days off say
     "nothing to do" instead.
   - It asks whether to turn on automatic logging. Say `y`.

That's it. From the next login or wake-up it logs on its own, and you get a desktop
notification each time it does.

## Check it's working

```bash
journalctl --user -u personio-autofill --since today
```

You'll see one of:

- `logged 09:00-18:00, ...`: done for today
- `already tracked ...`: you'd already logged today, so it left it alone
- `no target hours today (holiday/absence)`: day off, nothing logged

## Day to day

| Situation | What happens |
|---|---|
| Holiday, public holiday, full day off | Nothing is logged. |
| Half day off | Your hours don't match Personio's reduced target, so nothing is logged and you get a notification. Log that day by hand. |
| You already logged today | It leaves your entry alone. |
| A different day than usual | Fix the entry in Personio after it logs. It won't overwrite it. |
| Personio sign-in expired | You get a notification. Run `uv run login.py` in this folder and sign in again. |
| Something else breaks | You get one notification a day, and it keeps retrying. Look at the `journalctl` output above. |

Once today's outcome is settled, later runs that day exit straight away without
opening Personio.

## Commands

Run these from this folder:

```bash
uv run fill.py               # dry run for today: fills the card, screenshot, no submit
uv run fill.py --submit      # log today now
uv run fill.py --headed      # dry run in a visible browser, to watch it
uv run login.py              # sign in again
./install.sh --uninstall     # turn automatic logging off (keeps config and sign-in)
```

To update: `git pull`, then `./install.sh`.

## How it works

1. On each run it checks today in two places in Personio:
   - the **Attendance tab**, where working days show tracked/target hours (`0h/8h 30m`)
     and days off show no target;
   - the **Time tracking card** on the home page.
2. It only logs if both show the same target and your `config.toml` hours add up to
   it.
3. It fills Work and Break in the card and checks the card shows the target.
4. It submits, reloads the page and checks Personio saved the hours.

Personio only lets you log today (future days are locked), so it can't catch up a
missed day. If the laptop stays shut all day, log that day by hand.

**Triggers:** a systemd user service starts at desktop login. A timer runs it every
30 minutes, 08:00–20:30 on weekdays, because opening the lid isn't a login. Both are
set up by `install.sh` and point at this folder, so if you move the folder, run
`./install.sh` again.

**One Personio quirk:** the card crashes if a break time briefly passes through an
invalid value (typing "13" goes through "01" first). So the script changes times
with the arrow keys instead of typing them.

## What's in this folder

| File | Purpose |
|---|---|
| `install.sh` | setup, re-run safe |
| `fill.py` | the daily run |
| `login.py` | one-time sign-in window |
| `explore.py` | dumps a Personio page (screenshot + structure) for building new automations |
| `config.example.toml` | template for your `config.toml` |
| `systemd/*.in` | templates for the login service and the timer |

Created on your machine and never committed: `config.toml`, `.profile/` (your
Personio session, keep it private), `state/` (what happened each day), `dumps/`
(screenshots).
