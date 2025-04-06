@echo off
echo [백업용] 전체 프로젝트를 GitHub에 푸시합니다.

REM 전체를 Git에 추가 (backup, shared, venv 등 포함)
git add .

REM 커밋 메시지 입력받기
set /p msg=백업 커밋 메시지를 입력하세요:

git commit -m "%msg%"
git push
git add backup/

set /p msg=커밋 메시지를 입력하세요 (예: 4/7 백업): 
git commit -m "%msg%"
git push

pause
