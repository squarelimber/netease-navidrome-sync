FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

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
