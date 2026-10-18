/* AIPP operator panel client. All decisions remain enforced by the runtime authority gate. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  let state = null, busy = false;
  const token = () => { try { return localStorage.getItem('aipp_panel_token') || ''; } catch (_) { return ''; } };
  const headers = () => {
    const h = {'Content-Type':'application/json'};
    if (token()) h['X-AIPP-Panel-Token'] = token();
    return h;
  };
  const show = (id, yes) => { const el=$(id); if(el) el.classList.toggle('hidden', !yes); };
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function error(title, message, detail) {
    $('errorTitle').textContent=title; $('errorText').textContent=message || '';
    $('errorDetail').textContent=detail || ''; show('errorBox',true);
  }
  function request(path, method, body) {
    return fetch(path,{method:method||'GET',headers:headers(),body:body?JSON.stringify(body):undefined,cache:'no-store'})
      .then(async r => { const d=await r.json().catch(()=>({ok:false,error:'Geçersiz sunucu yanıtı'})); if(!r.ok){const e=new Error(d.error||('HTTP '+r.status));e.status=r.status;throw e;} return d; });
  }
  function currentTask(s) { const l=s.task_lifecycle||{}; return l.NOW || (l.FUTURE||[])[0] || null; }
  function render(s) {
    state=s; show('errorBox',false);
    const o=s.outcome||{};
    $('vHead').textContent=o.headline_tr||s.status||'Durum alındı';
    $('vText').textContent=o.detail_tr||'AIPP çalışma durumu güncellendi.';
    $('verdict').className='verdict '+(o.tone||'info');
    $('vProof').textContent=o.proven?'Kanıt mevcut':'Tamamlanma kanıtı henüz doğrulanmadı';
    const t=currentTask(s), now=(s.task_lifecycle||{}).NOW;
    show('decision',!!t && !now); show('inflight',!!now);
    if(t){$('dTitle').textContent=t.title||t.id||'Görev önerisi';$('dDesc').textContent=t.description||t.proposal_reason||'';$('dNext').textContent=t.next_action||'';$('dEvidence').textContent=JSON.stringify(t.source&&t.source.evidence||[],null,2);}
    if(now){$('iTitle').textContent=now.title||now.id;$('iText').textContent='Durum: '+(now.status||s.status)+'. Tamamlanma için doğrulama ve insan onayı gerekir.';}
    $('scanBtn').disabled=busy;$('approveBtn').disabled=busy;$('verifyBtn').disabled=busy;
    $('authState').textContent=token()?'Panel anahtarı kayıtlı':'Panel anahtarı gerekli';
    const pending=s.pending_human||[]; $('pendingCount').textContent='('+pending.length+')';
    $('pending').innerHTML=pending.length?pending.map(x=>'<li>'+esc(x.title||x.kind||'Karar bekliyor')+' — '+esc(x.text_tr||'')+'</li>').join(''):'<li class="empty">İnsan kararı bekleyen konu yok.</li>';
    const report=s.report||{}, scan=report.scan||{};
    $('scanBody').textContent=scan.text_tr||'Tarama raporu mevcut değil.';
    $('filesCount').textContent='('+((scan.files||[]).length)+')';
    $('files').innerHTML=(scan.files||[]).map(f=>'<li>'+esc(f.path||f.name)+' — '+esc(f.status||'Bilinmiyor')+'</li>').join('')||'<li class="empty">Dosya listesi yok.</li>';
    $('findingsCount').textContent='('+((report.findings||[]).length)+')';
    $('findings').innerHTML=(report.findings||[]).map(f=>'<li><b>'+esc(f.summary_tr||f.title||'Bulgu')+'</b><div>'+esc(f.type_tr||'')+'</div></li>').join('')||'<li class="empty">Rapor bulgusu yok.</li>';
    $('changes').innerHTML=(report.changes||[]).map(c=>'<li>'+esc(c.text_tr||c.text||'')+'</li>').join('')||'<li class="empty">Değişiklik kaydı yok.</li>';
    $('logCount').textContent='('+((report.events||[]).length)+')';
    $('log').innerHTML=(report.events||[]).slice().reverse().map(e=>'<li>'+esc(e.at||'')+' '+esc(e.text_tr||e.text||'')+'</li>').join('')||'<li class="empty">Henüz kayıt yok.</li>';
  }
  function run(command, task, extra) {
    if(busy)return; busy=true; $('scanBtn').disabled=$('approveBtn').disabled=$('verifyBtn').disabled=true;
    show('errorBox',false);
    return request('/api/command','POST',Object.assign({command:command,task:task||undefined},extra||{}))
      .then(d=>render(d.result||d))
      .catch(e=>error(e.status===401?'Panel anahtarı gerekli':'İşlem tamamlanamadı',e.message,'Ayarlar bölümüne panel anahtarını girip tekrar deneyin.'))
      .finally(()=>{busy=false; $('scanBtn').disabled=$('approveBtn').disabled=$('verifyBtn').disabled=false;});
  }
  $('scanBtn').addEventListener('click',()=>run('BAŞLA',null,{force_refresh:true}));
  $('approveBtn').addEventListener('click',()=>{const t=currentTask(state||{});if(t)run('APPROVE',t.id);});
  $('verifyBtn').addEventListener('click',()=>{const l=(state||{}).task_lifecycle||{},t=l.NOW;if(t)run('EXECUTE_APPROVED',t.id).then(()=>run('VERIFY',t.id));});
  $('saveToken').addEventListener('click',()=>{try{localStorage.setItem('aipp_panel_token',$('token').value.trim());}catch(_){} load();});
  function load(){request('/api/status').then(render).catch(e=>{ $('conn').textContent='Bağlantı yok';$('conn').className='conn bad';error(e.status===401?'Panel anahtarı gerekli':'Runtime’a ulaşılamadı',e.message,'Panel anahtarını girin veya Render servis durumunu kontrol edin.');});}
  $('token').value=token(); load();
})();