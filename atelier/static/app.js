'use strict';

const $ = (selector) => document.querySelector(selector);
const demoPrompt = 'Créer une liste de tâches : ajouter, terminer et supprimer une tâche, avec conservation des données.';
const terminal = new Set(['completed', 'prepared', 'needs_attention', 'failed', 'cancelled', 'interrupted']);
const labels = {queued:'En attente',planning:'Plan en préparation',routing:'Attribution des tâches',building:'Construction en cours',testing:'Tests en cours',reviewing:'Relectures en cours',repairing:'Corrections en cours',awaiting_input:'Ton avis est attendu',completed:'Projet validé',prepared:'Plan prêt',needs_attention:'À améliorer',failed:'Exécution en échec',cancelled:'Arrêtée',interrupted:'Interrompue',pending:'En attente',ready:'Prêt',running:'Au travail',blocked:'Bloqué'};
const roles = [
  ['chief','Chef de projet','Organise les missions et les dépendances','M5 20V7l7-4 7 4v13M9 20v-5h6v5M9 8h.01M15 8h.01'],
  ['router','Routeur','Choisit le bon spécialiste','M12 3v6M5 21v-6h14v6M12 9v6M3 21h4M17 21h4'],
  ['selector','Sélecteur de modèles','Adapte le modèle à la difficulté','M4 7h16M4 17h16M8 4v6M16 14v6'],
  ['liaison','Liaison avec toi','Te consulte aux grandes étapes','M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0ZM7 10h8M7 14h5'],
  ['backend','Développeur backend','Logique, données et persistance','m8 5-6 7 6 7M16 5l6 7-6 7M14 3l-4 18'],
  ['frontend','Développeur interface','Écrans et interactions','M3 4h18v16H3zM3 9h18M8 9v11'],
  ['tester','Testeur','Écrit et vérifie les tests','M9 3h6M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M8 14h8'],
  ['writer','Rédacteur','Explique comment lancer le projet','M5 3h10l4 4v14H5zM14 3v5h5M9 12h6M9 16h6'],
  ['reviewer','Relecteur','Vérifie le code et le comportement','M4 5h11v14H4zM8 9h3M8 13h3m3 1 3 3 5-6'],
  ['security','Sécurité','Cherche les vulnérabilités du code','M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6'],
];
const roleNames = Object.fromEntries(roles.map(([key, name]) => [key, name]));
let selectionVersion = 0, fileVersion = 0;
let config, current = null, activeQuestion = null, signature = '', loadedFiles = '', busy = false, customPrompt = '';

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined && text !== null) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function icon(path) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  line.setAttribute('d', path); svg.append(line); return svg;
}

function error(message) { $('#global-error').textContent = message; $('#global-error').hidden = !message; }

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type':'application/json', 'X-Atelier-Token': config?.token || '', ...options.headers}});
  if (!response.ok) {
    let message = 'Le serveur ne répond pas. Vérifie que l’atelier est lancé.';
    try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : 'Vérifie les informations saisies.'; } catch (_) { /* A non-JSON network response has no safe detail. */ }
    throw new Error(message);
  }
  return response.json();
}

function setMode() {
  const demo = $('#mode').value === 'demo';
  $('#prompt').readOnly = demo;
  $('#prompt').value = demo ? demoPrompt : (customPrompt || demoPrompt);
  $('#mode-note').textContent = demo
    ? 'Scénario fixe de liste de tâches. Les agents sont simulés ; les tests du code produit sont réels. Aucun appel payant.'
    : 'Les agents utilisent les modèles OpenAI. Chaque appel consomme ton quota API. Le code généré et ses tests s’exécutent localement.';
}

function renderAgents(run) {
  const target = $('#agents'); target.replaceChildren();
  const calls = run?.calls || [];
  const running = calls.filter(call => call.status === 'running');
  $('#active-count').textContent = running.length ? `${running.length} appel${running.length > 1 ? 's' : ''} en cours` : 'Aucun appel en cours';
  for (const [key, name, description, path] of roles) {
    const related = calls.filter(call => call.role === key || (call.role === 'worker' && run.tasks.find(task => task.id === call.task_id)?.specialist === key));
    const active = related.some(call => call.status === 'running') || (key === 'tester' && run?.status === 'testing');
    const waiting = key === 'liaison' && run?.status === 'awaiting_input';
    const complete = related.some(call => call.status === 'completed') && !active && !waiting;
    const row = node('div', null, `agent${active ? ' active' : complete ? ' complete' : ''}`);
    const symbol = node('div', null, 'agent-symbol'); symbol.append(icon(path));
    const content = node('div'); content.append(node('div',name,'agent-name'), node('div',description,'agent-desc'));
    row.append(symbol, content, node('span', waiting ? 'Attend ton avis' : active ? 'Au travail' : complete ? 'Intervenu' : 'Disponible', 'agent-state'));
    target.append(row);
  }
}

function renderJournal(run) {
  if (!run) return;
  const list = $('#journal'); const follow = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.replaceChildren();
  for (const event of run.events.slice(-100)) {
    const item = node('li', null, `journal-event ${event.kind}`);
    const time = node('time', new Date(event.at).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'})); time.dateTime=event.at;
    const content = node('div'); content.append(node('strong', roleNames[event.agent] || (event.agent === 'user' ? 'Toi' : 'Spécialiste')), node('p', event.message));
    item.append(time, content); list.append(item);
  }
  $('#event-count').textContent = `${run.events.length} événements`;
  if (follow) list.scrollTop = list.scrollHeight;
}

function renderQuestion(run) {
  const question = [...(terminal.has(run.status) ? [] : run.questions || [])].reverse().find(item => item.status === 'pending');
  $('#liaison').hidden = !question;
  if (!question) { activeQuestion = null; return; }
  $('#question-stage').textContent = question.blocking ? 'L’équipe attend ta réponse' : 'L’équipe continue';
  $('#question-text').textContent = question.question;
  $('#question-context').textContent = question.context;
  $('#answer-form button[value=continue]').textContent = question.stage === 'final' ? 'Valider le résultat' : question.stage === 'plan' ? 'Valider le plan' : 'Continuer';
  if (activeQuestion !== question.id) {
    activeQuestion = question.id;
    $('#answer').value=''; $('#answer-error').textContent='';
    $('#suggestions').replaceChildren();
    for (const suggestion of question.suggestions.slice(0,3)) {
      const button=node('button',suggestion); button.type='button';
      button.addEventListener('click',()=>{ $('#answer').value=suggestion; $('#answer').focus(); });
      $('#suggestions').append(button);
    }
  }
}

function renderPlan(run) {
  const target=$('#plan-content'); target.replaceChildren();
  if (!run.plan) { target.append(node('p','Le chef prépare le plan.','muted')); return; }
  target.append(node('p',run.plan.summary,'plan-summary'));
  const criteria=node('div',null,'criteria');
  for(const text of run.plan.acceptance_criteria) criteria.append(node('span',text,'criterion'));
  target.append(criteria);
  const tasks = run.tasks.length ? run.tasks : run.plan.tasks.map(task=>({...task,status:'pending'}));
  for(const task of tasks) {
    const row=node('div',null,'task-row'), text=node('div');
    text.append(node('h4',task.title),node('p',task.summary || task.instructions));
    if(task.model) text.append(node('span',`${roleNames[task.specialist] || task.specialist} · ${task.model}`,'task-model'));
    if(task.model_reason) text.append(node('p',task.model_reason));
    if(task.dependencies.length) text.append(node('p',`Attend : ${task.dependencies.join(', ')}`));
    row.append(text,node('span',task.status==='completed' ? 'Terminée' : labels[task.status] || task.status,`status-badge ${task.status}`)); target.append(row);
  }
  const details=node('details'), summary=node('summary','Lire le contrat commun');
  details.append(summary,node('div',run.plan.contract,'contract')); target.append(details);
}

function renderTests(run) {
  const target=$('#tests-content'); target.replaceChildren();
  if(!run.test_result) { target.append(node('p','Les tests seront exécutés après assemblage du code.','muted')); return; }
  const result=run.test_result;
  target.append(node('p',`${result.tests} test${result.tests > 1 ? 's' : ''} exécuté${result.tests > 1 ? 's' : ''} · ${result.passed ? 'Réussite' : 'Corrections nécessaires'}`,'test-summary'),node('pre',result.output));
  if(run.review) target.append(node('h3','Avis du relecteur'),node('p',run.review.summary,'muted'));
}

function renderSecurity(run) {
  const target=$('#security-content');target.replaceChildren();
  if(!run.security) { target.append(node('p','L’agent sécurité interviendra sur le projet assemblé, en parallèle du relecteur.','muted')); return; }
  if(run.mode==='demo') target.append(node('p','Rapport simulé de démonstration : aucun audit par un modèle n’a été réalisé.','security-summary'));
  target.append(node('p',run.security.summary,'security-summary'));
  for(const finding of run.security.findings) {
    const item=node('div',null,'finding'), title=node('div');
    title.append(node('span',{low:'Faible',medium:'Modérée',high:'Élevée',critical:'Critique'}[finding.severity],`severity ${finding.severity}`),node('strong',finding.path));
    item.append(title,node('p',finding.description),node('p',finding.recommendation));target.append(item);
  }
  if(!run.security.findings.length) target.append(node('p','Aucun constat signalé dans ce rapport.','muted'));
}

function renderUsage(run) {
  const rows=$('#calls-body');rows.replaceChildren();
  let incoming=0,outgoing=0,cost=0,priced=true;
  for(const call of run.calls) {
    incoming+=call.input_tokens||0;outgoing+=call.output_tokens||0;
    if(call.cost_usd===null && call.mode!=='demo') priced=false;else cost+=call.cost_usd||0;
    const row=node('tr');
    for(const value of [roleNames[call.role] || 'Spécialiste',call.mode==='demo' ? `${call.model} (simulé)` : call.model,
      call.duration_ms===null ? 'En cours' : `${(call.duration_ms/1000).toFixed(1)} s`,
      call.input_tokens===null ? 'Non mesuré' : `${call.input_tokens} / ${call.output_tokens}`,
      call.status==='completed' ? 'Réussi' : labels[call.status] || call.status]) row.append(node('td',value));
    rows.append(row);
  }
  $('#usage-summary').textContent=run.mode==='demo' ? `${run.calls.length} appels simulés · aucun token API consommé.`
    : `${run.calls.length} appels · ${incoming.toLocaleString('fr-FR')} tokens d’entrée · ${outgoing.toLocaleString('fr-FR')} tokens de sortie · ${priced ? `coût indicatif : ${cost.toFixed(4)} USD` : 'coût non configuré ou appel non terminé'}.`;
}

async function renderFiles(run) {
  const key=run.id+':'+run.tasks.filter(task=>task.status==='completed').length+':'+run.repairs;
  if(loadedFiles===key) return;
  const requestVersion = ++fileVersion;
  const files=await api(`/api/runs/${run.id}/files`);
  if(current?.id!==run.id || requestVersion!==fileVersion) return;
  const selected=$('#file-select').value; $('#file-select').replaceChildren(node('option','Choisir un fichier'));
  $('#file-select').firstChild.value='';
  for(const path of files) { const option=node('option',path);option.value=path;$('#file-select').append(option); }
  if(files.includes(selected)) $('#file-select').value=selected;
  loadedFiles=key;
  await loadSelectedFile();
}

function render(run) {
  if(current?.id !== run?.id) { selectionVersion++; fileVersion++; loadedFiles=''; $('#file-content').textContent='Sélectionne un fichier pour lire son contenu.'; }
  current=run;
  const active=run && !terminal.has(run.status);
  $('#launch').disabled=Boolean(active || busy);
  $('#cancel').hidden=!active;
  $('#results').hidden=!run;
  renderAgents(run);
  if(!run) { $('#run-status').textContent='Prête à démarrer'; $('#run-status').className='status-badge'; $('#liaison').hidden=true; $('#journal').replaceChildren(); $('#event-count').textContent='0 événements'; $('#run-summary').textContent='Le chef prépare le plan. Les spécialistes prennent ensuite le relais.'; return; }
  $('#run-status').textContent=labels[run.status] || run.status;
  $('#run-status').className=`status-badge ${run.status}`;
  $('#run-summary').textContent=run.error || run.summary || run.plan?.name || 'Le chef organise ta demande.';
  $('#report').href=`/api/runs/${run.id}/report`;
  $('#download').href=`/api/runs/${run.id}/download`;
  $('#download').hidden=run.plan_only || !run.test_result;
  renderQuestion(run);renderJournal(run);renderPlan(run);renderTests(run);renderSecurity(run);renderUsage(run);
  renderFiles(run).catch(e=>error(e.message));
}

async function history() {
  const runs=await api('/api/runs'); const list=$('#history');list.replaceChildren();
  if(!runs.length) list.append(node('p','Ton premier projet commence ici.','sidebar-empty'));
  for(const run of runs.slice(0,20)) {
    const button=node('button',null,`history-item${current?.id===run.id?' selected':''}`);
    button.append(node('strong',run.prompt),node('small',`${labels[run.status]||run.status} · ${run.mode==='demo'?'Démo':'OpenAI'}`));
    button.addEventListener('click',async()=>{try{const version=++selectionVersion; signature='';loadedFiles='';localStorage.setItem('atelier-run',run.id);const selected=await api(`/api/runs/${run.id}`);if(version!==selectionVersion)return;render(selected);await history();}catch(e){error(e.message);}});
    list.append(button);
  }
  return runs;
}

async function poll() {
  try {
    if(current) {
      const id=current.id, version=selectionVersion;
      const run=await api(`/api/runs/${id}`);
      if(current?.id!==id || selectionVersion!==version) { setTimeout(poll,900); return; }
      const key=JSON.stringify([run.id,run.status,run.events.length,run.questions.map(q=>q.status),run.tasks.map(t=>t.status)]);
      if(key!==signature) { signature=key;render(run);await history(); }
    }
  } catch(e) { error(e.message); }
  setTimeout(poll,900);
}

$('#mode').addEventListener('change',setMode);
$('#prompt').addEventListener('input',()=>{if($('#mode').value==='live')customPrompt=$('#prompt').value;});
$('#mission-form').addEventListener('submit',async event=>{
  event.preventDefault();error('');busy=true;$('#launch').disabled=true;
  try{
    const run=await api('/api/runs',{method:'POST',body:JSON.stringify({prompt:$('#prompt').value,mode:$('#mode').value,plan_only:$('#plan-only').checked})});
    signature='';loadedFiles='';localStorage.setItem('atelier-run',run.id);render(run);await history();
  }catch(e){error(e.message);}finally{busy=false;$('#launch').disabled=Boolean(current&&!terminal.has(current.status));}
});
$('#answer-form').addEventListener('submit',async event=>{
  event.preventDefault(); const action=event.submitter?.value||'continue';
  const answer=$('#answer').value.trim();
  if(action==='revise'&&!answer){$('#answer-error').textContent='Indique ce que tu souhaites adapter.';$('#answer').focus();return;}
  for(const button of $('#answer-form').querySelectorAll('button'))button.disabled=true;
  try{const run=await api(`/api/runs/${current.id}/answer`,{method:'POST',body:JSON.stringify({question_id:activeQuestion,action,answer})});render(run);}
  catch(e){$('#answer-error').textContent=e.message;}
  finally{for(const button of $('#answer-form').querySelectorAll('button'))button.disabled=false;}
});
$('#cancel').addEventListener('click',async()=>{try{render(await api(`/api/runs/${current.id}/cancel`,{method:'POST'}));await history();}catch(e){error(e.message);}});
$('#new-mission').addEventListener('click',()=>{
  if(current&&!terminal.has(current.status)){error('Une équipe est déjà active. Termine son point d’étape ou arrête son exécution avant une nouvelle mission.');return;}
  localStorage.removeItem('atelier-run');signature='';loadedFiles='';render(null);error('');setMode();$('#prompt').focus();history().catch(e=>error(e.message));
});
async function loadSelectedFile() {
  const id=current?.id, path=$('#file-select').value, version=++fileVersion;
  $('#file-content').textContent='Sélectionne un fichier pour lire son contenu.';
  if(!id || !path) return;
  try {
    const data=await api(`/api/runs/${id}/file?${new URLSearchParams({path})}`);
    if(current?.id===id && $('#file-select').value===path && version===fileVersion) $('#file-content').textContent=data.content;
  } catch(e) { if(version===fileVersion) error(e.message); }
}
$('#file-select').addEventListener('change',loadSelectedFile);

function switchTab(tab){
  for(const button of document.querySelectorAll('[role=tab]')){const selected=button===tab;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;$('#pane-'+button.dataset.pane).hidden=!selected;}
}
const tabs=[...document.querySelectorAll('[role=tab]')];
tabs.forEach((tab,index)=>{
  tab.addEventListener('click',()=>switchTab(tab));
  tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=tabs[(index+1)%tabs.length];if(event.key==='ArrowLeft')next=tabs[(index+tabs.length-1)%tabs.length];if(event.key==='Home')next=tabs[0];if(event.key==='End')next=tabs.at(-1);if(next){event.preventDefault();switchTab(next);next.focus();}});
});

(async()=>{
  try{
    config=await api('/api/config');
    $('#connection').textContent=config.live_available?'OpenAI configuré':'Mode démo disponible';$('#connection').classList.add('ready');
    $('#mode option[value=live]').disabled=!config.live_available;
    $('#model-list').textContent=`Modèle économique : ${config.models.economy}. Modèle avancé : ${config.models.advanced}. ${config.concurrency} appels simultanés maximum.`;
    setMode();renderAgents(null);
    const runs=await history();const saved=localStorage.getItem('atelier-run');
    const target=runs.find(run=>run.id===saved)||runs.find(run=>!terminal.has(run.status));
    if(target)render(await api(`/api/runs/${target.id}`));
    poll();
  }catch(e){$('#connection').textContent='Connexion interrompue';error(e.message);}
})();
