#!/usr/bin/env bash
# Set up personio-autofill: dependencies, config, Personio sign-in, and the
# login/wake-up triggers. Safe to run again at any time.
#
#   ./install.sh               full setup
#   ./install.sh --no-service  everything except the automatic triggers
#   ./install.sh --uninstall   remove the automatic triggers
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(pwd)"
NAME=personio-autofill
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Removing the automatic triggers"
  systemctl --user disable --now "$NAME.timer" "$NAME.service" 2>/dev/null || true
  rm -f "$UNIT_DIR/$NAME.service" "$UNIT_DIR/$NAME.timer"
  systemctl --user daemon-reload
  echo "Done. Your config, sign-in (.profile/) and this folder are untouched."
  exit 0
fi

[[ "$(uname -s)" == "Linux" ]] || die "Linux only for now (the triggers use systemd)."
UV="$(command -v uv || true)"
[[ -n "$UV" ]] || die "uv isn't installed. Install it with:
  curl -LsSf https://astral.sh/uv/install.sh | sh
then open a new terminal and run ./install.sh again."

step "Installing Python dependencies"
"$UV" sync

step "Installing the Chromium browser Playwright drives"
"$UV" run playwright install chromium || die "Chromium install failed. If it mentions missing libraries, run:
  sudo $UV run playwright install-deps chromium
then ./install.sh again."

if [[ ! -f config.toml ]]; then
  cp config.example.toml config.toml
  step "Created config.toml"
  echo "Set your usual hours in $DIR/config.toml (they must add up to your"
  echo "Personio target for each day), then run ./install.sh again."
  exit 0
fi

if [[ ! -f .profile/personio_url ]]; then
  step "Signing in to Personio"
  echo "A browser window will open. Sign in as normal, wait for your Personio"
  echo "home page, then close the window."
  "$UV" run login.py
  [[ -f .profile/personio_url ]] || die "Sign-in wasn't saved. Run ./install.sh again."
fi

step "Dry run for today (fills the form, does not submit)"
"$UV" run fill.py || true

[[ "${1:-}" == "--no-service" ]] && { echo; echo "Skipped the automatic triggers (--no-service)."; exit 0; }
command -v systemctl >/dev/null || die "systemctl not found; run fill.py by hand instead."

step "Automatic logging"
echo "This logs today's hours at desktop login, and every 30 minutes on weekdays"
echo "(08:00-20:30) after the laptop wakes up, at most once a day."
read -r -p "Turn it on? [y/N] " answer
if [[ ! "$answer" =~ ^[Yy] ]]; then
  echo "Left off. Run ./install.sh again whenever you want it."
  exit 0
fi

mkdir -p "$UNIT_DIR"
for unit in service timer; do
  sed -e "s|@DIR@|$DIR|g" -e "s|@UV@|$UV|g" "systemd/$NAME.$unit.in" > "$UNIT_DIR/$NAME.$unit"
done
systemctl --user daemon-reload
systemctl --user enable "$NAME.service" "$NAME.timer"
systemctl --user start "$NAME.timer"

step "All set"
echo "Check what it did:  journalctl --user -u $NAME --since today"
echo "Turn it off:        ./install.sh --uninstall"
