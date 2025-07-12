from flask import Flask, request, jsonify, send_file, Response
import requests
import tempfile
import os
import logging
import re
from datetime import datetime
import json

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def is_youtube_url(url):
    """Проверяет, является ли URL ссылкой на YouTube"""
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return youtube_regex.match(url) is not None

def extract_video_id(url):
    """Извлекает ID видео из YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        r'youtube\.com\/watch\?.*v=([^&\n?#]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "youtube-proxy-service"
    })

@app.route('/download-audio', methods=['POST'])
def download_audio():
    """Скачивает аудио через внешние сервисы"""
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
        
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({
                "error": "Could not extract video ID"
            }), 400
        
        logger.info(f"Processing video ID: {video_id}")
        
        # Пробуем несколько методов
        methods = [
            method_cobalt,
            method_y2mate,
            method_direct_download
        ]
        
        for i, method in enumerate(methods, 1):
            try:
                logger.info(f"Trying method {i}/{len(methods)}")
                result = method(video_id, url)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Method {i} failed: {str(e)}")
                continue
        
        return jsonify({
            "error": "All download methods failed. YouTube may have blocked access."
        }), 500
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": f"Internal server error: {str(e)}"
        }), 500

def method_cobalt(video_id, url):
    """Метод через Cobalt API"""
    try:
        api_url = "https://api.cobalt.tools/api/json"
        
        payload = {
            "url": url,
            "vCodec": "h264",
            "vQuality": "720",
            "aFormat": "mp3",
            "filenamePattern": "basic",
            "isAudioOnly": True
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("status") == "success" and "url" in result:
                audio_url = result["url"]
                
                # Скачиваем аудио
                audio_response = requests.get(audio_url, timeout=60)
                
                if audio_response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                        temp_file.write(audio_response.content)
                        temp_file.flush()
                        
                        return send_file(
                            temp_file.name,
                            as_attachment=True,
                            download_name=f"youtube_audio_{video_id}.mp3",
                            mimetype='audio/mpeg'
                        )
        
        return None
        
    except Exception as e:
        logger.error(f"Cobalt method failed: {str(e)}")
        return None

def method_y2mate(video_id, url):
    """Метод через Y2mate API"""
    try:
        # Получаем информацию о видео
        info_url = "https://www.y2mate.com/mates/analyze/ajax"
        
        info_data = {
            "url": url,
            "q_auto": 0,
            "ajax": 1
        }
        
        info_response = requests.post(info_url, data=info_data, timeout=30)
        
        if info_response.status_code == 200:
            info_result = info_response.json()
            
            if info_result.get("status") == "ok":
                # Ищем аудио формат
                links = info_result.get("links", {}).get("mp3", {})
                
                if links:
                    # Берем первый доступный формат
                    format_key = list(links.keys())[0]
                    format_data = links[format_key]
                    
                    # Получаем ссылку на скачивание
                    convert_url = "https://www.y2mate.com/mates/convert"
                    
                    convert_data = {
                        "type": "youtube",
                        "vid": video_id,
                        "k": format_data.get("k"),
                        "ajax": 1
                    }
                    
                    convert_response = requests.post(convert_url, data=convert_data, timeout=30)
                    
                    if convert_response.status_code == 200:
                        convert_result = convert_response.json()
                        
                        if convert_result.get("status") == "ok":
                            download_url = convert_result.get("dlink")
                            
                            if download_url:
                                audio_response = requests.get(download_url, timeout=60)
                                
                                if audio_response.status_code == 200:
                                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                                        temp_file.write(audio_response.content)
                                        temp_file.flush()
                                        
                                        return send_file(
                                            temp_file.name,
                                            as_attachment=True,
                                            download_name=f"youtube_audio_{video_id}.mp3",
                                            mimetype='audio/mpeg'
                                        )
        
        return None
        
    except Exception as e:
        logger.error(f"Y2mate method failed: {str(e)}")
        return None

def method_direct_download(video_id, url):
    """Метод прямого скачивания через простой API"""
    try:
        # Используем простой публичный API
        api_url = f"https://youtube-mp3-downloader2.p.rapidapi.com/ytmp3/ytmp3/custom/"
        
        querystring = {
            "url": url,
            "quality": "128"
        }
        
        headers = {
            "X-RapidAPI-Key": "demo",  # Некоторые API работают с demo ключом
            "X-RapidAPI-Host": "youtube-mp3-downloader2.p.rapidapi.com"
        }
        
        response = requests.get(api_url, headers=headers, params=querystring, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("status") == "success" and "dlink" in result:
                download_url = result["dlink"]
                
                audio_response = requests.get(download_url, timeout=60)
                
                if audio_response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                        temp_file.write(audio_response.content)
                        temp_file.flush()
                        
                        return send_file(
                            temp_file.name,
                            as_attachment=True,
                            download_name=f"youtube_audio_{video_id}.mp3",
                            mimetype='audio/mpeg'
                        )
        
        return None
        
    except Exception as e:
        logger.error(f"Direct download method failed: {str(e)}")
        return None

@app.route('/get-info', methods=['POST'])
def get_video_info():
    """Получает информацию о видео"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not is_youtube_url(url):
            return jsonify({"error": "Invalid YouTube URL"}), 400
        
        video_id = extract_video_id(url)
        
        # Простая информация из YouTube без API
        return jsonify({
            "video_id": video_id,
            "url": url,
            "status": "ready_for_download"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
