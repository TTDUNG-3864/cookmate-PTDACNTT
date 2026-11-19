import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

# 1. Tự động tìm và nạp file .env ở thư mục hiện tại hoặc thư mục con
env_files = list(Path(".").rglob(".env"))
for env_path in env_files:
    load_dotenv(dotenv_path=env_path, override=True)

# 2. Lấy key (hỗ trợ cả GEMINI_API_KEY và GOOGLE_API_KEY) và lọc bỏ khoảng trắng/dấu ngoặc
raw_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
API_KEY = raw_key.strip().strip('"').strip("'")

# In kiểm tra nhanh xem script đang đọc được gì (ẩn phần giữa để bảo mật)
if not API_KEY:
    print("❌ KHÔNG TÌM THẤY KEY trong biến môi trường hay file .env nào!")
    print(f"Các file .env đã quét: {[str(p) for p in env_files]}")
    exit(1)
else:
    print(f"🔑 Đang dùng key: {API_KEY[:6]}...{API_KEY[-4:]} (Độ dài: {len(API_KEY)} ký tự)")

client = genai.Client(api_key=API_KEY)


def check_free_models():
    print("\nĐang lấy danh sách model từ Google AI Studio...\n")
    available_free_models = []

    try:
        models = list(client.models.list())
    except APIError as e:
        print(f"❌ Lỗi xác thực API Key ngay khi lấy danh sách model ({e.code}): {e.message}")
        print("👉 Key này đã bị khóa/xóa hoặc copy thiếu ký tự. Hãy vào https://aistudio.google.com/apikey tạo key mới!")
        return

    for model in models:
        supported_actions = getattr(model, "supported_actions", []) or []
        if "generateContent" not in supported_actions:
            continue

        model_name = model.name.replace("models/", "")
        print(f"Đang kiểm tra: {model_name:<35}", end=" -> ", flush=True)

        try:
            client.models.generate_content(
                model=model_name,
                contents="Hi",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            print("DÙNG ĐƯỢC (Free)")
            available_free_models.append(model_name)

        except APIError as e:
            if e.code == 429:
                print("Bị giới hạn / Yêu cầu trả phí (429)")
            elif e.code in (400, 403, 404):
                print(f"Không khả dụng ({e.code})")
            else:
                print(f"Lỗi API ({e.code}): {e.message}")
        except Exception as e:
            print(f"Lỗi không xác định: {e}")

        time.sleep(1.5)

    print("\n" + "=" * 50)
    print(f"TỔNG KẾT: Có {len(available_free_models)} model dùng được miễn phí:")
    for m in available_free_models:
        print(f" - {m}")


if __name__ == "__main__":
    check_free_models()