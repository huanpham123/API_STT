import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import threading
import wave
import io
from datetime import datetime, timedelta

# --- Khởi tạo Flask App ---
app = Flask(__name__, template_folder="templates")
app.logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

# --- Cấu hình ---
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn upload 5MB
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

# --- Biến toàn cục để theo dõi trạng thái ---
last_request_time = datetime.now()
SERVER_TIMEOUT = timedelta(minutes=15)  # Thời gian không hoạt động trước khi bị tắt

# --- File WAV im lặng để Warm-up Recognizer ---
SILENT_WAV_PATH = os.path.join(TMP_DIR, "silent_warmup_stt.wav")

def create_silent_wav(path, duration=0.1, sample_rate=16000):
    """Tạo một file WAV im lặng ngắn."""
    try:
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.setnframes(int(duration * sample_rate))
            wf.setcomptype("NONE", "not compressed")
            wf.writeframes(b'\x00\x00' * int(duration * sample_rate))
        app.logger.info(f"Created silent WAV at: {path}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to create silent WAV: {e}")
        return False

if not create_silent_wav(SILENT_WAV_PATH):
    app.logger.warning("Silent WAV creation failed. Warm-up may be affected.")

# --- Pool cho Recognizer ---
class RecognizerPool:
    def __init__(self, pool_size=3, max_pool_size=10):
        self.initial_pool_size = pool_size
        self.max_pool_size = max_pool_size
        self.pool = []
        self.lock = threading.Lock()
        self._initialize_pool()
        self.warm_up_all_recognizers_in_pool()

    def _initialize_pool(self):
        with self.lock:
            self.pool = [sr.Recognizer() for _ in range(self.initial_pool_size)]
        app.logger.info(f"Initialized RecognizerPool with {self.initial_pool_size} instances")

    def _warm_up_single_recognizer(self, recognizer):
        try:
            if os.path.exists(SILENT_WAV_PATH):
                with sr.AudioFile(SILENT_WAV_PATH) as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.05)
        except Exception as e:
            app.logger.error(f"Warm-up failed for recognizer: {e}")

    def warm_up_all_recognizers_in_pool(self):
        app.logger.info("Starting recognizer pool warm-up...")
        threads = []
        
        with self.lock:
            current_recognizers = list(self.pool)

        for r_instance in current_recognizers:
            thread = threading.Thread(
                target=self._warm_up_single_recognizer,
                args=(r_instance,),
                name=f"WarmUpThread-{id(r_instance)}"
            )
            thread.start()
            threads.append(thread)
        
        for thread in threads:
            thread.join(timeout=5.0)
        app.logger.info(f"Completed recognizer pool warm-up. Active threads: {threading.active_count()}")

    def get_recognizer(self):
        with self.lock:
            if self.pool:
                return self.pool.pop(0)
            else:
                app.logger.info("Pool empty, creating new recognizer")
                return sr.Recognizer()
    
    def return_recognizer(self, recognizer):
        with self.lock:
            if len(self.pool) < self.max_pool_size:
                self.pool.append(recognizer)

# Khởi tạo pool
recognizer_pool = RecognizerPool()

# --- Background Tasks ---
def background_keepalive():
    """Nhiệm vụ nền để giữ server hoạt động"""
    while True:
        time.sleep(60)  # Kiểm tra mỗi phút
        if (datetime.now() - last_request_time) > SERVER_TIMEOUT:
            app.logger.info("No recent activity. Warming up to prevent cold start...")
            recognizer_pool.warm_up_all_recognizers_in_pool()
            # Giả lập request để giữ server hoạt động
            with app.test_request_context('/api/keepalive'):
                try:
                    app.preprocess_request()
                    app.logger.info("Keepalive request simulated")
                except Exception as e:
                    app.logger.error(f"Keepalive simulation failed: {e}")

# Khởi chạy background thread
keepalive_thread = threading.Thread(
    target=background_keepalive,
    daemon=True,
    name="BackgroundKeepalive"
)
keepalive_thread.start()

# --- Các Flask Route ---
@app.before_request
def update_last_request_time():
    """Cập nhật thời gian request cuối cùng"""
    global last_request_time
    last_request_time = datetime.now()

@app.route("/", methods=["GET"])
def index_route():
    return render_template("test.html")

@app.route("/api/ping", methods=["GET"])
def ping_route():
    ping_type = "Unknown"
    if request.headers.get('X-Health-Check') == 'true':
        ping_type = "Health-Check"
    elif request.headers.get('X-Keep-Alive') == 'true':
        ping_type = "Keep-Alive"
    elif request.headers.get('X-ESP32-Ping') == 'true':
        ping_type = "ESP32 Ping"
    
    app.logger.info(f"GET /api/ping from {request.remote_addr} (Type: {ping_type})")
    
    with recognizer_pool.lock:
        current_pool_size = len(recognizer_pool.pool)

    return jsonify({
        "status": "alive",
        "timestamp": time.time(),
        "recognizer_pool_size": current_pool_size,
        "message": "STT server is ready",
        "active_threads": threading.active_count(),
        "last_activity": last_request_time.isoformat()
    }), 200

@app.route("/api/wakeup", methods=["GET"])
def wakeup_route():
    """Route đặc biệt để đánh thức server"""
    app.logger.info(f"Wake-up request from {request.remote_addr}")
    
    # Warm-up recognizer pool ngay lập tức
    recognizer_pool.warm_up_all_recognizers_in_pool()
    
    return jsonify({
        "status": "awake",
        "message": "Server has been woken up and is ready",
        "timestamp": time.time(),
        "pool_size": len(recognizer_pool.pool)
    }), 200

@app.route("/api/transcribe", methods=["POST"])
def transcribe_route():
    request_id = str(uuid.uuid4())
    process_start_time = time.perf_counter()
    app.logger.info(f"[ReqID:{request_id}] POST /api/transcribe from {request.remote_addr}")

    if "audio_data" not in request.files:
        return jsonify({"error": "Missing audio file", "transcript": ""}), 400

    audio_file = request.files["audio_data"]

    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        return jsonify({"error": "Invalid file type, .wav only", "transcript": ""}), 400

    temp_filename = f"{request_id}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)
    transcript_text = ""
    final_status_code = 200

    try:
        audio_file.save(temp_path)
        recognizer_instance = recognizer_pool.get_recognizer()
        
        try:
            with sr.AudioFile(temp_path) as source:
                audio_data = recognizer_instance.record(source)
            
            try:
                transcript_text = recognizer_instance.recognize_google(audio_data, language="vi-VN")
            except sr.UnknownValueError:
                transcript_text = ""
            except sr.RequestError as e:
                transcript_text = f"[API Error: {e}]"
                final_status_code = 503
            except Exception as e_rec:
                transcript_text = "[Unknown processing error]"
                final_status_code = 500
        finally:
            recognizer_pool.return_recognizer(recognizer_instance)

    except Exception as e_general:
        return jsonify({"error": f"Server error: {str(e_general)}", "transcript": ""}), 500

    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e_remove:
                app.logger.error(f"Failed to remove temp file: {e_remove}")

        process_end_time = time.perf_counter()
        app.logger.info(f"[ReqID:{request_id}] Processed in {process_end_time - process_start_time:.4f}s")

    return jsonify({"transcript": transcript_text, "error": None}), final_status_code

# --- Main Execution ---
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, threaded=True)
