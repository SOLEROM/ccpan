#!/usr/bin/env bash
set -euo pipefail

# tmuxRunner.sh
#
# Usage:
#   ./tmuxRunner.sh <server_name> <command_file> [session_to_attach]
#
# Examples:
#   ./tmuxRunner.sh test2 cmds.txt
#   ./tmuxRunner.sh test2 cmds.txt editor
#
# Command file format:
#   #session_name
#   <multi-line commands...>
#   #another_session
#   <multi-line commands...>
#
# Header rule is strict: '#name' with NO spaces after '#'.

usage() {
  cat <<'EOF'
Usage:
  tmuxRunner.sh <server_name> <command_file> [session_to_attach]

File format:
  #session_name
  <multi-line commands...>

Notes:
  - Resets the tmux server under: tmux -L <server_name> (kills all its sessions).
  - Creates one session per header. Each session has exactly one window.
  - If session_to_attach is provided, attaches to it. Otherwise, attaches to the first session.
EOF
  exit 2
}

[[ $# -ge 2 ]] || usage

SERVER="$1"
CMD_FILE="$2"
ATTACH_SESSION="${3:-}"

[[ -f "$CMD_FILE" ]] || { echo "ERROR: command file not found: $CMD_FILE" >&2; exit 1; }

TMUX=(tmux -L "$SERVER")

# Store per-session scripts somewhere stable (not /tmp), so tmux can run them later.
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tmuxRunner/${SERVER}"
mkdir -p "$CACHE_DIR"

declare -a SESS_LIST=()
declare -A SESS_SCRIPT=()

current_sess=""
tmp="$(mktemp)"
trap 'rm -f "$tmp" 2>/dev/null || true' EXIT

finalize_block() {
  local sess="$1"
  [[ -n "$sess" ]] || return 0

  if ! grep -q '[^[:space:]]' "$tmp"; then
    echo "ERROR: session '#$sess' has no command lines under it." >&2
    exit 1
  fi

  if [[ -n "${SESS_SCRIPT[$sess]:-}" ]]; then
    echo "ERROR: duplicate session header '#$sess' in file." >&2
    exit 1
  fi

  local out="$CACHE_DIR/${sess}.sh"
  {
    echo '#!/usr/bin/env bash'
    echo 'set -euo pipefail'
    cat "$tmp"
  } > "$out"
  chmod +x "$out"

  SESS_LIST+=("$sess")
  SESS_SCRIPT["$sess"]="$out"
}

: > "$tmp"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"  # CRLF-safe

  # Strict header: '#name' with no spaces
  if [[ "$line" =~ ^#[A-Za-z0-9_.-]+$ ]]; then
    finalize_block "$current_sess"
    current_sess="${line#\#}"
    : > "$tmp"
    continue
  fi

  # Ignore leading blank lines before first header
  if [[ -z "$current_sess" ]]; then
    [[ -z "${line//[[:space:]]/}" ]] && continue
    echo "ERROR: found command lines before any '#session_name' header." >&2
    exit 1
  fi

  printf '%s\n' "$line" >> "$tmp"
done < "$CMD_FILE"

finalize_block "$current_sess"

if [[ "${#SESS_LIST[@]}" -eq 0 ]]; then
  echo "ERROR: no sessions found in file. Expected headers like '#name'." >&2
  exit 1
fi

# Default attach session: first parsed session
if [[ -z "$ATTACH_SESSION" ]]; then
  ATTACH_SESSION="${SESS_LIST[0]}"
fi

# Hard reset the tmux server/socket (kills ALL sessions under -L SERVER)
if "${TMUX[@]}" has-session 2>/dev/null; then
  "${TMUX[@]}" kill-server
fi

# Create one session per block, each with a single window.
for sess in "${SESS_LIST[@]}"; do
  script_path="${SESS_SCRIPT[$sess]}"

  # Run the script; when it exits, keep an interactive shell open.
  inner="bash $(printf '%q' "$script_path"); exec bash -i"

  "${TMUX[@]}" new-session -d -s "$sess" -n "$sess" \
    "bash -lc $(printf '%q' "$inner")"
done

# Validate attach target exists
if ! "${TMUX[@]}" has-session -t "$ATTACH_SESSION" 2>/dev/null; then
  echo "ERROR: requested attach session '$ATTACH_SESSION' does not exist." >&2
  echo "Available sessions:" >&2
  "${TMUX[@]}" list-sessions -F '#S' >&2 || true
  exit 1
fi

# Attach (takes over terminal; detach with Ctrl-b d)
exec "${TMUX[@]}" attach -t "$ATTACH_SESSION"

