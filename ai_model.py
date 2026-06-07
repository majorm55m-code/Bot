import asyncio
from llama_cpp import Llama
from config import MODEL_PATH, N_CTX, N_THREADS

# تحميل النموذج مرة واحدة
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=N_CTX,
    n_threads=N_THREADS,
    verbose=False
)

async def ask_ai(prompt: str) -> str:
    try:
        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(
            None,
            lambda: llm(
                prompt,
                max_tokens=500,
                temperature=0.7,
                stop=["<|im_end|>", "Human:"],
            )
        )
        return output["choices"][0]["text"].strip()
    except Exception as e:
        return f"⚠️ خطأ في النموذج المحلي: {e}"
