#!/bin/bash
# The morning run: the nightly job plus a log and a Mac notification. launchd starts it at 4:00 and 9:00
# (see tools/com.sportsstocks.morning.plist). Running it twice is harmless: every game pays only once.
# By hand:  bash tools/morning.sh      Log: save/morning.log
cd "$(dirname "$0")/.." || exit 1
LOG=save/morning.log
mkdir -p save

notify() {  # title, message
  /usr/bin/osascript -e "display notification \"${2//\"/\'}\" with title \"$1\"" >/dev/null 2>&1
}

OUT=$(/usr/bin/python3 tools/nightly.py --quiet 2>&1)
CODE=$?
{
  echo "===== $(date '+%a %d %b %Y %H:%M') (exit $CODE)"
  echo "$OUT"
  echo
} >> "$LOG"

if [ $CODE -ne 0 ]; then
  FIRST=$(echo "$OUT" | grep -m1 -E "Stopped at|Error|error" || echo "$OUT" | tail -1)
  notify "Sports Stocks: overnight update stopped" "$FIRST. Nothing was paid for that day. Details in save/morning.log."
elif ! echo "$OUT" | grep -q "Nothing new to process"; then
  DAYS=$(echo "$OUT" | grep -cE "^[0-9]{4}-[0-9]{2}-[0-9]{2}:")
  CASH=$(echo "$OUT" | grep -E "^[0-9]{4}-[0-9]{2}-[0-9]{2}:" | tail -1 | sed -E 's/.*dividends (\$[0-9,.]+).*/\1/')
  BAD=$(echo "$OUT" | grep -c "MISMATCHES")
  MSG="Processed $DAYS game day(s). Dividends on the last: $CASH."
  [ "$BAD" -gt 0 ] && MSG="$MSG Hand check found mismatches: look at save/morning.log."
  notify "Sports Stocks: overnight update done" "$MSG"
fi
exit $CODE
