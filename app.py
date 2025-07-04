import os
import uuid
import subprocess
import wave
import json
from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS
from werkzeug.utils import secure_filename
from stegano import lsb

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
# Konfigurasi
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
ALLOWED_EXTENSIONS = {
    'video': ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm'],
    'audio': ['wav', 'mp3', 'flac']
}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONVERTED_FOLDER'] = CONVERTED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB

# Buat folder jika belum ada
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

def allowed_file(filename, file_type='video'):
    """Cek ekstensi file yang diizinkan"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS[file_type]

def generate_unique_filename(extension):
    """Hasilkan nama file unik"""
    return f"{uuid.uuid4().hex}.{extension}"

def cleanup_file(filepath):
    """Hapus file setelah selesai diproses"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        app.logger.error(f"Error deleting file {filepath}: {str(e)}")

@app.route('/convert', methods=['POST'])
def convert_video():
    """Endpoint untuk konversi video"""
    # Validasi request
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    output_format = request.form.get('output_format', 'mp4')
    sample_rate = request.form.get('sample_rate', '30')
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    # Simpan file yang diunggah
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)
    
    # Buat nama file output
    output_filename = generate_unique_filename(output_format)
    output_path = os.path.join(app.config['CONVERTED_FOLDER'], output_filename)
    
    try:
        # Konversi video menggunakan FFmpeg
        command = [
            'ffmpeg',
            '-i', input_path,
            '-r', sample_rate,
            '-c:v', 'libx264' if output_format != 'gif' else 'gif',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac' if output_format != 'gif' else None,
            '-b:a', '128k' if output_format != 'gif' else None,
            '-y', output_path
        ]
        # Hapus elemen None dari command
        command = [c for c in command if c is not None]
        
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            app.logger.error(f"FFmpeg error: {result.stderr}")
            cleanup_file(input_path)
            return jsonify({'error': 'Video conversion failed'}), 500
        
        # Set cleanup setelah response dikirim
        @after_this_request
        def cleanup(response):
            cleanup_file(input_path)
            cleanup_file(output_path)
            return response
        
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    
    except Exception as e:
        app.logger.error(f"Conversion error: {str(e)}")
        cleanup_file(input_path)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/compress', methods=['POST'])
def compress_video():
    """Endpoint untuk kompresi video"""
    # Validasi request
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    codec = request.form.get('codec', 'libx264')
    method = request.form.get('method', 'crf')
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    # Simpan file yang diunggah
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)
    
    # Buat nama file output
    output_filename = generate_unique_filename('mp4')
    output_path = os.path.join(app.config['CONVERTED_FOLDER'], output_filename)
    
    try:
        # Konfigurasi kompresi berdasarkan metode
        compression_params = []
        if method == 'crf':  # Constant Rate Factor
            compression_params = ['-crf', '28']
        elif method == 'vbr':  # Variable Bitrate
            compression_params = ['-b:v', '1M', '-maxrate', '1.5M', '-bufsize', '2M']
        elif method == 'cbr':  # Constant Bitrate
            compression_params = ['-b:v', '1M']
        elif method == 'size':  # Target Size (contoh untuk 10MB)
            compression_params = ['-fs', '10M']
        
        # Kompres video menggunakan FFmpeg
        command = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', codec,
            '-preset', 'slow',
            '-movflags', '+faststart',
            '-y', output_path
        ] + compression_params
        
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            app.logger.error(f"FFmpeg error: {result.stderr}")
            cleanup_file(input_path)
            return jsonify({'error': 'Video compression failed'}), 500
        
        # Set cleanup setelah response dikirim
        @after_this_request
        def cleanup(response):
            cleanup_file(input_path)
            cleanup_file(output_path)
            return response
        
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    
    except Exception as e:
        app.logger.error(f"Compression error: {str(e)}")
        cleanup_file(input_path)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/steganography/encode', methods=['POST'])
def encode_audio():
    """Endpoint untuk menyembunyikan pesan dalam audio (WAV)"""
    # Validasi request
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    message = request.form.get('message', '')
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename, 'audio'):
        return jsonify({'error': 'Invalid file type'}), 400
    
    if not message:
        return jsonify({'error': 'No message provided'}), 400
    
    # Simpan file yang diunggah
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)
    
    # Buat nama file output
    output_filename = generate_unique_filename('wav')
    output_path = os.path.join(app.config['CONVERTED_FOLDER'], output_filename)
    
    try:
        # Konversi ke WAV jika perlu
        if not input_path.lower().endswith('.wav'):
            wav_path = os.path.join(app.config['UPLOAD_FOLDER'], generate_unique_filename('wav'))
            
            # Konversi ke WAV menggunakan FFmpeg
            command = [
                'ffmpeg',
                '-i', input_path,
                '-ar', '44100',
                '-ac', '1',
                '-y', wav_path
            ]
            
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode != 0:
                app.logger.error(f"FFmpeg error: {result.stderr}")
                cleanup_file(input_path)
                return jsonify({'error': 'Audio conversion failed'}), 500
            
            input_path = wav_path
        
        # Sembunyikan pesan dalam file audio
        secret = lsb.hide(input_path, message)
        secret.save(output_path)
        
        # Set cleanup setelah response dikirim
        @after_this_request
        def cleanup(response):
            cleanup_file(input_path)
            cleanup_file(output_path)
            return response
        
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    
    except Exception as e:
        app.logger.error(f"Encoding error: {str(e)}")
        cleanup_file(input_path)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/steganography/decode', methods=['POST'])
def decode_audio():
    """Endpoint untuk mengekstrak pesan dari audio (WAV)"""
    # Validasi request
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename, 'audio'):
        return jsonify({'error': 'Invalid file type'}), 400
    
    # Simpan file yang diunggah
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)
    
    try:
        # Konversi ke WAV jika perlu
        if not input_path.lower().endswith('.wav'):
            wav_path = os.path.join(app.config['UPLOAD_FOLDER'], generate_unique_filename('wav'))
            
            # Konversi ke WAV menggunakan FFmpeg
            command = [
                'ffmpeg',
                '-i', input_path,
                '-ar', '44100',
                '-ac', '1',
                '-y', wav_path
            ]
            
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode != 0:
                app.logger.error(f"FFmpeg error: {result.stderr}")
                cleanup_file(input_path)
                return jsonify({'error': 'Audio conversion failed'}), 500
            
            input_path = wav_path
        
        # Ekstrak pesan dari file audio
        message = lsb.reveal(input_path)
        
        # Set cleanup setelah response dikirim
        @after_this_request
        def cleanup(response):
            cleanup_file(input_path)
            return response
        
        return jsonify({'message': message})
    
    except Exception as e:
        app.logger.error(f"Decoding error: {str(e)}")
        cleanup_file(input_path)
        return jsonify({'error': 'No hidden message found or file corrupted'}), 400

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled Exception: {str(e)}")
    return jsonify(error="Internal server error"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    
