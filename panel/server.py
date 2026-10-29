import hashlib
import hmac
import os
import threading
import uuid
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

PANEL_DIR = Path(__file__).resolve().parent
RUNTIME_URL = os.environ.get('AIPP_RUNTIME_URL', '').strip().rstrip('/')
RUNTIME_TOKEN = os.environ.get('AIPP_RUNTIME_TOKEN', '').strip()
PANEL_TOKEN = os.environ.get('AIPP_PANEL_TOKEN', '').strip()

# Long workspace scans must not hold a browser-facing HTTP request open.
# Jobs are ephemeral and contain only runtime responses; canonical state remains in Drive.
JOBS = {}
JOBS_LOCK = threading.Lock()

app = Flask(__name__, static_folder=str(PANEL_DIR), static_url_path='')

def fingerprint(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12] if value else 'NONE'

def require_panel_token():
    # Fail closed: never expose operator APIs when the panel secret is absent.
    if not PANEL_TOKEN:
        return jsonify({'ok': False, 'error': 'Panel authentication is not configured'}), 503
    supplied = request.headers.get('X-AIPP-Panel-Token', '').strip()
    if not supplied:
        auth = request.headers.get('Authorization', '')
        supplied = auth[7:].strip() if auth.startswith('Bearer ') else auth.strip()
    if not hmac.compare_digest(supplied, PANEL_TOKEN):
        return jsonify({'ok': False, 'error': 'Panel authentication required'}), 401
    return None

class RuntimeRequestError(RuntimeError):
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data
        message = data.get('error') if isinstance(data, dict) else None
        super().__init__(f'Runtime HTTP {status_code}: {message or "request failed"}')


def runtime_request(path, method='GET', payload=None):
    if not RUNTIME_URL:
        raise RuntimeError('AIPP_RUNTIME_URL is not configured')
    if not RUNTIME_TOKEN:
        raise RuntimeError('AIPP_RUNTIME_TOKEN is not configured')

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-AIPP-Runtime-Token': RUNTIME_TOKEN,
    }
    body = payload.copy() if isinstance(payload, dict) else {}
    if method == 'POST':
        body['_runtime_token'] = RUNTIME_TOKEN

    attempts = 3 if method == 'GET' else 1
    last_response = None
    for attempt in range(attempts):
        response = requests.request(
            method,
            RUNTIME_URL + path,
            headers=headers,
            json=body if method == 'POST' else None,
            timeout=310,
        )
        last_response = response
        if response.ok:
            break
        # Render can briefly return 502/503/504 while a Runtime instance is
        # being replaced. Retry GET/status only; never retry POST because it
        # may already have executed an AIPP command.
        if method != 'GET' or response.status_code not in (502, 503, 504) or attempt == attempts - 1:
            break
        import time
        time.sleep(2)

    response = last_response
    try:
        data = response.json()
    except ValueError:
        data = {'ok': False, 'error': response.text[:2000]}

    if not response.ok:
        raise RuntimeRequestError(response.status_code, data)
    return data

def panel_html():
    response = Response((PANEL_DIR / 'index.html').read_text(encoding='utf-8'), mimetype='text/html')
    # The panel is a live operator surface. Never let a stale browser/CDN copy
    # hide the current Turkish UI after a deployment.
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.get('/')
def index():
    return panel_html()

@app.get('/panel')
def panel():
    return panel_html()

@app.get('/index.html')
def index_html():
    return panel_html()

@app.get('/health')
def health():
    return jsonify({'ok': True, 'panel': 'AIPP Control Panel', 'source': 'AIPP Standalone Cloud Runtime'})

@app.get('/api/status')
def status():
    auth_error = require_panel_token()
    if auth_error:
        return auth_error
    try:
        return jsonify(runtime_request('/api/status'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502

def _run_background_job(job_id, payload):
    try:
        result = runtime_request('/api/run', 'POST', payload)
        if result.get('job_id'):
            import time
            runtime_job_id = str(result['job_id'])
            for _ in range(420):
                time.sleep(2)
                state = runtime_request('/api/jobs/' + runtime_job_id, 'GET')
                if state.get('status') == 'RUNNING':
                    continue
                if state.get('status') == 'COMPLETED':
                    result = state.get('data')
                    if not isinstance(result, dict):
                        raise RuntimeError('Runtime scan completed without a valid result.')
                    break
            else:
                raise RuntimeError('Runtime scan did not finish within 14 minutes. It was not automatically restarted.')
        with JOBS_LOCK:
            JOBS[job_id].update({'status': 'COMPLETED', 'result': result})
    except RuntimeRequestError as exc:
        with JOBS_LOCK:
            JOBS[job_id].update({'status': 'FAILED', 'error': exc.data, 'http_status': exc.status_code})
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id].update({'status': 'FAILED', 'error': {'ok': False, 'error': str(exc)}, 'http_status': 502})

@app.post('/api/command')
def command():
    auth_error = require_panel_token()
    if auth_error:
        return auth_error
    try:
        body = request.get_json(silent=True) or {}
        command_name = str(body.get('command') or 'BAŞLA').strip().upper()
        task = str(body.get('task') or '').strip()
        payload = {'command': command_name, 'task': task or None, 'max_attempts': int(body.get('max_attempts') or 3), 'force_refresh': bool(body.get('force_refresh', False))}
        if command_name == 'BAŞLA':
            job_id = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job_id] = {'status': 'RUNNING'}
            threading.Thread(target=_run_background_job, args=(job_id, payload), daemon=True).start()
            return jsonify({'ok': True, 'job_id': job_id, 'status': 'RUNNING'}), 202
        return jsonify(runtime_request('/api/run', 'POST', payload))
    except RuntimeRequestError as exc:
        return jsonify(exc.data), exc.status_code
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502

@app.get('/api/jobs/<job_id>')
def job_status(job_id):
    auth_error = require_panel_token()
    if auth_error:
        return auth_error
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({'ok': False, 'error': 'Bu inceleme oturumu bulunamadı. Sayfa yenilenmiş veya sunucu yeniden başlamış olabilir.'}), 404
        snapshot = dict(job)
    if snapshot['status'] == 'RUNNING':
        return jsonify({'ok': True, 'job_id': job_id, 'status': 'RUNNING'}), 200
    if snapshot['status'] == 'FAILED':
        error = snapshot.get('error') or {'error': 'İnceleme tamamlanamadı.'}
        return jsonify(error), int(snapshot.get('http_status') or 502)
    return jsonify({'ok': True, 'job_id': job_id, 'status': 'COMPLETED', 'data': snapshot.get('result')}), 200

@app.get('/api/config-status')
def config_status():
    auth_error = require_panel_token()
    if auth_error:
        return auth_error
    return jsonify({
        'ok': True,
        'runtime_url_configured': bool(RUNTIME_URL),
        'runtime_token_configured': bool(RUNTIME_TOKEN),
        'panel_token_configured': bool(PANEL_TOKEN),
        'runtime_token_fingerprint': fingerprint(RUNTIME_TOKEN),
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
