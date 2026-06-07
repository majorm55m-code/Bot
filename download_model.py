import os
from huggingface_hub import hf_hub_download

MODEL_REPO = os.getenv("MODEL_REPO", "TheBloke/DeepSeek-R1-Distill-Qwen-7B-GGUF")
MODEL_FILENAME = os.getenv("MODEL_FILENAME", "deepseek-r1-distill-qwen-7b.Q4_K_M.gguf")
MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/model.gguf")

if not os.path.exists(MODEL_PATH):
    print(f"📥 جاري تحميل النموذج إلى {MODEL_PATH}...")
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=MODEL_REPO,
        filename=MODEL_FILENAME,
        local_dir=os.path.dirname(MODEL_PATH),
        local_dir_use_symlinks=False,
    )
    if downloaded != MODEL_PATH:
        os.rename(downloaded, MODEL_PATH)
    print("✅ اكتمل التحميل")
else:
    print("ℹ️ النموذج موجود مسبقاً")
