#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import mimetypes

# ✅ .js 파일을 정확하게 application/javascript로 인식하도록 설정
mimetypes.add_type("application/javascript", ".js", True)

# ✅ backend 경로를 모듈 경로로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.aptitude.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
