from flask import Flask, request, jsonify, send_file
import yt_dlp
import tempfile
import os
import logging
from werkzeug.utils import secure_filename
import re
from datetime import datetime

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def is_youtube_url(url):
    """Проверяет, является ли URL ссылкой на YouTube"""
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return youtube_regex.match(url) is not None

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "youtube-audio-downloader"
    })

@app.route('/download-audio', methods=['POST'])
def download_audio():
    """Скачивает аудио с YouTube и возвращает файл"""
    try:
        # Получаем данные из запроса
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                "error": "Missing 'url' parameter in request body"
            }), 400
        
        url = data['url']
        
        # Проверяем, что это YouTube URL
        if not is_youtube_url(url):
            return jsonify({
                "error": "Invalid YouTube URL"
            }), 400
        
        logger.info(f"Processing YouTube URL: {url}")
        
        # Создаем временную директорию
        with tempfile.TemporaryDirectory() as temp_dir:
            # Настройки для yt-dlp с обходом блокировок
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{temp_dir}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
                # Ограничения для безопасности
                'max_filesize': 50 * 1024 * 1024,  # 50MB max
                'max_downloads': 1,
                # Обход блокировок YouTube
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Accept-Encoding': 'gzip,deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                    'Connection': 'keep-alive',
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['hls', 'dash']
                    }
                }
            }
            
            # Скачиваем аудио
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                    title = info.get('title', 'audio')
                    duration = info.get('duration', 0)
                    
                    # Проверка длительности (максимум 30 минут)
                    if duration > 1800:
                        return jsonify({
                            "error": "Video too long. Maximum duration: 30 minutes"
                        }), 400
                        
                except Exception as e:
                    logger.error(f"yt-dlp error: {str(e)}")
                    return jsonify({
                        "error": f"Failed to download video: {str(e)}"
                    }), 500
            
            # Находим скачанный файл
            audio_file = None
            for file in os.listdir(temp_dir):
                if file.endswith('.wav'):
                    audio_file = os.path.join(temp_dir, file)
                    break
            
            if not audio_file or not os.path.exists(audio_file):
                return jsonify({
                    "error": "Audio file not found after download"
                }), 500
            
            # Получаем размер файла
            file_size = os.path.getsize(audio_file)
            
            logger.info(f"Successfully downloaded: {title} ({file_size} bytes)")
            
            # Возвращаем файл
            safe_filename = secure_filename(f"{title[:50]}.wav")
            return send_file(
                audio_file,
                as_attachment=True,
                download_name=safe_filename,
                mimetype='audio/wav'
            )
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}"
        }), 500

@app.route('/get-info', methods=['POST'])
def get_video_info():
    """Получает информацию о видео без скачивания"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                "error": "Missing 'url' parameter in request body"
            }), 400
        
        url = data['url']
        
        if not is_youtube_url(url):
            return jsonify({
                "error": "Invalid YouTube URL"
            }), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "title": info.get('title', 'Unknown'),
                "duration": info.get('duration', 0),
                "uploader": info.get('uploader', 'Unknown'),
                "view_count": info.get('view_count', 0),
                "upload_date": info.get('upload_date', 'Unknown'),
                "description": info.get('description', '')[:200] + '...' if info.get('description') else ''
            })
            
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        return jsonify({
            "error": f"Failed to get video info: {str(e)}"
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
