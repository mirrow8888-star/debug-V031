"""建置階段預先下載嵌入模型，避免服務啟動時才下載。"""
import os
from fastembed import TextEmbedding

TextEmbedding(model_name=os.getenv("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
              cache_dir=os.getenv("FASTEMBED_CACHE_PATH") or None)
print("embedding model cached")
