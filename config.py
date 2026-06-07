import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
MODEL_PATH = os.getenv("MODEL_PATH", "./model.gguf")
N_CTX = int(os.getenv("N_CTX", 2048))
N_THREADS = int(os.getenv("N_THREADS", 4))
