#!/bin/bash
echo "======================================================="
echo "STARTING CHROME WITH REMOTE DEBUGGING ENABLED (NEW PROFILE)"
echo "======================================================="
echo ""
echo "A NEW Chrome window will open."
echo "Keep it open and navigate to Bet365 in it!"
echo ""

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --remote-allow-origins="*" \
  --user-data-dir="/tmp/bet365_debug_profile" &

exit 0
