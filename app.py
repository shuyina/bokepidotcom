import os
import re
import urllib.parse
import yt_dlp
from flask import Flask, request, jsonify, Response
from playwright.sync_api import sync_playwright

app = Flask(__name__)

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>1-Click M3U8 to MP4 Downloader</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; background: #fafafa; }
        .container { background: #fff; border: 1px solid #ccc; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .row { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
        input[type="text"] { flex: 1; padding: 0.8rem; border: 1px solid #bbb; border-radius: 4px; font-size: 1rem; }
        button { padding: 0.8rem 1.5rem; cursor: pointer; background-color: #007bff; color: white; border: none; border-radius: 4px; font-size: 1rem; font-weight: bold; }
        button:hover { background-color: #0056b3; }
        button:disabled { background-color: #ccc; cursor: not-allowed; }
        .hidden { display: none; }
        .error { color: red; margin-top: 1rem; }
        .success { color: #28a745; margin-top: 1rem; font-weight: bold; }
        .result-box { margin-top: 1.5rem; text-align: center; }
        .thumbnail-img { max-width: 100%; max-height: 400px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 1rem; object-fit: cover; }
        .download-btn { display: inline-block; width: 100%; padding: 1rem; background-color: #28a745; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 1.2rem; cursor: pointer; transition: background 0.2s; box-sizing: border-box; }
        .download-btn:hover { background-color: #218838; }
    </style>
</head>
<body>
    <div class="container">
        <h2>1-Click M3U8 to MP4 Downloader</h2>
        
        <div class="row">
            <input type="text" id="urlInput" placeholder="Paste webpage URL here...">
            <button id="extractBtn" onclick="scrapeUrl()">Detect Media</button>
        </div>
        
        <div id="loading" class="hidden" style="color: #007bff; font-weight: bold;">Analyzing page...</div>
        <div id="downloading" class="hidden" style="color: #ff9900; font-weight: bold;">Downloading and converting to MP4... Check your terminal!</div>
        <div id="error" class="error hidden"></div>
        <div id="success" class="success hidden"></div>

        <div id="results" class="result-box hidden">
            <div id="thumbnailContainer"></div>
            <div id="videoContainer"></div>
        </div>
    </div>

    <script>
        let currentVideoUrl = "";

        async function scrapeUrl() {
            const url = document.getElementById('urlInput').value.trim();
            const loading = document.getElementById('loading');
            const errorDiv = document.getElementById('error');
            const successDiv = document.getElementById('success');
            const resultsDiv = document.getElementById('results');
            const btn = document.getElementById('extractBtn');
            const thumbContainer = document.getElementById('thumbnailContainer');
            const videoContainer = document.getElementById('videoContainer');
            
            if (!url) { alert("Please enter a valid URL"); return; }

            loading.classList.remove('hidden');
            errorDiv.classList.add('hidden');
            successDiv.classList.add('hidden');
            resultsDiv.classList.add('hidden');
            thumbContainer.innerHTML = '';
            videoContainer.innerHTML = '';
            btn.disabled = true;

            try {
                const response = await fetch('/scrape', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                const data = await response.json();

                if (data.error) {
                    errorDiv.textContent = "Error: " + data.error;
                    errorDiv.classList.remove('hidden');
                } else {
                    if (data.thumbnails && data.thumbnails.length > 0) {
                        thumbContainer.innerHTML = `<img src="${data.thumbnails[0]}" class="thumbnail-img" />`;
                    }
                    if (data.videos && data.videos.length > 0) {
                        currentVideoUrl = data.videos[0];
                        videoContainer.innerHTML = `<button onclick="triggerBackendDownload()" class="download-btn">⬇ Download & Convert to MP4</button>`;
                        resultsDiv.classList.remove('hidden');
                    } else {
                        errorDiv.textContent = "No standard video URLs detected.";
                        errorDiv.classList.remove('hidden');
                    }
                }
            } catch (err) {
                errorDiv.textContent = "Network error: " + err.message;
                errorDiv.classList.remove('hidden');
            } finally {
                loading.classList.add('hidden');
                btn.disabled = false;
            }
        }

        async function triggerBackendDownload() {
            const originalUrl = document.getElementById('urlInput').value.trim();
            const downloading = document.getElementById('downloading');
            const successDiv = document.getElementById('success');
            const errorDiv = document.getElementById('error');
            const resultsDiv = document.getElementById('results');
            
            resultsDiv.classList.add('hidden');
            downloading.classList.remove('hidden');
            errorDiv.classList.add('hidden');
            successDiv.classList.add('hidden');

            try {
                const response = await fetch('/download_backend', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        url: currentVideoUrl,
                        originalUrl: originalUrl
                    })
                });
                const data = await response.json();

                if (data.error) {
                    errorDiv.textContent = "Download failed: " + data.error;
                    errorDiv.classList.remove('hidden');
                } else {
                    successDiv.textContent = "Success! File saved to your Downloads folder: " + data.filepath;
                    successDiv.classList.remove('hidden');
                }
            } catch (err) {
                errorDiv.textContent = "Network error: " + err.message;
                errorDiv.classList.remove('hidden');
            } finally {
                downloading.classList.add('hidden');
            }
        }
    </script>
</body>
</html>
"""

def extract_with_ytdlp(url):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'format': 'best', 'extract_flat': False}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info.get('url') or (info.get('entries', [{}])[0].get('url') if info.get('entries') else None)
            thumbnail = info.get('thumbnail')
            if video_url: return {"videos": [video_url], "thumbnails": [thumbnail] if thumbnail else []}
    except Exception: pass
    return None

def extract_with_playwright(url):
    videos, thumbnails = set(), set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": url
            })
            
            def handle_response(response):
                resource_url = response.url.lower()
                # Intercept video links
                if any(ext in resource_url for ext in ['.mp4', '.webm', '.m3u8', '.mkv']):
                    videos.add(response.url)
                # Intercept image links that might be thumbnails
                if any(ext in resource_url for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    if any(keyword in resource_url for keyword in ['thumb', 'poster', 'cover', 'default', 'mqdefault', 'hqdefault']):
                        thumbnails.add(response.url)
                        
            page.on("response", handle_response)
            page.goto(url, wait_until="networkidle", timeout=15000)
            
            try:
                # Also try to extract directly from the HTML <video> tag
                page.wait_for_selector('video', timeout=3000)
                video_src = page.evaluate("document.querySelector('video')?.src")
                video_poster = page.evaluate("document.querySelector('video')?.poster")
                
                if video_src and video_src.startswith('http'): 
                    videos.add(video_src)
                if video_poster and video_poster.startswith('http'): 
                    thumbnails.add(video_poster)
            except: 
                pass
                
            browser.close()
    except Exception as e:
        return {"error": str(e)}
    return {"videos": list(videos), "thumbnails": list(thumbnails)}

@app.route('/')
def index():
    return Response(HTML_CONTENT, mimetype='text/html')

@app.route('/scrape', methods=['POST'])
def scrape():
    target_url = request.json.get('url')
    
    # Fast extraction first
    result = extract_with_ytdlp(target_url)
    
    # If no video or thumbnail found, fallback to full browser render
    if not result or not result.get('videos') or not result.get('thumbnails'):
        pw_result = extract_with_playwright(target_url)
        
        # Merge results to get the best of both
        videos = pw_result.get('videos', [])
        thumbnails = pw_result.get('thumbnails', [])
        
        if result and result.get('videos') and not videos:
            videos = result['videos']
            
        result = {"videos": videos, "thumbnails": thumbnails}
        
    return jsonify(result)

@app.route('/download_backend', methods=['POST'])
def download_backend():
    url = request.json.get('url') # The raw .m3u8 or .mp4 link
    original_url = request.json.get('originalUrl', '') # The link the user pasted
    
    if not url: return jsonify({"error": "No URL provided"}), 400
    
    # 1. Parse the original URL to get a clean filename
    parsed_path = urllib.parse.urlparse(original_url).path.strip('/')
    base_name = parsed_path.split('/')[-1] if parsed_path else "downloaded_video"
    
    # 2. Clean the filename (remove .html, .php, or invalid characters)
    base_name = os.path.splitext(base_name)[0]
    base_name = re.sub(r'[\\/*?:"<>|]', "", base_name)
    if not base_name or base_name.lower() == 'index':
        base_name = "media_download"

    # 3. Setup Downloads folder (CHANGED FOR CLOUD DEPLOYMENT)
    downloads_folder = os.path.join(os.getcwd(), "downloads")
    os.makedirs(downloads_folder, exist_ok=True)
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(downloads_folder, f'{base_name}.%(ext)s'),
        'merge_output_format': 'mp4', # Forces m3u8 conversion to mp4
        'noplaylist': True,
        'http_headers': {
            'Referer': original_url,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Replace extension to reflect merged mp4
            mp4_filename = os.path.splitext(filename)[0] + '.mp4'
            return jsonify({"filepath": mp4_filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=False)
