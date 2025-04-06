@echo off
echo [공유용] shared/ 폴더만 GitHub에 푸시합니다.

REM shared 폴더만 Git에 추가
git add shared/
git add .gitignore
git add README.md

REM 커밋 메시지 입력받기
set /p msg=공유용 커밋 메시지를 입력하세요:

git commit -m "%msg%"
git push

pause
