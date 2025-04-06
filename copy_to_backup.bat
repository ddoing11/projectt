@echo off
echo 🔁 전체 프로젝트를 backup/ 폴더로 복사합니다...

REM backup 폴더 없으면 생성
if not exist backup (
    mkdir backup
)

REM 폴더 복사 (venv는 제외)
if exist backend (
    xcopy /E /Y /I backend backup\backend
)
if exist kiosk (
    xcopy /E /Y /I kiosk backup\kiosk
)

REM 파일 복사
if exist manage.py (
    copy /Y manage.py backup\
)
if exist convert_encoding.py (
    copy /Y convert_encoding.py backup\
)
if exist requirements.txt (
    copy /Y requirements.txt backup\
)

echo ✅ venv 제외한 전체 백업 완료! 이제 commit_backup.bat 실행하면 GitHub에 백업됩니다.
pause
