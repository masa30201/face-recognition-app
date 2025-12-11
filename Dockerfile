FROM python:3.11-slim

# システムパッケージのインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# dlibのビルドに必要なパッケージを先にインストール
RUN pip install --no-cache-dir cmake packaging setuptools wheel

# dlibを最新版でインストール
RUN git clone https://github.com/davisking/dlib.git && \
    cd dlib && \
    python setup.py install && \
    cd .. && \
    rm -rf dlib

# 依存関係のインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルのコピー
COPY . .

# ポートの公開
EXPOSE 5000

# アプリケーションの起動
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]