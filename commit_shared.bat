@echo off
echo [공유용] shared 브랜치에 전체 프로젝트를 GitHub에 푸시합니다.

REM shared 브랜치로 전환
git checkout shared

REM 변경 사항 전체 추가
git add .

REM 커밋 메시지 입력 받기
set /p msg=공유 커밋 메시지를 입력하세요: 

REM 커밋 및 push
git commit -m "%msg%"
git push origin shared

pause
