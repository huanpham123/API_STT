from flask import Flask, request, render_template, jsonify
import os, requests
from werkzeug.utils import secure_filename

app = Flask(__name__)
os.makedirs('uploads', exist_ok=True)

@app.route('/')
def index():
    return render_template('test.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    # kiểm tra có file gửi lên không
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({'error': 'Vui lòng chọn file âm thanh'}), 400

    f = request.files['file']
    fn = secure_filename(f.filename)
    save_path = os.path.join('uploads', fn)
    f.save(save_path)

    # gọi Deepgram
    dg = requests.post(
        'https://api.deepgram.com/v1/listen',
        headers={
            'Authorization': 'Token 95e26fe061960fecb8fc532883f92af0641b89d0',
            'Content-Type': f'audio/{fn.rsplit(".",1)[-1]}'
        },
        data=open(save_path, 'rb'),
        params={'language': 'vi', 'model': 'nova-2'}
    )

    if dg.status_code != 200:
        return jsonify({'error': f'Deepgram lỗi: {dg.text}'}), dg.status_code

    # trích transcript từ response
    transcript = dg.json()['results']['channels'][0]['alternatives'][0]['transcript']
    return jsonify({'transcript': transcript})

if __name__ == '__main__':
    app.run(debug=True)
