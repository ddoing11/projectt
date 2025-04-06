import os

# 파일 경로 (필요하면 경로 수정)
file_path = "kiosk/static/js/voice_socket.js"

# 기존 인코딩을 시도해볼 리스트 (깨짐 방지용)
encodings_to_try = ['cp949', 'euc-kr', 'utf-8']

for enc in encodings_to_try:
    try:
        with open(file_path, 'r', encoding=enc) as f:
            content = f.read()
        print(f"[✔] Successfully read with encoding: {enc}")
        break
    except UnicodeDecodeError:
        continue
else:
    print("[✘] Failed to decode the file. Try opening it manually in VSCode.")
    exit()

# UTF-8로 다시 저장
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("[✔] File successfully converted to UTF-8.")
