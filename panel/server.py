import json
import os
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8787
BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "canonical_state.json"
PANEL_DIR = Path(__file__).resolve().parent

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIPP Control Panel</title>
    <style>
        :root { --bg-color:#0f172a; --card-bg:#1e293b; --border-color:#334155; --text-main:#f8fafc; --text-muted:#94a3b8; --accent-blue:#38bdf8; }
        * { box-sizing:border-box; margin:0; padding:0; font-family:monospace,sans-serif; }
        body { background:var(--bg-color); color:var(--text-main); padding:16px; line-height:1.4; }
        header { display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid var(--border-color); padding-bottom:12px; margin-bottom:16px; }
        h1 { font-size:1.2rem; text-transform:uppercase; letter-spacing:1px; color:var(--accent-blue); }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:16px; }
        .card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:4px; padding:14px; }
        .card-title { font-size:.85rem; font-weight:bold; text-transform:uppercase; color:var(--text-muted); border-bottom:1px solid var(--border-color); padding-bottom:6px; margin-bottom:10px; }
        .pipeline-flow { display:flex; gap:8px; overflow-x:auto; padding:8px 0; margin-bottom:16px; background:#020617; border:1px solid var(--border-color); border-radius:4px; }
        .step { padding:6px 12px; font-size:.75rem; border-radius:3px; background:var(--card-bg); color:var(--text-muted); font-weight:bold; white-space:nowrap; }
        .step.active { background:var(--accent-blue); color:#000; }
        .badge { display:inline-block; padding:2px 6px; font-size:.7rem; font-weight:bold; border-radius:3px; text-transform:uppercase; }
        .badge-green { background:#15803d; color:#fff; } .badge-yellow { background:#a16207; color:#fff; } .badge-blue { background:#0369a1; color:#fff; }
        .btn-group { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        button { background:var(--border-color); color:var(--text-main); border:1px solid #475569; padding:8px 12px; font-size:.75rem; font-weight:bold; cursor:pointer; border-radius:3px; text-transform:uppercase; }
        button:hover { background:#475569; } button.primary { background:#0284c7; border-color:#38bdf8; } button.success { background:#16a34a; border-color:#4ade80; }
        ul { list-style:none; font-size:.8rem; } li { padding:6px 0; border-bottom:1px dashed var(--border-color); }
        .log-box { background:#020617; border:1px solid var(--border-color); padding:10px; height:160px; overflow-y:auto; font-size:.75rem; color:#a7f3d0; }
        .error-banner { background:#7f1d1d; color:#fecaca; padding:10px; margin-bottom:16px; border-radius:4px; display:none; font-size:.8rem; }
    </style>
</head>
<body>
<header><h1>AIPP Operator Console</h1><div id="sys-status"><span class="badge badge-blue">CONNECTING...</span></div></header>
<div id="error-display" class="error-banner"></div>
<div class="pipeline-flow">
<div class="step" id="flow-PROJECT">1. PROJECT</div><div class="step" id="flow-DISCOVERED">2. DISCOVERED TASKS</div><div class="step" id="flow-PROPOSAL">3. PROPOSAL</div><div class="step" id="flow-AUTHORITY">4. AUTHORITY</div><div class="step" id="flow-EXECUTION">5. EXECUTION</div><div class="step" id="flow-VERIFY">6. VERIFY</div><div class="step" id="flow-COMPLETED">7. COMPLETED</div>
</div>
<div class="grid">
<div class="card"><div class="card-title">SYSTEM STATUS</div><ul><li>Active Project: <strong id="sys-project">-</strong></li><li>Execution Mode: <strong id="sys-mode">-</strong></li><li>Runner Status: <strong id="sys-runner">-</strong></li><li>Lifecycle State: <strong id="sys-lifecycle">-</strong></li></ul><div class="btn-group"><button onclick="sendCommand('BAŞLA')">START / DISCOVER</button></div></div>
<div class="card"><div class="card-title">CURRENT TASK & ACTIONS</div><div id="current-task-info">No active task selected.</div><div class="btn-group"><button class="primary" onclick="sendCommand('REQUEST_APPROVAL')">REQUEST APPROVAL</button><button class="success" onclick="sendCommand('APPROVE')">APPROVE</button><button onclick="sendCommand('EXECUTE')">EXECUTE</button><button onclick="sendCommand('VERIFY')">VERIFY</button><button onclick="sendCommand('CONTINUE')">CONTINUE</button></div></div>
</div>
<div class="grid"><div class="card"><div class="card-title">TASK QUEUE</div><div id="task-queue">Loading tasks...</div></div><div class="card"><div class="card-title">AUTHORITY & EXECUTION STATE</div><ul><li>Authority Gate: <span id="gate-status" class="badge badge-yellow">PENDING</span></li><li>Execution Status: <span id="exec-status" class="badge">QUEUED</span></li><li>Artifact: <span id="artifact-info">None</span></li></ul></div></div>
<div class="card"><div class="card-title">ACTIVITY / LOG</div><div class="log-box" id="log-box">Console loaded...</div></div>
<script>
async function fetchStatus(){try{const res=await fetch('/api/status');if(!res.ok)throw new Error('API Connection Failed');const data=await res.json();document.getElementById('error-display').style.display='none';renderUI(data)}catch(err){showError('System Unavailable: '+err.message)}}
function renderUI(data){const sys=data.system||{};document.getElementById('sys-status').innerHTML='<span class="badge badge-green">'+(sys.status||'READY')+'</span>';document.getElementById('sys-project').innerText=sys.active_project||'None';document.getElementById('sys-mode').innerText=sys.execution_mode||'DETERMINISTIC';document.getElementById('sys-runner').innerText=sys.runner_status||'IDLE';document.getElementById('sys-lifecycle').innerText=sys.lifecycle_state||'PROJECT';document.querySelectorAll('.step').forEach(el=>el.classList.remove('active'));const activeStep=document.getElementById('flow-'+sys.lifecycle_state);if(activeStep)activeStep.classList.add('active');const cur=data.current_task||data.panel?.current_task;if(cur){document.getElementById('current-task-info').innerHTML='<strong>['+(cur.id||'-')+'] '+(cur.title||'Current Task')+'</strong><br>State: '+(cur.state||'-')+' | Auth: '+(cur.authority_status||'-')}else document.getElementById('current-task-info').innerText='No active task currently processing.';const tasks=data.tasks||data.panel?.proposed_tasks||[];document.getElementById('task-queue').innerHTML=tasks.length?'<ul>'+tasks.map(t=>'<li><strong>['+(t.id||'-')+']</strong> '+(t.title||'')+' <span class="badge badge-blue">'+(t.state||'-')+'</span></li>').join('')+'</ul>':'<em>No tasks in queue.</em>';const logs=data.activity_log||[];document.getElementById('log-box').innerHTML=logs.map(l=>'> '+l).join('<br>');const gate=data.authority_gate||{};document.getElementById('gate-status').innerText=gate.pending_approval?'PENDING':'READY'}
async function sendCommand(cmdName){try{const res=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmdName})});const result=await res.json();if(!res.ok||result.error)showError(result.error||'Command failed');else renderUI(result)}catch(err){showError('Command delivery failed: '+err.message)}}
function showError(msg){const d=document.getElementById('error-display');d.innerText=msg;d.style.display='block'}
setInterval(fetchStatus,3000);fetchStatus();
</script>
</body></html>"""

class AIPPPanelHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/','/index.html'): self.send_html_response(200,HTML_CONTENT)
        elif self.path=='/api/status': self.handle_get_status()
        else: self.send_error(404,'Endpoint not found')
    def do_POST(self):
        if self.path=='/api/command': self.handle_post_command()
        else: self.send_error(404,'Endpoint not found')
    def handle_get_status(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE,'r',encoding='utf-8') as f: state=json.load(f)
            else:
                state={'system':{'status':'READY','active_project':'None','execution_mode':'DETERMINISTIC','runner_status':'IDLE','lifecycle_state':'PROJECT'},'project':{'name':'Drive Sync Pending','state':'DISCOVERED'},'tasks':[],'current_task':None,'activity_log':['AIPP Control Panel initialized.']}
            self._sanitize_state(state); self.send_json_response(200,state)
        except Exception as e: self.send_json_response(500,{'error':f'State read error: {str(e)}'})
    def handle_post_command(self):
        try:
            length=int(self.headers.get('Content-Length',0)); body=self.rfile.read(length).decode('utf-8'); data=json.loads(body) if body else {}; command=data.get('command'); params=data.get('params',{})
            if not command: self.send_json_response(400,{'error':'Command parameter required'}); return
            result=self._execute_aipp_command(command,params); self.send_json_response(200,result)
        except json.JSONDecodeError: self.send_json_response(400,{'error':'Invalid JSON body'})
        except Exception as e: self.send_json_response(500,{'error':f'Command failed: {str(e)}'})
    def _execute_aipp_command(self,command,params):
        runner_script=BASE_DIR/'aipp_runner.py'
        if not runner_script.exists(): return {'status':'error','message':'aipp_runner.py not found in root directory'}
        cmd=[sys.executable,str(runner_script),'--command',command]
        if 'task_id' in params: cmd.extend(['--task-id',str(params['task_id'])])
        try:
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=60,cwd=str(BASE_DIR))
            return {'status':'success','output':proc.stdout.strip()} if proc.returncode==0 else {'status':'failed','error':proc.stderr.strip() or proc.stdout.strip()}
        except subprocess.TimeoutExpired: return {'status':'error','message':'Execution timed out'}
        except Exception as e: return {'status':'error','message':str(e)}
    def _sanitize_state(self,state):
        if isinstance(state,dict):
            for k in list(state.keys()):
                if any(s in k.lower() for s in ['token','secret','credential','password','key']): state[k]='[REDACTED]'
                elif isinstance(state[k],(dict,list)): self._sanitize_state(state[k])
        elif isinstance(state,list):
            for item in state: self._sanitize_state(item)
    def send_html_response(self,code,html_text):
        body=html_text.encode('utf-8'); self.send_response(code); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def send_json_response(self,code,payload):
        body=json.dumps(payload,ensure_ascii=False).encode('utf-8'); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

def run():
    PANEL_DIR.mkdir(parents=True,exist_ok=True); os.chdir(PANEL_DIR); server=HTTPServer(('127.0.0.1',PORT),AIPPPanelHandler); print(f'AIPP Control Panel running: http://127.0.0.1:{PORT}'); server.serve_forever()

if __name__=='__main__': run()
