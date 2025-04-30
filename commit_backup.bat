@echo off
echo [백업용] main 브랜치에 전체 프로젝트를 GitHub에 푸시합니다.

REM main 브랜치로 전환
git checkout main

REM 전체를 Git에 추가
git add .

REM 커밋 메시지 입력받기
set /p msg=백업 커밋 메시지를 입력하세요: 

REM 커밋 및 main 브랜치에 푸시
git commit -m "%msg%"
git push origin main

pause
