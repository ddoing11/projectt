# projectt 🎤 키오스크 음성인식 시스템

## 소개
이 프로젝트는 음성 명령 기반의 키오스크 시스템입니다. 시각장애인 및 고령층을 위한 접근성 중심 설계를 목표로 합니다.

## 사용 기술
- Python
- Django
- Whisper API
- WebRTC (실시간 음성 인식)
- MySQL
- HTML/CSS

## 시작하기
```bash
# 1. 가상환경 생성
python -m venv venv

# 2. 가상환경 활성화 (Windows 기준)
venv\Scripts\activate

# 3. 필요한 패키지 설치
pip install -r requirements.txt

# 4. 서버 실행
python manage.py runserver

```


## 📁 폴더 안내

- 👉 [공유용 코드 (shared 폴더)](https://github.com/ddoing11/projectt/tree/main/shared)  
  팀원들과 협업할 때 사용하는 주요 코드입니다.

- 🔐 [개인 백업용 코드 (backup 폴더)](https://github.com/ddoing11/projectt/tree/main/backup)  
  전체 프로젝트 백업본으로, `venv/` 등도 포함되어 있을 수 있습니다.


## 공유할때

    ./copy_to_shared.bat  
    ./commit_shared.bat  

## 백업할 때

    ./copy_to_backup.bat  
    ./commit_backup.bat  

## requirements.txt 갱신할 때

    pip freeze > requirements.txt  
    git add requirements.txt  
    git commit -m "📦 패키지 목록 업데이트"  
    git push  
