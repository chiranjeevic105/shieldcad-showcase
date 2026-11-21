const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let KEY = sessionStorage.getItem('shieldcad_key') || '', ROLE = '', cur = null, orig = {};
const EX_PART = 'Aluminium bracket, 120x60x8 mm, four M6 holes on a 100x40 pattern';
const EX_ASM = 'Steel plate 200x120x10 mm with four M8 holes 20 mm from edge\nSteel flange OD 80, bore 30, 12 mm thick, four M6 bolt holes on a 60 mm bolt circle, on top of part 1\nSteel spacer OD 50, ID 20, 40 mm long, on top of part 2';
const mode = () => document.querySelector('input[name=mode]:checked').value;
const COLORS = ['#7d96b8', '#b98a4e', '#6f9e7f', '#9a7bb0', '#bfae55', '#c87474'];
const TABS = ['chk', 'dl', 'par', 'hist'];

async function api(path, opt = {}) {
  const r = await fetch('/api' + path, {...opt, headers: {'X-API-Key': KEY, 'Content-Type': 'application/json'}});
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m } catch (e) {} throw new Error(r.status + ' ' + m) }
  return r;
}
const post = (p, b) => api(p, {method: 'POST', body: JSON.stringify(b)}).then(r => r.json());
function stage(n) {  // 1 = describing, 2 = confirming, 3 = generated
  $('s1').classList.toggle('active', n === 1); $('s1').classList.toggle('done', n >= 2);
  $('s2').classList.toggle('active', n === 2); $('s2').classList.toggle('done', n >= 3);
}
function tab(t) {
  TABS.forEach(k => { $('p-' + k).hidden = k !== t; document.querySelector('.tab[data-t=' + k + ']').setAttribute('aria-selected', k === t) });
}
function setMode() {
  const a = mode() === 'asm'; $('asmopt').hidden = !a;
  const v = $('q').value.trim(); if (!v || v === EX_PART || v === EX_ASM) $('q').value = a ? EX_ASM : EX_PART;
  $('q').rows = a ? 6 : 3; $('gen').disabled = true; $('errs').innerHTML = ''; stage(1);
}
async function signin() {
  KEY = $('key').value || KEY;
  try {
    const u = await (await api('/me')).json();
    sessionStorage.setItem('shieldcad_key', KEY); ROLE = u.role;
    $('who').textContent = u.user + ' · ' + u.role; $('login').hidden = true; $('app').hidden = false;
    $('ver').hidden = ROLE !== 'admin'; if (ROLE === 'viewer') $('interp').disabled = true; setMode(); history(); size();
  } catch (e) { $('lerr').textContent = e.message; sessionStorage.removeItem('shieldcad_key') }
}
function renderSpec(spec) {
  const rows = [['part', spec.type.replace('_', ' ')], ['material', spec.material || 'not given']];
  const flat = (o, p) => Object.entries(o).forEach(([k, v]) => { if (k === 'points' || k === 'bbox_hint') return; if (v && typeof v === 'object') flat(v, k + '.'); else rows.push([p + k, v]) });
  flat(spec.params, '');
  $('spec').className = 'spec';
  $('spec').innerHTML = '<dl class="kv">' + rows.map(([k, v]) => '<dt>' + esc(k.replace(/_/g, ' ')) + '</dt><dd>' + esc(v) + '</dd>').join('') + '</dl>' +
    (spec.notes.length ? '<p class="note">' + esc(spec.notes.join(' ')) + '</p>' : '');
}
function showErrors(errs) { $('errs').innerHTML = errs.map(e => '<div class="row bad">⚠ ' + esc(e) + '</div>').join('') }
async function interp() {
  $('gen').disabled = true; $('errs').innerHTML = '';
  try {
    let errs;
    if (mode() === 'asm') {
      const d = await post('/assembly/parse', {prompt: $('q').value, fuse: $('fuse').checked}); errs = d.errors;
      $('spec').className = 'spec'; $('spec').innerHTML = '<ol class="plist">' + d.summary.map(s => '<li>' + esc(s.replace(/^\d+ · /, '')) + '</li>').join('') + '</ol>';
    } else {
      const d = await post('/parse', {prompt: $('q').value}); errs = d.errors; renderSpec(d.spec);
    }
    showErrors(errs); $('gen').disabled = errs.length > 0; stage(errs.length ? 1 : 2);
  } catch (e) { showErrors([e.message]) }
}
async function generate() {
  $('gen').disabled = true; $('chk').className = 'mut'; $('chk').textContent = 'Generating…'; tab('chk');
  try {
    const d = mode() === 'asm' ? await post('/assembly/generate', {prompt: $('q').value, fuse: $('fuse').checked, confirmed: true})
                               : await post('/generate', {prompt: $('q').value, confirmed: true});
    if (d.status === 'needs_input') { $('chk').innerHTML = d.errors.map(e => '<div class="row bad">' + esc(e) + '</div>').join(''); stage(1); return }
    await showRun(d.run_id, d.report); history();
  } catch (e) { $('chk').innerHTML = '<div class="row bad">' + esc(e.message) + '</div>' }
}
const FMT = {'part.step': ['STEP', 'Single solid, any CAD'], 'part.iges': ['IGES', 'Older CAD exchange'], 'part.brep': ['BREP', 'FreeCAD, OpenCascade'], 'part.stl': ['STL', '3D printing'],
  'part.3mf': ['3MF', '3D printing with units'], 'part.obj': ['OBJ', 'Blender, mesh tools'], 'part.glb': ['GLB', 'Web viewers, AR'], 'assembly.step': ['STEP', 'Separate named parts'],
  'assembly.glb': ['GLB', 'Coloured parts'], 'part.py': ['PY', 'Parametric CadQuery source'], 'report.json': ['JSON', 'Measurements and checks']};
function dlButtons(rep) {
  const f = (rep.files || []).concat(['part.py', 'report.json']), isA = !!rep.assembly;
  const card = n => { const m = n.match(/^component_(\d+)\.(\w+)$/), x = FMT[n] || [m ? m[2].toUpperCase() : n, m ? 'Part ' + m[1] + ', placed' : '']; return '<button class="file" data-f="' + esc(n) + '"><b>' + x[0] + '</b><span>' + esc(x[1]) + '</span></button>' };
  const grp = (t, ns) => ns.length ? '<h3 class="fh">' + t + '</h3><div class="files">' + ns.map(card).join('') + '</div>' : '';
  return grp(isA ? 'Single fused solid' : 'Part', f.filter(n => /^part\.(step|iges|brep|stl|3mf|obj|glb)$/.test(n))) + grp('Assembly, separate bodies', f.filter(n => /^assembly\./.test(n))) +
    grp('Each component, placed', f.filter(n => /^component_/.test(n))) + grp('Source and report', f.filter(n => n === 'part.py' || n === 'report.json'));
}
function renderChecks(rep) {
  const cs = (rep.validation && rep.validation.checks) || [], bad = cs.filter(c => !c.pass).length, groups = {};
  let h = '<div class="sum ' + (bad ? 'bad' : 'ok') + '">' + (bad ? bad + ' of ' + cs.length + ' checks failed' : cs.length ? 'All ' + cs.length + ' checks passed' : 'No checks ran') + '</div>';
  cs.forEach(c => { const p = c.check.includes(': ') ? c.check.split(': ') : ['', c.check]; (groups[p[0]] = groups[p[0]] || []).push([p[1], c]) });
  const gl = g => g.startsWith('component_') ? 'Part ' + g.slice(10) : g === 'fused' ? 'Fused solid' : g;
  Object.keys(groups).forEach(g => { h += (g ? '<h3 class="gh">' + esc(gl(g)) + '</h3>' : '') + groups[g].map(([n, c]) => '<div class="row"><span class="pill ' + (c.pass ? 'ok' : 'bad') + '">' + (c.pass ? 'Pass' : 'Fail') + '</span><span><b>' + esc(n.replace(/_/g, ' ')) + '</b>' + esc(c.detail) + '</span></div>').join('') });
  if (rep.assembly && (rep.assembly.interference || []).length) h += '<p class="note">Overlap merged into the fused solid: ' + rep.assembly.interference.map(o => 'parts ' + o[0] + ' and ' + o[1] + ', ' + o[2].toFixed(0) + ' mm³').join('; ') + '</p>';
  if (rep.error) h += '<div class="row bad">' + esc(rep.error) + '</div>';
  if (rep.sandbox) h += '<p class="mut" style="font-size:12px;margin:12px 0 0">Sandbox: network ' + (rep.sandbox.network_isolated ? 'isolated' : 'not isolated on this host') + ', ' + rep.sandbox.mem_limit_mb + ' MB limit.</p>';
  $('chk').className = ''; $('chk').innerHTML = h;
  const b = $('bdgChk'); b.className = 'badge ' + (bad ? 'bad' : 'ok'); b.textContent = bad ? bad + ' failed' : cs.length + ' passed';
}
function fillTitle(rep) {
  const ok = rep.validation && rep.validation.passed, a = rep.assembly;
  $('tbPart').textContent = a ? 'Assembly, ' + a.plan.components.length + ' parts' : rep.spec.type.replace('_', ' ') + (rep.spec.material ? ', ' + rep.spec.material : '');
  $('tbRev').textContent = rep.revision || 1; $('tbMass').textContent = rep.est_mass_kg ? rep.est_mass_kg + ' kg' : '–';
  $('tbStatus').textContent = ok ? 'Passed' : 'Failed'; $('tbStatus').className = ok ? 'ok' : 'bad'; $('tbRun').textContent = rep.run_id.slice(-6);
}
async function showRun(id, rep) {
  rep = rep || await (await api('/runs/' + id)).json(); cur = id;
  renderChecks(rep); fillTitle(rep); renderParams(rep); stage(3); tab('chk');
  $('dl').className = ''; $('dl').innerHTML = dlButtons(rep);
  $('dl').querySelectorAll('button').forEach(b => b.onclick = () => download(b.dataset.f));
  try {
    const comps = (rep.files || []).filter(n => /^component_\d+\.stl$/.test(n));
    const names = rep.assembly && comps.length ? comps : ['part.stl'];
    const bufs = await Promise.all(names.map(n => api('/runs/' + id + '/files/' + n).then(r => r.arrayBuffer())));
    showModels(bufs.map((b, i) => ({buf: b, color: rep.assembly ? COLORS[i % COLORS.length] : null})));
  } catch (e) {}
}
function renderParams(rep) {
  orig = rep.editable || {}; const ks = Object.keys(orig), by = {};
  ks.forEach(k => { const m = k.match(/^(\d+)\.(.+)$/), g = m ? 'Part ' + m[1] : ''; (by[g] = by[g] || []).push(k) });
  $('rerr').innerHTML = ''; $('par').className = ks.length ? '' : 'mut';
  $('par').innerHTML = (rep.revision > 1 ? '<p class="mut">Revision ' + rep.revision + ', edited from ' + esc(rep.parent_run_id) + '.</p>' : '') +
    (ks.length ? Object.keys(by).map(g => (g ? '<h3 class="gh">' + g + '</h3>' : '') + '<div class="pgrid">' + by[g].map(k => '<label class="pl"><span>' + esc(k.replace(/^\d+\./, '').replace(/_/g, ' ')) + '</span><input type="number" step="any" min="0" data-k="' + esc(k) + '" value="' + esc(orig[k]) + '"></label>').join('') + '</div>').join('') : 'This part has no editable parameters.');
  $('rev').disabled = ROLE === 'viewer' || !ks.length;
}
async function revise() {
  const ch = {}; document.querySelectorAll('#par input').forEach(i => { if (+i.value !== orig[i.dataset.k]) ch[i.dataset.k] = +i.value });
  if (!Object.keys(ch).length) { $('rerr').innerHTML = '<div class="row bad">Change at least one value.</div>'; return }
  try {
    const d = await post('/runs/' + cur + '/revise', {changes: ch});
    if (d.status === 'needs_input') { $('rerr').innerHTML = d.errors.map(e => '<div class="row bad">' + esc(e) + '</div>').join(''); return }
    await showRun(d.run_id, d.report); history();
  } catch (e) { $('rerr').innerHTML = '<div class="row bad">' + esc(e.message) + '</div>' }
}
async function download(n) {
  const b = await (await api('/runs/' + cur + '/files/' + n)).blob(), a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = n; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
const when = id => { const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/); return m ? m[3] + '/' + m[2] + ' ' + m[4] + ':' + m[5] : '' };
async function history() {
  const rs = await (await api('/runs')).json();
  $('hist').className = rs.length ? '' : 'mut'; $('hist').innerHTML = rs.length ? '' : 'No runs yet. Generate a part and it will be listed here.';
  rs.forEach(r => { const b = document.createElement('button'); b.className = 'hrow';
    b.innerHTML = '<i class="' + (r.passed ? 'ok' : 'bad') + '">' + (r.passed ? '✓' : '✗') + '</i><span>' + (r.kind === 'assembly' ? 'Assembly: ' : '') + (r.revision > 1 ? 'rev ' + r.revision + ' · ' : '') + esc((r.prompt || r.run_id).replace(/\s+/g, ' ').slice(0, 64)) + '</span><em>' + when(r.run_id) + '</em>';
    b.onclick = () => showRun(r.run_id); $('hist').appendChild(b) });
}
async function verify() {
  const d = await (await api('/audit/verify')).json();
  $('verout').textContent = d.ok ? 'Audit chain verified.' : 'Tampered at line ' + d.first_bad_line;
}

// 3D viewer (binary or ASCII STL; several models at once for assemblies)
const cv = $('cv'), R = new THREE.WebGLRenderer({canvas: cv, antialias: true, alpha: true}), sc = new THREE.Scene(), cam = new THREE.PerspectiveCamera(40, 1, 1, 10000);
sc.add(new THREE.HemisphereLight(0xffffff, 0x445566, .9)); const dl = new THREE.DirectionalLight(0xffffff, .8); dl.position.set(1, 2, 1.5); sc.add(dl);
let grp = null, th = .8, ph = 1.05, dist = 300, tg = new THREE.Vector3(), dr = null;
const place = () => { cam.position.set(tg.x + dist * Math.sin(ph) * Math.sin(th), tg.y + dist * Math.cos(ph), tg.z + dist * Math.sin(ph) * Math.cos(th)); cam.lookAt(tg); R.render(sc, cam) };
function size() { const r = cv.parentElement.getBoundingClientRect(); if (!r.width) return; R.setPixelRatio(Math.min(devicePixelRatio, 2)); R.setSize(r.width, r.height, false); cam.aspect = r.width / r.height; cam.updateProjectionMatrix(); place() }
new ResizeObserver(size).observe(cv.parentElement);
cv.onpointerdown = e => { dr = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId) };
cv.onpointermove = e => { if (!dr) return; th -= (e.clientX - dr[0]) * .01; ph = Math.min(3.04, Math.max(.1, ph - (e.clientY - dr[1]) * .01)); dr = [e.clientX, e.clientY]; place() };
cv.onpointerup = () => dr = null;
cv.addEventListener('wheel', e => { e.preventDefault(); dist *= 1 + Math.sign(e.deltaY) * .08; place() }, {passive: false});
function parseSTL(buf) {
  const dv = new DataView(buf), n = dv.getUint32(80, true), pos = [];
  if (84 + 50 * n === buf.byteLength) {
    for (let i = 0; i < n; i++) for (let v = 0; v < 3; v++) for (let c = 0; c < 3; c++) pos.push(dv.getFloat32(84 + 50 * i + 12 + 12 * v + 4 * c, true));
  } else {
    const t = new TextDecoder().decode(buf), re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/g; let m;
    while ((m = re.exec(t))) pos.push(+m[1], +m[2], +m[3]);
  }
  return new Float32Array(pos);
}
function showModels(list) {
  if (grp) { sc.remove(grp); grp.traverse(o => o.geometry && o.geometry.dispose()) }
  const css = getComputedStyle(document.documentElement); grp = new THREE.Group();
  list.forEach(({buf, color}) => {
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(parseSTL(buf), 3)); geo.computeVertexNormals();
    grp.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: color || css.getPropertyValue('--mesh').trim(), metalness: .35, roughness: .5})));
    grp.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30), new THREE.LineBasicMaterial({color: css.getPropertyValue('--edge').trim()})));
  });
  grp.rotation.x = -Math.PI / 2; sc.add(grp); grp.updateMatrixWorld(true);
  const bx = new THREE.Box3().setFromObject(grp); bx.getCenter(tg); dist = bx.getSize(new THREE.Vector3()).length() * 1.5; place();
}
$('signin').onclick = signin; $('key').onkeydown = e => { if (e.key === 'Enter') signin() };
$('interp').onclick = interp; $('gen').onclick = generate; $('ver').onclick = verify; $('rev').onclick = revise;
document.querySelectorAll('input[name=mode]').forEach(r => r.onchange = setMode);
$('q').oninput = () => { $('gen').disabled = true; stage(1) };  // spec must be re-confirmed after any edit
$('fuse').onchange = () => { $('gen').disabled = true; stage(1) };
document.querySelectorAll('.tab').forEach(b => b.onclick = () => tab(b.dataset.t));
if (KEY) signin();
