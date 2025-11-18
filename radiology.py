#!/usr/bin/env python3
import os
import requests
import time
import uuid
import threading
from datetime import datetime
from flask import (
    Flask,
    request,
    render_template_string,
    send_from_directory,
    jsonify,
    redirect,
    url_for,
    Blueprint
)


# --- Configuration & Global State ---
DEFAULT_HOST = "http://127.0.0.1:5000"  # target radiology server
radiology_bp = Blueprint('radiology_bp', __name__, template_folder='templates')
os.makedirs("downloads", exist_ok=True)

# In-memory "database" for tracking requests
REQUEST_QUEUE = []
queue_lock = threading.Lock()

# In-memory "database" for scans
SCAN_DB = {}
scan_lock = threading.Lock()

# --- Helpers (unchanged functionality) ---

def save_stream_to_file(resp, out_path, chunk_size=8192):
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size):
            if chunk:
                f.write(chunk)

def download_scan(host, scan_id, out_dir, uhid=None):
    # This function is now modified to call the new local endpoint
    url = f"{host.rstrip('/')}/radiology/api/scans/download/{scan_id}"
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            if r.ok:
                disp = r.headers.get('Content-Disposition')
                filename = disp.split('filename=')[-1].strip('\"') if disp else f'scan-{scan_id}.dcm'
                out_path = os.path.join(out_dir, filename)
                save_stream_to_file(r, out_path)
                print(f"[{datetime.now().isoformat()}] Scan {scan_id} downloaded to {out_path}")
                return filename
            else:
                print(f"[{datetime.now().isoformat()}] Failed to download scan {scan_id}. Status code: {r.status_code}")
                return None
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] An error occurred during download: {e}")
        return None

def process_scan_request_worker(request_id, host, department, uhid, scan_type, body_part):
    """
    Simulates a worker thread processing the request.
    It calls the external server and updates the queue status.
    """
    request_data = {
        "department": department,
        "uhid": uhid,
        "scan_type": scan_type,
        "body_part": body_part,
    }
    # Corrected URL to match the local blueprint
    url = f"{host.rstrip('/')}/radiology/api/scans/create"
    
    with queue_lock:
        req = next((r for r in REQUEST_QUEUE if r['id'] == request_id), None)
    
    if req:
        try:
            time.sleep(1) # Simulate network latency
            resp = requests.post(url, json=request_data, timeout=30)
            resp.raise_for_status()
            scan_id = resp.json().get('scan_id')
            
            # Simulate processing/downloading time
            time.sleep(2)
            
            filename = download_scan(host, scan_id, "downloads", uhid)

            with queue_lock:
                req['status'] = 'Completed' if filename else 'Failed'
                req['filename'] = filename
                req['error'] = None if filename else 'Download failed'
            print(f"[{datetime.now().isoformat()}] Request {request_id} processed. Status: {req['status']}")

        except requests.exceptions.RequestException as e:
            with queue_lock:
                req['status'] = 'Failed'
                req['error'] = str(e)
            print(f"[{datetime.now().isoformat()}] Request {request_id} failed: {e}")
        except Exception as e:
            with queue_lock:
                req['status'] = 'Failed'
                req['error'] = f"An unexpected error occurred: {e}"
            print(f"[{datetime.now().isoformat()}] Request {request_id} failed with an unexpected error: {e}")

# --- HTML Templates ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Submit Scan Request — DICOM App</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    /* subtle page background */
    body { background: radial-gradient(1200px 400px at 10% 10%, rgba(59,130,246,0.06), transparent),
                          radial-gradient(900px 300px at 90% 90%, rgba(99,102,241,0.035), transparent), #f3f4f6; }
    .glass { background: rgba(255,255,255,0.7); backdrop-filter: blur(6px); }
    .accent { background: linear-gradient(90deg,#4f46e5,#06b6d4); -webkit-background-clip: text; color: transparent;}
    .card-hover:hover { transform: none; box-shadow: 0 20px 40px rgba(15,23,42,0.08); }
    /* Toast */
    .toast { position: fixed; top: 24px; right: 24px; z-index: 50; min-width: 280px; max-width: 420px; }
    .toast-enter { transform: translateY(-12px) scale(0.98); opacity: 0; }
    .toast-visible { transform: translateY(0) scale(1); opacity: 1; transition: transform .28s cubic-bezier(.2,.9,.3,1), opacity .28s; }
    .toast-hide { transform: translateY(-12px) scale(0.98); opacity: 0; transition: transform .28s, opacity .28s; }
    .tiny { font-size: .85rem; }
  </style>
</head>
<body class="font-sans text-gray-800 min-h-screen">
  <header class="py-6">
    <div class="container mx-auto flex items-center justify-between px-4">
      <div class="flex items-center space-x-3">
        <div class="w-12 h-12 rounded-xl flex items-center justify-center bg-gradient-to-tr from-indigo-600 to-teal-400 text-white shadow-lg">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 2v4M5 7l7 7 7-7M12 22v-6" />
          </svg>
        </div>
        <div>
          <div class="text-lg font-bold">DICOM Request App</div>
          <div class="text-xs text-gray-500">Request for a scan in seconds.</div>
        </div>
      </div>
      <nav class="space-x-4">
      <a href="{{ url_for('psychiatry_dashboard') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Home</a>
        <a href="{{ url_for('radiology_bp.radiology_submit') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Submit</a>
        <a href="{{ url_for('radiology_bp.view_queue_page') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">View Queue</a>
      </nav>
    </div>
  </header>

  <main class="container mx-auto px-4 pb-12">
    <div class="grid md:grid-cols-2 gap-8 items-start">
      <div class="glass rounded-2xl p-6 shadow-sm card-hover">
        <div class="flex justify-between items-center mb-4">
          <div>
            <h1 class="text-2xl font-bold text-gray-800">New Scan Request</h1>
          </div>
          <div class="text-right">
            <div class="text-sm text-gray-500">Dept</div>
            <div class="font-semibold">PSYCHIATRY</div>
          </div>
        </div>

        <form method="POST" action="{{ url_for('radiology_bp.radiology_submit') }}" class="space-y-4">
          <input type="text" name="department" value="ORTHOPEDICS" class="hidden">
          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Patient UHID</div>
            <input type="text" name="uhid" class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-300" placeholder="UHID e.g. UHID77777" required>
          </label>

          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Scan Type</div>
            <select name="scan_type" class="w-full border rounded-lg px-3 py-2 focus:outline-none" required>
              <option value="" disabled selected>Select Scan Type</option>
              <option value="CT">CT</option>
              <option value="MR">MR</option>
              <option value="XRAY">XRAY</option>
              <option value="US">ULTRASOUND</option>
              <option value="PET">PET</option>
            </select>
          </label>

          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Body Part</div>
            <input type="text" name="body_part" class="w-full border rounded-lg px-3 py-2 focus:outline-none" placeholder="e.g. BRAIN" required oninput="this.value=this.value.toUpperCase()">
            <div class="text-xs text-gray-400 mt-1">Please spell the body part correctly for better matching.</div>
          </label>

          <div class="flex items-center space-x-3">
            <button type="submit" class="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg shadow">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
              Queue Request
            </button>
            <a href="{{ url_for('radiology_bp.view_queue_page') }}" class="text-sm text-gray-600 hover:underline">Open queue</a>
          </div>
        </form>
      </div>

      <div class="space-y-4">
        <div class="glass rounded-2xl p-6 shadow-sm card-hover">
          <div class="flex items-center justify-between mb-2">
            <h3 class="font-semibold text-gray-700">Quick Stats</h3>
            <div class="text-xs text-gray-500">Realtime (in-memory)</div>
          </div>
          <div class="grid grid-cols-3 gap-4 mt-3">
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Queued</div>
              <div id="stat-queued" class="text-2xl font-bold">0</div>
            </div>
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Completed</div>
              <div id="stat-completed" class="text-2xl font-bold">0</div>
            </div>
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Failed</div>
              <div id="stat-failed" class="text-2xl font-bold text-red-500">0</div>
            </div>
          </div>

          <div class="mt-4 text-xs text-gray-500">Note: Queue is in-memory and will reset on app restart.</div>
        </div>

        <div class="glass rounded-2xl p-6 shadow-sm card-hover">
          <h3 class="font-semibold text-gray-700 mb-2">Helpful</h3>
          <ul class="text-sm text-gray-600 space-y-2">
            <li>Open <a href="{{ url_for('radiology_bp.view_queue_page') }}" class="text-indigo-600 hover:underline">View Queue</a> to monitor progress & view DICOMs.</li>
          </ul>
        </div>
      </div>
    </div>
  </main>

  <div id="toast-root" class="toast"></div>

  <script>
    async function fetchStats() {
      try {
        const res = await fetch('/radiology/api/queue_status');
        if (!res.ok) return;
        const q = await res.json();
        let queued = 0, completed = 0, failed = 0;
        for (const r of q) {
          if (r.status === 'Pending') queued++;
          else if (r.status === 'Completed') completed++;
          else if (r.status === 'Failed') failed++;
        }
        document.getElementById('stat-queued').textContent = queued;
        document.getElementById('stat-completed').textContent = completed;
        document.getElementById('stat-failed').textContent = failed;
      } catch (e) {
        // ignore
      }
    }

    // Show animated toast (auto-dismiss)
    function showToast(title, message, kind = 'success') {
      const root = document.getElementById('toast-root');
      const id = 't' + Math.random().toString(36).slice(2,9);
      const color = kind === 'error' ? 'bg-red-50 border-red-200' : 'bg-white border-indigo-100';
      const icon = kind === 'error' ? '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-red-500" viewBox="0 0 20 20" fill="currentColor"><path d="M10 9a1 1 0 100 2 1 1 0 000-2z"/><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.72-1.36 3.486 0l5.518 9.814A1 1 0 0116.518 15H3.482a1 1 0 01-.743-1.587L8.257 3.1z" clip-rule="evenodd"/></svg>'
                               : '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-indigo-500" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11.414V11a1 1 0 11-2 0V6.586L7.293 7.293A1 1 0 015.879 5.879l3-3A1 1 0 019.88 2.88L12 5l2.12-2.12a1 1 0 011.414 1.414L13.414 6H11z" clip-rule="evenodd"/></svg>';

      const el = document.createElement('div');
      el.id = id;
      el.className = `p-3 rounded-lg border ${color} shadow-sm toast-enter`;
      el.innerHTML = `<div class="flex items-start gap-3">
            <div class="pt-0.5">${icon}</div>
            <div>
              <div class="font-medium text-sm">${title}</div>
              <div class="text-xs text-gray-600 mt-1">${message}</div>
            </div>
            <div class="ml-4"><button class="text-gray-400 hover:text-gray-600 close-btn" aria-label="close">&times;</button></div>
          </div>`;
      root.appendChild(el);

      // animate in
      requestAnimationFrame(() => el.classList.add('toast-visible'));

      // close handler
      el.querySelector('.close-btn').addEventListener('click', () => {
        hide();
      });

      let hideTimeout = setTimeout(hide, 4200);
      function hide() {
        clearTimeout(hideTimeout);
        el.classList.remove('toast-visible');
        el.classList.add('toast-hide');
        setTimeout(() => el.remove(), 300);
      }
    }

    // If page has ?created_id=...&uhid=..., show toast once and remove params
    (function handleCreatedParam() {
      const params = new URLSearchParams(window.location.search);
      const created = params.get('created_id');
      const uhid = params.get('uhid');
      const scan = params.get('scan_type') || '';
      if (created && uhid) {
        showToast('Request created', `UHID ${uhid} queued ${scan ? '• ' + scan : ''}.`, 'success');
        // Remove query params to avoid re-showing on refresh
        params.delete('created_id'); params.delete('uhid'); params.delete('scan_type');
        const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.history.replaceState({}, document.title, newUrl);
      }
    })();

    // initial stats + periodic refresh
    fetchStats();
    setInterval(fetchStats, 1800000);
  </script>
</body>
</html>
"""

VIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Request Queue — DICOM App</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: radial-gradient(1000px 300px at 15% 20%, rgba(99,102,241,0.03), transparent), #f8fafc; }
    .glass { background: rgba(255,255,255,0.8); backdrop-filter: blur(6px); }
    .card-hover:hover { transform: none; box-shadow: 0 14px 30px rgba(2,6,23,0.08); }
    .spinner { border: 3px solid rgba(0,0,0,0.06); width: 18px; height: 18px; border-radius: 999px; border-left-color: #2563eb; animation: spin 1s linear infinite;}
    @keyframes spin { to { transform: rotate(360deg); } }
    .timeline { border-left: 3px dashed rgba(99,102,241,0.12); padding-left: 16px; }
  </style>
</head>
<body class="font-sans text-gray-800 min-h-screen">
  <header class="py-6">
    <div class="container mx-auto flex items-center justify-between px-4">
      <div class="flex items-center space-x-3">
        <div class="w-12 h-12 rounded-xl flex items-center justify-center bg-gradient-to-tr from-indigo-600 to-teal-400 text-white shadow-lg">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 2v4M5 7l7 7 7-7M12 22v-6" />
          </svg>
        </div>
        <div>
          <div class="text-lg font-bold">DICOM Request App</div>
          <div class="text-xs text-gray-500">Queue monitor</div>
        </div>
      </div>
      <nav class="space-x-4">
      <a href="{{ url_for('psychiatry_dashboard') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Home</a>
        <a href="{{ url_for('radiology_bp.radiology_submit') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Submit</a>
        <a href="{{ url_for('radiology_bp.view_queue_page') }}" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">View Queue</a>
      </nav>
    </div>
  </header>

  <main class="container mx-auto px-4 pb-12">
    <div class="bg-white/60 glass rounded-2xl p-6 shadow-sm">
      <h2 class="text-2xl font-bold mb-4">Request Queue</h2>
      <div class="flex justify-between items-center mb-4">
        <div class="text-sm text-gray-600">Realtime queue (in-memory)</div>
        <div class="text-sm"><button id="clear-queue" class="text-xs bg-red-50 text-red-600 px-3 py-1 rounded">Clear (dev)</button></div>
      </div>

      <div id="request-queue-container" class="space-y-3">
        </div>
    </div>
  </main>

  <div id="viewer-modal" class="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-4 hidden">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-3xl h-full max-h-[80vh] flex flex-col">
      <div class="p-3 border-b flex justify-between items-center">
        <h3 class="font-bold text-lg">DICOM Viewer</h3>
        <button id="close-modal-btn" class="text-gray-500 hover:text-gray-800 text-2xl">&times;</button>
      </div>
      <div id="dicomImage" class="w-full flex-grow bg-black"></div>
    </div>
  </div>

  <script src="https://unpkg.com/cornerstone-core@2.3.0/dist/cornerstone.js"></script>
  <script src="https://unpkg.com/dicom-parser@1.8.7/dist/dicomParser.js"></script>
  <script src="https://unpkg.com/cornerstone-wado-image-loader@3.1.2/dist/cornerstoneWADOImageLoader.js"></script>

  <script>
    // Cornerstone init
    try {
      cornerstoneWADOImageLoader.webWorkerManager.initialize({
        maxWebWorkers: navigator.hardwareConcurrency || 1,
        startWebWorkersOnDemand: true,
        taskConfiguration: { 'decodeTask': { initializeCodecsOnStartup: false, usePDFJS: false, strict: false } }
      });
      cornerstoneWADOImageLoader.external.cornerstone = cornerstone;
    } catch (e) { console.warn('cornerstone init failed', e); }

    const queueContainer = document.getElementById('request-queue-container');
    const modal = document.getElementById('viewer-modal');
    const dicomElement = document.getElementById('dicomImage');
    const closeModalBtn = document.getElementById('close-modal-btn');

    function renderQueue(queue) {
      if (!queue || queue.length === 0) {
        queueContainer.innerHTML = '<p class="text-center text-gray-500 py-8">No requests in the queue.</p>';
        return;
      }
      // Grouped timeline-like layout
      let html = '<div class="timeline">';
      for (const req of queue) {
        const when = new Date(req.timestamp).toLocaleString();
        const statusBadge = req.status === 'Pending' ? '<div class="text-xs text-blue-600">Pending</div>' :
                                 req.status === 'Completed' ? '<div class="text-xs text-green-600">Completed</div>' :
                                 '<div class="text-xs text-red-600">Failed</div>';
        const spinner = req.status === 'Pending' ? '<div class="spinner mr-2"></div>' : '';
        const viewBtn = (req.status === 'Completed' && req.filename) ? `<button class="view-dicom-btn bg-green-600 text-white px-3 py-1 rounded text-sm" data-filename="${req.filename}">View</button>` : '';
        const errMsg = req.error ? `<div class="text-xs text-red-500 mt-1">Err: ${req.error}</div>` : '';
        html += `
          <div class="mb-6 p-4 bg-white rounded-lg shadow-sm flex justify-between items-start card-hover">
            <div>
              <div class="flex items-center gap-3">
                ${spinner}
                <div>
                  <div class="font-medium">UHID: ${req.uhid} <span class="text-xs text-gray-400">• ${when}</span></div>
                  <div class="text-sm text-gray-600">${req.scan_type} — ${req.body_part}</div>
                  ${errMsg}
                </div>
              </div>
            </div>
            <div class="flex flex-col items-end gap-2">
              ${statusBadge}
              ${viewBtn}
            </div>
          </div>
        `;
      }
      html += '</div>';
      queueContainer.innerHTML = html;
    }

    async function fetchQueueStatus() {
      try {
        const res = await fetch('/radiology/api/queue_status');
        if (!res.ok) return;
        const q = await res.json();
        renderQueue(q);
      } catch (e) { console.error('fetchQueueStatus err', e); }
    }

    function enableCornerstone() {
      try { cornerstone.enable(dicomElement); } catch(e) {}
    }
    function disableCornerstone() {
      try { cornerstone.disable(dicomElement); } catch(e) {}
      dicomElement.innerHTML = '';
    }

    function showViewer(filename) {
      if (!filename) return;
      const imageId = `wadouri:${window.location.origin}/radiology/dicom/${encodeURIComponent(filename)}`;
      modal.classList.remove('hidden');
      enableCornerstone();
      cornerstone.loadAndCacheImage(imageId).then(function(image) {
        cornerstone.displayImage(dicomElement, image);
      }).catch(function(err) {
        dicomElement.innerHTML = '<div class="p-4 text-red-400">Failed to load DICOM image. Check console.</div>';
        console.error(err);
      });
    }

    closeModalBtn.addEventListener('click', () => {
      modal.classList.add('hidden');
      disableCornerstone();
    });

    // Delegated click for view-dicom buttons
    queueContainer.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.view-dicom-btn');
      if (btn) {
        const filename = btn.dataset.filename;
        showViewer(filename);
      }
    });

    document.addEventListener('DOMContentLoaded', () => {
      fetchQueueStatus();
      setInterval(fetchQueueStatus, 1800000);

      // dev: clear queue
      document.getElementById('clear-queue').addEventListener('click', async () => {
        await fetch('/radiology/api/clear_queue', { method: 'POST' });
        fetchQueueStatus();
      });
    });
  </script>
</body>
</html>
"""

# --- Flask Routes ---

@radiology_bp.route("/", methods=["GET", "POST"])
def radiology_submit():
    """Main submission page for scan requests."""
    if request.method == "POST":
        uhid = request.form.get("uhid")
        department = request.form.get("department")
        scan_type = request.form.get("scan_type")
        body_part = request.form.get("body_part")

        if not all([uhid, department, scan_type, body_part]):
            # In a real app, you would handle this more gracefully
            return "Missing form data", 400

        new_request = {
            "id": str(uuid.uuid4()),
            "uhid": uhid,
            "department": department,
            "scan_type": scan_type,
            "body_part": body_part,
            "status": "Pending",
            "filename": None,
            "error": None,
            "timestamp": datetime.now().isoformat()
        }

        with queue_lock:
            REQUEST_QUEUE.insert(0, new_request)

        thread = threading.Thread(
            target=process_scan_request_worker,
            args=(
                new_request['id'],
                DEFAULT_HOST,
                department,
                uhid,
                scan_type,
                body_part
            ),
            daemon=True
        )
        thread.start()
        # Correct the url_for to point to the correct blueprint endpoint
        return redirect(url_for('radiology_bp.radiology_submit', created_id=new_request['id'], uhid=uhid, scan_type=scan_type))

    return render_template_string(INDEX_HTML)

@radiology_bp.route("/view")
def view_queue_page():
    """Separate View Requests page."""
    return render_template_string(VIEW_HTML)

@radiology_bp.route("/api/queue_status")
def queue_status():
    with queue_lock:
        return jsonify(list(REQUEST_QUEUE))

@radiology_bp.route("/api/scans/create", methods=["POST"])
def create_scan():
    """Endpoint for creating a new scan request."""
    # This route simulates the external server. It receives the request and returns a scan_id.
    try:
        data = request.get_json()
        uhid = data.get('uhid')
        scan_type = data.get('scan_type')
        body_part = data.get('body_part')
        
        if not all([uhid, scan_type, body_part]):
            return jsonify({"error": "Missing data"}), 400

        new_scan_id = str(uuid.uuid4())
        # In a real scenario, this would trigger scan generation
        with scan_lock:
            SCAN_DB[new_scan_id] = {
                "uhid": uhid,
                "scan_type": scan_type,
                "body_part": body_part,
                "created_at": datetime.now().isoformat()
            }
        
        print(f"[{datetime.now().isoformat()}] New scan request received for UHID {uhid}. ID: {new_scan_id}")
        return jsonify({"scan_id": new_scan_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@radiology_bp.route("/api/scans/download/<scan_id>")
def download_scan_api(scan_id):
    """Endpoint for downloading a scan file."""
    # This route simulates the external server. It serves a dummy DICOM file.
    with scan_lock:
        scan_info = SCAN_DB.get(scan_id)
        if not scan_info:
            return "Scan not found", 404
    
    # Create a dummy DICOM file for demonstration
    dummy_dicom_content = b'This is a dummy DICOM file for scan: ' + scan_id.encode('utf-8')
    dummy_filename = f"scan_{scan_id}.dcm"
    
    # Save the dummy file to the downloads directory
    file_path = os.path.join("downloads", dummy_filename)
    with open(file_path, "wb") as f:
        f.write(dummy_dicom_content)
    
    print(f"[{datetime.now().isoformat()}] Serving dummy DICOM file for {scan_id}")
    return send_from_directory("downloads", dummy_filename, as_attachment=True, mimetype="application/octet-stream")

@radiology_bp.route("/dicom/<path:filename>")
def serve_dicom(filename):
    return send_from_directory("downloads", filename, mimetype="application/octet-stream")

# Optional helper: clear in-memory queue (dev only)
@radiology_bp.route("/api/clear_queue", methods=["POST"])
def clear_queue():
    with queue_lock:
        REQUEST_QUEUE.clear()
    with scan_lock:
        SCAN_DB.clear()
    return "Queue cleared", 200

if __name__ == "__main__":
    app.run(port=8000, debug=True)
