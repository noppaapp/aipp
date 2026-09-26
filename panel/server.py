import hashlib
import hmac
import os
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

PANEL_DIR = Path(__file__).resolve().parent
RUNTIME_URL = os.environ.get('AIPP_RUNTIME_URL', '').strip().rstrip('/')
RUNTIME_TOKEN = os.environ.get('AIPP_RUNTIME_TOKEN', '').strip()
PANEL_TOKEN = os.environ.get('AIPP_PANEL_TOKEN', '').strip()

app = Flask(__name__, static_folder=str(PANEL_DIR), static_url_path='')

def fingerprint(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12] if value else 'NONE'

def require_panel_token():
    if not PANEL_TOKEN:
        return None
    supplied = request.headers.get('X-AIPP-Panel-Token', '').strip()
    if not supplied:
        auth = request.headers.get('Authorization', '')
        supplied = auth[7:].strip() if auth.startswith('Bearer ') else auth.strip()
    if not hmac.compare_digest(supplied, PANEL_TOKEN):
        return jsonify({'ok': False, 'error': 'Panel authentication required'}), 401
    return None

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

    response = requests.request(
        method,
        RUNTIME_URL + path,
        headers=headers,
        json=body if method == 'POST' else None,
        timeout=310,
    )
    try:
        data = response.json()
    except ValueError:
        data = {'ok': False, 'error': response.text[:2000]}

    if not response.ok:
        message = data.get('error') if isinstance(data, dict) else None
        raise RuntimeError(f'Runtime HTTP {response.status_code}: {message or "request failed"}')
    return data

@app.get('/')
def index():
    return send_from_directory(PANEL_DIR, 'index.html')

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

@app.post('/api/command')
def command():
    auth_error = require_panel_token()
    if auth_error:
        return auth_error
    try:
        body = request.get_json(silent=True) or {}
        command_name = str(body.get('command') or 'BAŞLA').strip().upper()
        task = str(body.get('task') or '').strip()
        payload = {'command': command_name, 'task': task or None, 'max_attempts': int(body.get('max_attempts') or 3)}
        return jsonify(runtime_request('/api/run', 'POST', payload))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502

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
