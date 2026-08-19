FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# yt-dlp 的 YouTube 提取需要外部 JavaScript runtime；Deno 是官方推荐运行时。
# 使用 Python 下载静态二进制，避免引入 apt/ffmpeg，保持镜像构建较轻。
ARG DENO_VERSION=2.3.3
ARG TARGETARCH=amd64
ARG DENO_BASE_URL=https://github.com/denoland/deno/releases/download
RUN DENO_VERSION="$DENO_VERSION" TARGETARCH="$TARGETARCH" DENO_BASE_URL="$DENO_BASE_URL" python - <<'PY'
import os
import stat
import urllib.request
import zipfile
from io import BytesIO

arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(
    os.environ.get("TARGETARCH", "amd64"), "x86_64"
)
version = os.environ.get("DENO_VERSION", "2.3.3")
base_url = os.environ.get("DENO_BASE_URL", "https://github.com/denoland/deno/releases/download").rstrip("/")
url = f"{base_url}/v{version}/deno-{arch}-unknown-linux-gnu.zip"
request = urllib.request.Request(url, headers={"User-Agent": "Docker/yt-dlp-build"})
with urllib.request.urlopen(request, timeout=120) as response:
    data = response.read()
with zipfile.ZipFile(BytesIO(data)) as archive:
    archive.extract("deno", "/usr/local/bin")
path = "/usr/local/bin/deno"
os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
PY

# 国内网络可指定镜像加速 pip，例如：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=""
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -r requirements.txt -i "$PIP_INDEX_URL"; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app

VOLUME ["/app/data"]

CMD ["python", "-m", "app.main"]
