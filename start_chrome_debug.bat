@echo off
echo =======================================================
echo STARTING CHROME WITH REMOTE DEBUGGING ENABLED (NEW PROFILE)
echo =======================================================
echo.
echo A NEW Chrome window will open.
echo Keep it open and navigate to Bet365 in it!
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --remote-allow-origins="*" --user-data-dir="%TEMP%\bet365_debug_profile"
exit
