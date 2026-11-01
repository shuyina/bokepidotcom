import os
import re
import uuid
import threading
import time
import urllib.parse
import yt_dlp
from flask import Flask, request, jsonify, send_from_directory
from playwright.sync_api import sync_playwright

app = Flask(__name__)

DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}

# ---------- cleanup old files every 10 minutes ----------
def cleanup_loop():
    while True:
        time.sleep(600)
        try:
            now = time.time()
            for f in os.listdir(DOWNLOAD_DIR):
                fp = os.path.join(DOWNLOAD_DIR, f)
                if os.path.isfile(fp) and now - os.path.getmtime(fp) > 3600:
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
        except Exception:
            pass

threading.Thread(target=cleanup_loop, daemon=True).start()

# ---------- embedded single-page UI ----------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M3U8 / Video Downloader</title>
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
  .download-btn:disabled { background-color: #8cd39c; cursor: wait; }
  .direct-link { display: inline-block; margin-top: 0.5rem; color: #007bff; word-break: break-all; }
</style>
</head>
<body>
<div class="container">
  <h2>M3U8 / Video Downloader</h2>

  <div class="row">
    <input type="text" id="urlInput" placeholder="Paste webpage URL or .m3u8 link...">
    <button id="extractBtn" onclick="scrapeUrl()">Detect Media</button>
  </div>

  <div id="loading" class="hidden" style="color:#007bff; font-weight:bold;">Analyzing page...</div>
  <div id="downloading" class="hidden" style="color:#ff9900; font-weight:bold;">Downloading &amp; converting to MP4... this may take a while.</div>
  <div id="error" class="error hidden"></div>
  <div id="success" class="success hidden"></div>

  <div id="results" class="result-box hidden">
    <div id="thumbnailContainer"></div>
    <div id="videoContainer"></div>
    <div id="directLinkContainer"></div>
  </div>
</div>

<script>
let currentVideoUrl = "";
let currentOriginalUrl = "";

async function scrapeUrl() {
  const url = document.getElementById('urlInput').value.trim();
  const loading = document.getElementById('loading');
  const errorDiv = document.getElementById('error');
  const successDiv = document.getElementById('success');
  const resultsDiv = document.getElementById('results');
  const btn = document.getElementById('extractBtn');
  const thumbContainer = document.getElementById('thumbnailContainer');
  const videoContainer = document.getElementById('videoContainer');
  const directLinkContainer = document.getElementById('directLinkContainer');

  if (!url) { alert("Please enter a valid URL"); return; }

  loading.classList.remove('hidden');
  errorDiv.classList.add('hidden');
  successDiv.classList.add('hidden');
  resultsDiv.classList.add('hidden');
  thumbContainer.innerHTML = '';
  videoContainer.innerHTML = '';
  directLinkContainer.innerHTML = '';
  btn.disabled = true;

  // If user pasted an m3u8 directly, skip scraping
  if (url.includes('.m3u8')) {
    currentVideoUrl = url;
    currentOriginalUrl = url;
    showResults(url, []);
    loading.classList.add('hidden');
    btn.disabled = false;
    return;
  }

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
    } else if (data.videos && data.videos.length > 0) {
      currentVideoUrl = data.videos[0];
      currentOriginalUrl = url;
      showResults(currentVideoUrl, data.thumbnails || []);
    } else {
      errorDiv.textContent = "No video URL detected on this page.";
      errorDiv.classList.remove('hidden');
    }
  } catch (err) {
    errorDiv.textContent = "Network error: " + err.message;
    errorDiv.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
    btn.disabled = false;
  }
}

function showResults(videoUrl, thumbnails) {
  const resultsDiv = document.getElementById('results');
  const thumbContainer = document.getElementById('thumbnailContainer');
  const videoContainer = document.getElementById('videoContainer');
  const directLinkContainer = document.getElementById('directLinkContainer');

  if (thumbnails && thumbnails.length > 0) {
    thumbContainer.innerHTML = `<img src="${thumbnails[0]}" class="thumbnail-img" />`;
  }

  videoContainer.innerHTML = `<button onclick="triggerBackendDownload()" class="download-btn" id="dlBtn">⬇ Download &amp; Convert to MP4</button>`;
  directLinkContainer.innerHTML = `<a href="${videoUrl}" target="_blank" rel="noopener" class="direct-link">Direct source link (open in new tab)</a>`;
  resultsDiv.classList.remove('hidden');
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function triggerBackendDownload() {
  const downloading = document.getElementById('downloading');
  const successDiv = document.getElementById('success');
  const errorDiv = document.getElementById('error');
  const dlBtn = document.getElementById('dlBtn');

  downloading.classList.remove('hidden');
  errorDiv.classList.add('hidden');
  successDiv.classList.add('hidden');
  if (dlBtn) dlBtn.disabled = true;

  try {
    // 1. Start job
    const startResp = await fetch('/start_download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: currentVideoUrl, originalUrl: currentOriginalUrl })
    });
    const startData = await startResp.json();
    if (startData.error) throw new Error(startData.error);

    const jobId = startData.job_id;

    // 2. Poll status
    for (let i = 0; i < 600; i++) {  // up to ~20 min
      await sleep(2000);
      const statusResp = await fetch('/job_status/' + jobId);
      const status = await statusResp.json();

      if (status.status === 'done') {
        // 3. Trigger browser download
        const a = document.createElement('a');
        a.href = '/download/' + encodeURIComponent(status.filename);
        a.download = status.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        successDiv.textContent = "✅ Download started: " + status.filename;
        successDiv.classList.remove('hidden');
        return;
      } else if (status.status === 'error') {
        throw new Error(status.error || "Unknown error");
      }
    }
    throw new Error("Timed out waiting for conversion.");
  } catch (err) {
    errorDiv.textContent = "Download failed: " + err.message;
    errorDiv.classList.remove('hidden');
  } finally {
    downloading.classList.add('hidden');
    if (dlBtn) dlBtn.disabled = false;
  }
}
</script>
</body>
</html>
"""


# ---------- extraction: yt-dlp fast path ----------
def extract_with_ytdlp(url):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'format': 'best', 'extract_flat': False}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info.get('url') or (
                info.get('entries', [{}])[0].get('url') if info.get('entries') else None
            )
            thumbnail = info.get('thumbnail')
            if video_url:
                return {"videos": [video_url], "thumbnails": [thumbnail] if thumbnail else []}
    except Exception:
        pass
    return None


# ---------- extraction: playwright fallback ----------
def extract_with_playwright(url):
    videos, thumbnails = set(), set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page()
                page.set_extra_http_headers({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": url,
                })

                def handle_response(response):
                    r = response.url.lower()
                    if any(ext in r for ext in ['.mp4', '.webm', '.m3u8', '.mkv']):
                        videos.add(response.url)
                    if any(ext in r for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                        if any(k in r for k in ['thumb', 'poster', 'cover', 'default', 'mqdefault', 'hqdefault']):
                            thumbnails.add(response.url)

                page.on("response", handle_response)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

                try:
                    video_src = page.evaluate("document.querySelector('video')?.src")
                    video_poster = page.evaluate("document.querySelector('video')?.poster")
                    if video_src and video_src.startswith('http'):
                        videos.add(video_src)
                    if video_poster and video_poster.startswith('http'):
                        thumbnails.add(video_poster)
                except Exception:
                    pass
            finally:
                browser.close()
    except Exception as e:
        return {"error": str(e)}
    return {"videos": list(videos), "thumbnails": list(thumbnails)}


# ---------- routes ----------
@app.route('/')
def index():
    return HTML_CONTENT


@app.route('/scrape', methods=['POST'])
def scrape():
    target_url = (request.json or {}).get('url')
    if not target_url:
        return jsonify({"error": "No URL provided"})

    result = extract_with_ytdlp(target_url)

    if not result or not result.get('videos') or not result.get('thumbnails'):
        pw_result = extract_with_playwright(target_url)
        videos = pw_result.get('videos', [])
        thumbnails = pw_result.get('thumbnails', [])
        if result and result.get('videos') and not videos:
            videos = result['videos']
        if result and result.get('thumbnails') and not thumbnails:
            thumbnails = result['thumbnails']
        result = {"videos": videos, "thumbnails": thumbnails}

    return jsonify(result)


def _run_download_job(job_id, url, original_url):
    try:
        parsed_path = urllib.parse.urlparse(original_url).path.strip('/')
        base_name = parsed_path.split('/')[-1] if parsed_path else "video"
        base_name = os.path.splitext(base_name)[0]
        base_name = re.sub(r'[\\\\/*?:"<>|]', "", base_name) or "media_download"

        out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}_{base_name}.%(ext)s")

        ydl_opts = {
            'format': 'best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'Referer': original_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            mp4_path = os.path.splitext(filename)[0] + '.mp4'
            if os.path.exists(mp4_path):
                filename = mp4_path

        if not os.path.exists(filename):
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(job_id):
                    filename = os.path.join(DOWNLOAD_DIR, f)
                    break

        jobs[job_id]['status'] = 'done'
        jobs[job_id]['filename'] = os.path.basename(filename)
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)


@app.route('/start_download', methods=['POST'])
def start_download():
    data = request.json or {}
    url = data.get('url')
    original_url = data.get('originalUrl', '')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {'status': 'processing', 'filename': None, 'error': None}
    threading.Thread(target=_run_download_job, args=(job_id, url, original_url), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route('/job_status/<job_id>')
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route('/download/<path:filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port)
