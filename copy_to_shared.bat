@echo off
echo 🔁 공유용 파일을 shared/ 폴더로 복사합니다...

REM shared 폴더가 없으면 생성
if not exist shared (
    mkdir shared
)

REM 폴더 복사
xcopy /E /Y /I backend shared\backend
xcopy /E /Y /I kiosk shared\kiosk

REM 파일 복사
copy /Y manage.py shared\
copy /Y requirements.txt shared\

echo ✅ 복사 완료! 이제 commit_shared.bat 실행해서 GitHub에 푸시하세요.
pause
