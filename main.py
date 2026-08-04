<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M.A.R.K. Uploader</title>
<style>
  :root {
    --bg: #0a0a0a;
    --panel: #141414;
    --border: #2a2a2a;
    --green: #22c55e;
    --orange: #f97316;
    --red: #ef4444;
    --text: #e5e5e5;
    --dim: #888;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, Roboto, "Segoe UI", sans-serif;
    margin: 0;
    padding: 16px;
    max-width: 480px;
    margin: 0 auto;
  }
  h1 {
    font-size: 1.4rem;
    margin: 8px 0 4px 0;
  }
  .subtitle {
    color: var(--dim);
    font-size: 0.85rem;
    margin-bottom: 20px;
  }
  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
  }
  label {
    display: block;
    font-size: 0.8rem;
    color: var(--dim);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  input[type="text"] {
    width: 100%;
    background: #1e1e1e;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    color: var(--text);
    font-size: 0.95rem;
    margin-bottom: 14px;
  }
  .picker-btn {
    width: 100%;
    padding: 16px;
    background: #1e1e1e;
    border: 1px dashed var(--border);
    border-radius: 10px;
    color: var(--text);
    font-size: 0.95rem;
    text-align: center;
    cursor: pointer;
    margin-bottom: 14px;
  }
  .picker-btn.has-file {
    border-style: solid;
    border-color: var(--green);
    color: var(--green);
  }
  input[type="file"] { display: none; }
  .upload-btn {
    width: 100%;
    padding: 16px;
    background: var(--green);
    border: none;
    border-radius: 10px;
    color: #05170c;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
  }
  .upload-btn:disabled {
    background: #333;
    color: var(--dim);
  }
  .status-line {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 0;
    font-size: 0.85rem;
    border-bottom: 1px solid var(--border);
  }
  .status-line:last-child { border-bottom: none; }
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--dim);
    flex-shrink: 0;
  }
  .dot.ok { background: var(--green); }
  .dot.warn { background: var(--orange); }
  .dot.err { background: var(--red); }
  #log { display: none; }
  #log.show { display: block; }
  .result-box {
    background: #1e1e1e;
    border-radius: 8px;
    padding: 12px;
    margin-top: 10px;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--dim);
    max-height: 220px;
    overflow-y: auto;
  }
</style>
</head>
<body>

<h1>M.A.R.K. Uploader</h1>
<div class="subtitle">Pick a video, send it straight to the content engine.</div>

<div class="panel">
  <label for="endpoint">API Endpoint</label>
  <input type="text" id="endpoint" placeholder="https://mark.sagewire.dev/process-video" value="https://mark.sagewire.dev/process-video">

  <label for="recordId">Record ID (optional — leave blank to create new)</label>
  <input type="text" id="recordId" placeholder="e.g. df1db859">

  <label>Video</label>
  <div class="picker-btn" id="pickerBtn">📹 Tap to choose a video</div>
  <input type="file" id="fileInput" accept="video/*">

  <button class="upload-btn" id="uploadBtn" disabled>Select a video first</button>
</div>

<div class="panel" id="log">
  <div class="status-line"><div class="dot" id="dotUpload"></div><span id="txtUpload">Uploading...</span></div>
  <div class="status-line"><div class="dot" id="dotProcess"></div><span id="txtProcess">Waiting on transcription + LLM...</span></div>
  <div class="status-line"><div class="dot" id="dotSheet"></div><span id="txtSheet">Waiting on Sheets write...</span></div>
  <div class="result-box" id="resultBox"></div>
</div>

<script>
  const pickerBtn = document.getElementById('pickerBtn');
  const fileInput = document.getElementById('fileInput');
  const uploadBtn = document.getElementById('uploadBtn');
  const endpointInput = document.getElementById('endpoint');
  const recordIdInput = document.getElementById('recordId');
  const log = document.getElementById('log');
  const resultBox = document.getElementById('resultBox');

  let selectedFile = null;

  pickerBtn.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      selectedFile = fileInput.files[0];
      pickerBtn.textContent = `✅ ${selectedFile.name}`;
      pickerBtn.classList.add('has-file');
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'Send to M.A.R.K.';
    }
  });

  function setDot(id, state) {
    document.getElementById(id).className = 'dot ' + state;
  }

  uploadBtn.addEventListener('click', async () => {
    const endpoint = endpointInput.value.trim();
    if (!endpoint) {
      alert('Enter the API endpoint first (ask Claude/check your Coolify deployment for the public URL).');
      return;
    }
    if (!selectedFile) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Working...';
    log.classList.add('show');
    resultBox.textContent = '';
    setDot('dotUpload', 'warn');
    setDot('dotProcess', '');
    setDot('dotSheet', '');
    document.getElementById('txtUpload').textContent = 'Uploading video...';
    document.getElementById('txtProcess').textContent = 'Waiting on transcription + LLM...';
    document.getElementById('txtSheet').textContent = 'Waiting on Sheets write...';

    const formData = new FormData();
    formData.append('file', selectedFile);
    const recordId = recordIdInput.value.trim();
    if (recordId) formData.append('record_id', recordId);

    // --- DEBUG LOGGING (added 2026-08-04, patched by Claude) ---
    // "Failed to fetch" alone doesn't say WHY -- CORS block, DNS failure,
    // and a proxy timing out the connection all produce that exact same
    // message with zero extra detail. The two things that actually
    // distinguish them are (1) elapsed time before failure, and (2) the
    // real error object's .name/.message, which the old catch block threw
    // away. A live ticking timer + an AbortController with a generous
    // ceiling gives us both: near-instant failure = CORS/DNS/cert issue,
    // long wait then abort = proxy or server timing the request out.
    const startTime = Date.now();
    let elapsedTimer = null;
    const updateElapsed = () => {
      const secs = ((Date.now() - startTime) / 1000).toFixed(1);
      document.getElementById('txtUpload').textContent = `Uploading video... (${secs}s elapsed)`;
    };
    elapsedTimer = setInterval(updateElapsed, 500);

    const controller = new AbortController();
    const timeoutMs = 120000; // 2 minutes -- generous ceiling for CPU-based Whisper transcription
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      setDot('dotProcess', 'warn');
      document.getElementById('txtProcess').textContent = 'Transcribing + generating content (this can take a bit)...';

      const res = await fetch(endpoint, {
        method: 'POST',
        body: formData,
        signal: controller.signal
      });

      clearInterval(elapsedTimer);
      clearTimeout(timeoutId);
      const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);

      setDot('dotUpload', 'ok');
      document.getElementById('txtUpload').textContent = `Video uploaded (${elapsedSec}s)`;

      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        // This is exactly the "<html>...not valid JSON" failure mode
        const raw = await res.text();
        setDot('dotProcess', 'err');
        document.getElementById('txtProcess').textContent = `Server did not return JSON (status ${res.status})`;
        resultBox.textContent = `HTTP ${res.status} ${res.statusText}\n\n${raw.slice(0, 500)}`;
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Try again';
        return;
      }

      const data = await res.json();
      setDot('dotProcess', 'ok');
      document.getElementById('txtProcess').textContent = 'Transcript + content generated';

      if (data.status === 'success') {
        setDot('dotSheet', 'ok');
        document.getElementById('txtSheet').textContent = 'Written to Google Sheet';
      } else if (data.status === 'partial_success') {
        setDot('dotSheet', 'err');
        document.getElementById('txtSheet').textContent = 'Sheet write FAILED (content was generated but not saved)';
      } else {
        setDot('dotSheet', 'warn');
        document.getElementById('txtSheet').textContent = 'Unknown status: ' + data.status;
      }

      resultBox.textContent = JSON.stringify(data, null, 2);
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'Send another';

    } catch (err) {
      clearInterval(elapsedTimer);
      clearTimeout(timeoutId);
      const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);

      setDot('dotUpload', 'err');

      if (err.name === 'AbortError') {
        // We hit our own 2-minute ceiling -- the request never got a
        // response at all. This is the timeout signature: long wait,
        // then nothing. Points at a proxy/server timeout, not CORS.
        document.getElementById('txtUpload').textContent = `Timed out after ${elapsedSec}s -- no response from server`;
        resultBox.textContent = `TIMEOUT after ${elapsedSec}s.\n\nThe request was sent but never got a response before hitting the ${timeoutMs/1000}s client-side limit. This usually means a reverse proxy (Traefik, Cloudflare, etc.) in front of the API is killing the connection before Whisper transcription finishes -- not a CORS or code problem.`;
      } else {
        // Fast failure (check the elapsed seconds above/below) usually
        // means CORS, DNS, a bad URL, or a TLS/cert problem -- something
        // that fails before any real network round-trip happens.
        document.getElementById('txtUpload').textContent = `Failed after ${elapsedSec}s: ${err.name}`;
        resultBox.textContent = `ERROR after ${elapsedSec}s\n\nName: ${err.name}\nMessage: ${err.message}\n\nIf this failed in well under a second, it's almost always CORS, a DNS/typo issue in the endpoint URL, or a TLS/certificate problem -- not a timeout. If you're testing this on GitHub Pages (https) make sure the API endpoint above also starts with https:// exactly.`;
      }

      uploadBtn.disabled = false;
      uploadBtn.textContent = 'Try again';
    }
  });
</script>

</body>
</html>
