FROM python:3.11-slim
WORKDIR /app

# Install CPU-only torch FIRST. sentence-transformers otherwise drags in the
# default CUDA torch (~5-6GB of nvidia-* wheels) this service never uses — it
# only does CPU inference on all-MiniLM-L6-v2. Pre-installing the CPU build
# satisfies the torch requirement so the requirements install won't pull CUDA.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# pre-download the embedder so first request isn't slow / offline-safe
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
