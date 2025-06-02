# Sử dụng Python 3.9-slim
FROM python:3.9-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy requirements trước để tận dụng cache
COPY requirements.txt /app/

# Cài các package Python
RUN pip install --no-cache-dir -r requirements.txt

# Nếu bạn cần thư viện hệ thống (ví dụ để xử lý audio), có thể thêm ở đây:
# RUN apt-get update && \
#     apt-get install -y ffmpeg libsndfile1 && \
#     rm -rf /var/lib/apt/lists/*

# Copy toàn bộ mã nguồn vào container
COPY . /app

# Tạo thư mục tạm
RUN mkdir -p /tmp

# Expose port 8080 (Fly sẽ map port public 80/443 vào đây)
EXPOSE 8080

# Chạy Gunicorn với 4 worker, mỗi worker 2 thread
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--threads", "2", "test:app"]
