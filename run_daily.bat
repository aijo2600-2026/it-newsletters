@echo off
chcp 65001 >nul
cd /d %USERPROFILE%\it-newsletter
set PYTHONUTF8=1
rem Scheduler context lacks interactive PATH. Use absolute python and add npm/python dirs.
set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
set "PATH=%USERPROFILE%\AppData\Roaming\npm;%USERPROFILE%\AppData\Local\Programs\Python\Python313;%PATH%"
rem Recipients come from your own local env (set RECIPIENTS / NEWSLETTER_EXTERNAL_TO
rem in a machine-level env var or a local, gitignored setup — never hardcode here).
"%PY%" oneshot.py >> run.log 2>&1
"%PY%" cleanup.py >> run.log 2>&1
exit /b 0
