"""Gera o artefato HTML de busca a partir de groups.json + hotspots.json.
Estilizado 100% sobre os tokens do Enter UI Design System (Geist + tokens fig)."""
import json, sys, html, datetime as dt

LOGO = open("../data/logo-enter.svg", encoding="utf-8").read() if __import__("os").path.exists("../data/logo-enter.svg") else "<b>enter</b>"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title> Enter — Small Gatherings</title>
<style>
/* ── Geist (auto-hospedado, como o Design System da Enter) ── */
@font-face{font-family:"Geist";src:url("fonts/Geist-Regular.ttf") format("truetype");font-weight:400;font-display:swap}
@font-face{font-family:"Geist";src:url("fonts/Geist-Medium.ttf") format("truetype");font-weight:500;font-display:swap}
@font-face{font-family:"Geist";src:url("fonts/Geist-SemiBold.ttf") format("truetype");font-weight:600;font-display:swap}
@font-face{font-family:"Geist";src:url("fonts/Geist-Bold.ttf") format("truetype");font-weight:700;font-display:swap}
@font-face{font-family:"Geist Mono";src:url("fonts/GeistMono-Regular.ttf") format("truetype");font-weight:400;font-display:swap}
@font-face{font-family:"Geist Mono";src:url("fonts/GeistMono-Medium.ttf") format("truetype");font-weight:500;font-display:swap}

:root{
  /* cores semânticas (light) — fig-tokens.css */
  --bg:rgb(255,255,255); --bg-2:rgb(250,250,250); --surface:rgba(0,0,0,.05); --inverse:rgb(23,24,30);
  --brand:rgb(255,174,53); --brand-100:rgb(255,238,196); --brand-200:rgb(255,217,138);
  --brand-400:rgb(227,141,31); --on-brand:rgb(10,10,10);
  --tx:rgb(23,23,23); --tx-2:rgb(82,82,82); --tx-3:rgb(161,161,161); --tx-inv:rgb(250,250,250);
  /* strokes como anéis inset (o DS nunca usa border) */
  --ring:inset 0 0 0 1px rgba(0,0,0,.15); --ring-2:inset 0 0 0 1px rgba(0,0,0,.10);
  --ring-3:inset 0 0 0 1px rgba(0,0,0,.05); --ring-dark:inset 0 0 0 1px rgba(255,255,255,.15);
  --ring-focus:inset 0 0 0 2px rgb(0,0,0); --ring-brand:inset 0 0 0 2px rgb(255,174,53);
  --shadow-overlay:0 4px 16px rgba(0,0,0,.15);
  --font:"Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  --mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --r-lg:8px; --r-xl:12px; --r-2xl:16px; --r-full:9999px;
  --ease:cubic-bezier(.2,0,.2,1); --dur:180ms;
  /* tag líder (tag-purple) + fills saturados oficiais p/ avatares */
  --tag-lead-bg:rgb(226,217,238); --tag-lead-fg:rgb(99,71,148);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);font-family:var(--font);
  font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:960px;margin:0 auto;padding:clamp(20px,5vw,56px) 20px 80px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:clamp(32px,6vw,56px)}
header .logo{height:22px;width:auto;display:block}
.eyebrow{font-family:var(--mono);font-weight:500;font-size:12px;letter-spacing:1.6px;
  text-transform:uppercase;color:var(--tx-3)}
/* hero */
.hero h1{font-weight:600;font-size:clamp(30px,7vw,48px);line-height:1.05;
  letter-spacing:-.4px;margin:0 0 14px}
.hero p{margin:0 0 28px;color:var(--tx-2);font-size:clamp(15px,2.4vw,17px)}
.searchbox{position:relative;max-width:560px}
#q{width:100%;font-family:var(--font);font-size:18px;font-weight:400;height:56px;
  padding:0 18px 0 50px;border:0;border-radius:var(--r-xl);background:var(--bg);
  color:var(--tx);box-shadow:var(--ring);outline:none;transition:box-shadow var(--dur) var(--ease)}
#q::placeholder{color:var(--tx-3)}
#q:focus{box-shadow:var(--ring-focus)}
.searchbox svg.ic{position:absolute;left:17px;top:50%;transform:translateY(-50%);color:var(--tx-3)}
.results{margin-top:36px}
.empty{color:var(--tx-2);margin-top:24px;font-size:15px}
.pick{display:flex;flex-direction:column;gap:8px;margin-top:14px}
.pick button{text-align:left;font:inherit;font-size:15px;background:var(--bg);border:0;
  box-shadow:var(--ring-2);border-radius:var(--r-lg);padding:13px 15px;cursor:pointer;
  transition:box-shadow var(--dur) var(--ease)}
.pick button:hover{box-shadow:var(--ring)}
/* group card */
.groupcard{background:var(--bg);box-shadow:var(--ring);border-radius:var(--r-2xl);overflow:hidden;
  opacity:0;transform:translateY(8px);animation:rise .4s var(--ease) forwards}
@keyframes rise{to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.groupcard{animation:none;opacity:1;transform:none}}
.gc-top{padding:22px 24px;box-shadow:inset 0 -1px 0 rgba(0,0,0,.05);
  display:flex;justify-content:space-between;align-items:flex-end;gap:14px;flex-wrap:wrap}
.gc-top .you{font-family:var(--mono);font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--tx-3);margin:0 0 6px}
.gc-top h2{font-weight:600;font-size:22px;margin:0;letter-spacing:-.4px}
.chip{font-size:13px;font-weight:500;padding:7px 13px;border-radius:var(--r-full);
  background:var(--brand);color:var(--on-brand);white-space:nowrap}
.members{list-style:none;margin:0;padding:6px 12px}
.member{display:flex;align-items:center;gap:14px;padding:12px;border-radius:var(--r-lg)}
.member+.member{box-shadow:inset 0 1px 0 rgba(0,0,0,.05)}
.member .av{width:40px;height:40px;border-radius:var(--r-full);flex:none;display:grid;place-items:center;
  font-weight:500;color:#fff;font-size:15px}
.member .who{flex:1;min-width:0}
.member .nm{font-weight:500;font-size:15px}
.member .meta{color:var(--tx-2);font-size:13px}
.lead{font-size:12px;font-weight:500;color:var(--tag-lead-fg);background:var(--tag-lead-bg);
  padding:4px 10px;border-radius:var(--r-full)}
.member.me{background:var(--brand-100);box-shadow:var(--ring-brand)}
/* hotspots — superfície inversa oficial */
.spots{margin-top:20px;background:var(--inverse);color:var(--tx-inv);border-radius:var(--r-2xl);padding:24px}
.spots-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:16px}
.spots h3{font-weight:600;margin:0;font-size:19px;letter-spacing:-.4px}
.spots-count{font-family:var(--mono);font-size:12px;color:rgba(250,250,250,.5)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.filter-btn{font:inherit;font-size:13px;font-weight:500;color:rgba(250,250,250,.75);
  background:rgba(255,255,255,.06);box-shadow:var(--ring-dark);border:0;border-radius:var(--r-full);
  padding:8px 15px;cursor:pointer;transition:background var(--dur) var(--ease),color var(--dur) var(--ease)}
.filter-btn:hover{background:rgba(255,255,255,.12)}
.filter-btn.active{background:var(--brand);color:var(--on-brand);box-shadow:none;font-weight:600}
.spotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:12px}
.spot{display:block;background:rgba(255,255,255,.05);box-shadow:var(--ring-dark);border-radius:var(--r-xl);
  padding:14px 16px;color:inherit;text-decoration:none;transition:background var(--dur) var(--ease)}
.spot:hover{background:rgba(255,255,255,.1)}
.spot .c{font-family:var(--mono);font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--brand)}
.spot .n{font-weight:500;margin:6px 0 2px;font-size:15px}
.spot .a{font-size:13px;color:rgba(250,250,250,.7)}
.spot .no{font-size:12px;color:rgba(250,250,250,.55);margin-top:6px;line-height:1.45}
.spots-empty{color:rgba(250,250,250,.55);font-size:14px;padding:8px 0}
/* botão "ver todos os grupos" */
.btn{display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:14px;font-weight:500;
  background:var(--bg);border:0;box-shadow:var(--ring-2);border-radius:var(--r-full);
  padding:10px 18px;cursor:pointer;color:var(--tx);transition:box-shadow var(--dur) var(--ease)}
.btn:hover{box-shadow:var(--ring)}
/* browse */
.browse{margin-top:56px;box-shadow:inset 0 1px 0 rgba(0,0,0,.05);padding-top:28px}
.browse h3{font-weight:600;font-size:16px;margin:0 0 16px}
.allgroups{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:14px}
.mini{background:var(--bg-2);box-shadow:var(--ring-3);border-radius:var(--r-xl);padding:15px 16px}
.mini h4{font-weight:600;margin:0 0 9px;font-size:14px}
.mini ul{margin:0;padding-left:0;list-style:none}
.mini li{font-size:13px;padding:3px 0;color:var(--tx-2)}
.mini li b{color:var(--tx);font-weight:500}
.mini .star{color:var(--brand-400)}
.wa-note{margin-top:24px;color:var(--tx-2);font-size:13px;text-align:center}
footer{margin-top:20px;color:var(--tx-3);font-size:12px;text-align:center;font-family:var(--mono);letter-spacing:.3px}
footer a{color:inherit;text-decoration:underline}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="logo">__LOGO__</span>
    <span class="eyebrow">Small Gatherings · __MONTH__</span>
  </header>

  <section class="hero">
    <h1>Ache seu grupo de Small Gathering do mês</h1>
    <p>Todos os meses a gente mistura o time da Enter para que mais pessoas se conheçam para além do escritório. Aproveite esse momento para viver uma experiência super legal e diferente (seja um jantar especial, um novo hobbie, um esporte) e se integrar com pessoas novas!</p>
    <div class="searchbox">
      <svg class="ic" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
      <input id="q" type="search" placeholder="Busque seu nome aqui!" autocomplete="off" autofocus aria-label="Buscar seu nome">
    </div>
  </section>

  <div class="results" id="results"></div>

  <div class="spots">
    <div class="spots-head"><h3>Onde marcar</h3><span class="spots-count" id="spots-count"></span></div>
    <div class="filters" id="filters"></div>
    <div class="spotgrid" id="spotgrid"></div>
  </div>

  <div class="browse">
    <h3>Todos os grupos</h3>
    <div class="allgroups" id="allgroups"></div>
    <div style="text-align:center;margin-top:16px"><button class="btn" id="more-groups">Ver todos os __NGROUPS__ grupos</button></div>
  </div>

  <p class="wa-note">Lembrem-se de sempre mandar suas fotos de small gathering em nosso grupo do WhatsApp (Black Pearl)</p>

  <footer>Dúvidas? fale com o time de People <a href="https://slack.com/app_redirect?channel=D0BT9B8SPRS" target="_blank" rel="noopener">@Gabriela Barbosa</a></footer>
</div>

<script>
const DATA = __DATA__;
const HOTSPOTS = __HOTSPOTS__;
const AV = ["rgb(227,86,71)","rgb(80,179,49)","rgb(47,159,198)","rgb(148,114,194)","rgb(198,152,28)","rgb(227,141,31)"];
const norm = s => (s||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
function initials(n){const p=n.trim().split(/\s+/);return ((p[0]||"")[0]||"")+((p[p.length-1]||"")[0]||"");}
function groupOf(id){return DATA.groups.find(g=>g.some(p=>p.id===id));}

function renderGroup(group, meId){
  const leader = group.find(p=>p.is_leader) || group[0];
  const members = group.map(p=>{
    const isMe = p.id===meId;
    const av = AV[(p.name.charCodeAt(0)+(p.name.charCodeAt(1)||0))%AV.length];
    const meta = [p.team, p.tenure_label].filter(Boolean).join(' · ');
    return `<li class="member ${isMe?'me':''}">
      <div class="av" style="background:${av}">${initials(p.name).toUpperCase()}</div>
      <div class="who"><div class="nm">${p.name}${isMe?' · você':''}</div>
      <div class="meta">${meta}</div></div>
      ${p.is_leader?'<span class="lead">capitão</span>':''}
    </li>`;}).join("");
  return `<div class="groupcard">
    <div class="gc-top"><div><p class="you">Seu Small Gathering de ${DATA.month}</p>
      <h2>${group.length} Pessoas</h2></div>
      <span class="chip">${leader.name.split(' ')[0]} é responsável por garantir que o Small Gathering vai sair do papel!</span></div>
    <ul class="members">${members}</ul>
  </div>`;
}

const results = document.getElementById('results');
function show(id){results.innerHTML = renderGroup(groupOf(id), id);}
function search(v){
  const q = norm(v);
  if(q.length<2){results.innerHTML="";return;}
  const all = DATA.groups.flat();
  const hits = all.filter(p=>norm(p.name).includes(q));
  if(hits.length===0){results.innerHTML=`<p class="empty">Não achei ninguém com “${v}”. Confere a grafia ou tenta só o primeiro nome.</p>`;return;}
  if(hits.length===1){show(hits[0].id);return;}
  results.innerHTML = `<p class="empty">Achei ${hits.length} pessoas</p>
    <div class="pick">${hits.slice(0,12).map(p=>`<button data-id="${p.id}">${[p.name,p.team].filter(Boolean).join(' · ')}</button>`).join("")}</div>`;
  results.querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.id));
}
let t; document.getElementById('q').addEventListener('input',e=>{clearTimeout(t);t=setTimeout(()=>search(e.target.value),120);});

const spotCats = [...new Set((HOTSPOTS.items||[]).map(s=>s.cat))];
let activeCat = 'Todas';
function renderFilters(){
  document.getElementById('filters').innerHTML = ['Todas', ...spotCats].map(c=>
    `<button class="filter-btn ${c===activeCat?'active':''}" data-cat="${c}">${c}</button>`
  ).join("");
  document.querySelectorAll('#filters .filter-btn').forEach(btn=>{
    btn.onclick = ()=>{ activeCat = btn.dataset.cat; renderFilters(); renderSpots(); };
  });
}
function renderSpots(){
  const items = activeCat==='Todas' ? (HOTSPOTS.items||[]) : (HOTSPOTS.items||[]).filter(s=>s.cat===activeCat);
  const grid = document.getElementById('spotgrid');
  grid.innerHTML = items.length ? items.map(s=>{
    const url = s.maps_url || ('https://www.google.com/maps/search/?api=1&query='+encodeURIComponent((s.name||'')+' '+(s.area||'')));
    return `<a class="spot" href="${url}" target="_blank" rel="noopener">
      <div class="c">${s.cat}</div><div class="n">${s.name}</div>
      <div class="a">${s.area}</div>${s.note?`<div class="no">${s.note}</div>`:''}</a>`;
  }).join("") : `<p class="spots-empty">Sem sugestões nessa categoria ainda.</p>`;
  document.getElementById('spots-count').textContent = items.length + (items.length===1?' sugestão':' sugestões');
}
renderFilters();
renderSpots();

function renderMini(list){
  return list.map((g,i)=>`<div class="mini"><h4>Grupo ${i+1}</h4><ul>${
    g.map(p=>`<li>${p.is_leader?'<span class="star">★</span> ':''}<b>${p.name}</b>${p.team?' · '+p.team:''}</li>`).join("")}</ul></div>`).join("");
}
document.getElementById('allgroups').innerHTML = renderMini(DATA.groups.slice(0,3));
const moreBtn = document.getElementById('more-groups');
if(DATA.groups.length<=3){ moreBtn.remove(); }
else{
  moreBtn.onclick = function(){
    document.getElementById('allgroups').innerHTML = renderMini(DATA.groups);
    this.remove();
  };
}
</script>
</body>
</html>"""

def main(groups_path, hotspots_path, out_path):
    data = json.load(open(groups_path, encoding="utf-8"))
    hot = json.load(open(hotspots_path, encoding="utf-8"))
    n_groups = len(data.get("groups", []))
    out = (TEMPLATE
        .replace("__LOGO__", LOGO)
        .replace("__MONTH__", html.escape(data.get("month","")))
        .replace("__GENERATED__", html.escape(data.get("generated_at", dt.date.today().isoformat())))
        .replace("__NGROUPS__", str(n_groups))
        .replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__HOTSPOTS__", json.dumps(hot, ensure_ascii=False)))
    open(out_path, "w", encoding="utf-8").write(out)
    print("Artefato gerado:", out_path)

if __name__ == "__main__":
    main(*(sys.argv[1:4] or ["../data/groups.json","../data/hotspots.json","../data/index.html"]))
