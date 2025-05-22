from flask import Flask, request, render_template, jsonify
import requests
import os

app = Flask(__name__)

# Sử dụng thư mục /tmp để lưu trữ tệp tạm thời
UPLOAD_FOLDER = '/tmp'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DEEPGRAM_API_KEY = "95e26fe061960fecb8fc532883f92af0641b89d0"

@app.route('/')
def index():
    return render_template('test.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'Không có file âm thanh'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'Chưa chọn file'}), 400

    filename = f.filename
    path = os.path.join(UPLOAD_FOLDER, filename)
    f.save(path)

    # Gửi nội dung file lên Deepgram
    with open(path, 'rb') as audio_file:
        dg_resp = requests.post(
            'https://api.deepgram.com/v1/listen',
            headers={
                'Authorization': f'Token {DEEPGRAM_API_KEY}',
                'Content-Type': f'audio/{filename.rsplit('.', 1)[-1]}'
            },
            data=audio_file,
            params={
                'language': 'vi',
                'model': 'nova-2'
            }
        )

    if dg_resp.status_code != 200:
        return jsonify({'error': 'Deepgram lỗi: ' + dg_resp.text}), dg_resp.status_code

    result = dg_resp.json()
    transcript = result.get('results', {})\
                       .get('channels', [{}])[0]\
                       .get('alternatives', [{}])[0]\
                       .get('transcript', '')

    return jsonify({
        'message': 'File đã upload và chuyển thành văn bản',
        'transcript': transcript
    })

if __name__ == '__main__':
    app.run(debug=True)
