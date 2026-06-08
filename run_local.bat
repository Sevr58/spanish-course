@echo off
REM Локальный сервер для уроков испанского.
REM Нужен для работы микрофона (Web Speech API требует https:// или localhost).
REM Дважды кликни этот файл — откроется http://localhost:8000/

cd /d "%~dp0"
echo.
echo  Запускаю локальный сервер для уроков испанского...
echo  Открой в браузере: http://localhost:8000/
echo.
echo  Чтобы остановить — закрой это окно.
echo.

REM Откроем браузер на дашборде
start "" "http://localhost:8000/index.html"

REM Запустим Python http.server (Python должен быть установлен)
python -m http.server 8000
