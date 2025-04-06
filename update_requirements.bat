@echo off
echo 📦 requirements.txt를 현재 가상환경 기준으로 업데이트합니다...

pip freeze > requirements.txt

git add requirements.txt
set /p msg=커밋 메시지를 입력하세요 (예: 패키지 추가됨): 
git commit -m "📦 requirements.txt 업데이트: %msg%"
git push

echo ✅ 업데이트 및 GitHub 푸시 완료!
pause
