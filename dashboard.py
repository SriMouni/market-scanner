"""Build docs/index.html - one static page (works opened locally or on GitHub Pages)."""
import json

from common import CONFIG, DATA, DOCS, now_ist, read_csv, read_json

TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Scanner</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#5f6b7a;--line:#e3e7ec;--soft:#f1f3f6;--up:#0f8a4b;--upbg:#e5f5ec;
--dn:#c62f2f;--dnbg:#fbe9e9;--acc:#2955d9;--accbg:#e8eefc;--warn:#9a6a00;--warnbg:#fdf3dc;--ce:#d9534f;--pe:#1f9d61}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1217;--card:#171b22;--ink:#e8ebf0;--soft:#1e232c;
--muted:#9aa5b4;--line:#2a313b;--up:#3fcf86;--upbg:#12291e;--dn:#ff6b6b;--dnbg:#2e1616;--acc:#7c9cff;--accbg:#1a2340;
--warn:#f0c14b;--warnbg:#2d2510;--ce:#ff7a75;--pe:#3fcf86}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{padding:20px 16px 8px;max-width:1180px;margin:auto}h1{margin:0;font-size:22px}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.warn{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:13px;margin-top:10px}
nav{max-width:1180px;margin:12px auto 0;padding:0 16px;display:flex;gap:6px;flex-wrap:wrap}
nav button{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:8px 14px;border-radius:999px;cursor:pointer;font-size:14px}
nav button.on{background:var(--acc);border-color:var(--acc);color:#fff}
main{max-width:1180px;margin:auto;padding:12px 16px 48px}
section{display:none}section.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.v{font-size:21px;font-weight:650;margin-top:2px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.up{color:var(--up)}.dn{color:var(--dn)}
.pill.CE{background:var(--upbg);color:var(--up)}.pill.PE{background:var(--dnbg);color:var(--dn)}.pill.n{background:var(--accbg);color:var(--acc)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}
th,td{padding:8px 11px;border-bottom:1px solid var(--line);text-align:right}th{color:var(--muted);font-weight:600;font-size:12px;background:var(--card)}
td:first-child,th:first-child{text-align:left}tr:last-child td{border-bottom:0}
tr.click{cursor:pointer}tr.click:hover td{background:var(--soft)}tr.click td:first-child::before{content:"▸ ";color:var(--muted)}
tr.click.open td:first-child::before{content:"▾ "}
tr.det>td{white-space:normal;text-align:left;background:var(--soft);padding:16px}
.mini td,.mini th{background:none;border-bottom:1px solid var(--line)}.box table.mini{white-space:normal}tr.det{display:none}tr.det.open{display:table-row}
.muted{color:var(--muted)}h2{font-size:17px;margin:22px 0 8px}h3{font-size:14px;margin:0 0 6px}p.note{color:var(--muted);font-size:13px;margin:6px 0 12px}
.empty{padding:22px;text-align:center;color:var(--muted)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.box ul,.box ol{margin:4px 0 0;padding-left:18px}.box li{margin:3px 0}
.mini{width:100%;font-size:13px}.mini td,.mini th{padding:5px 8px}
.chain td{padding:5px 8px;font-size:13px}.chain tr.atm td{background:var(--accbg)}.chain td.st{text-align:center;font-weight:650;background:var(--soft)}
.bar{height:10px;border-radius:3px;display:inline-block;vertical-align:middle}
.oi{display:grid;grid-template-columns:1fr 70px 1fr;gap:3px 6px;align-items:center;font-size:12px}
.oi .l{display:flex;justify-content:flex-end}.oi .s{text-align:center;font-weight:600}.oi .s.atm{color:var(--acc)}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin:6px 0}
.guide{max-width:820px}.guide h2{margin-top:28px}.guide p,.guide li{line-height:1.6}
.guide table{white-space:normal}.guide td,.guide th{text-align:left;vertical-align:top}
.act{display:flex;gap:14px;align-items:flex-start;padding:14px 0;border-top:1px solid var(--line)}.act:first-of-type{border-top:0}
.act .amt{min-width:120px;text-align:right;font-size:20px;font-weight:700}.act .what{flex:1}.act .what b.big{font-size:16px}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:4px;background:var(--accbg);color:var(--acc);margin-bottom:4px}
.tag.best{background:var(--upbg);color:var(--up)}.tag.wait{background:var(--warnbg);color:var(--warn)}
.total{display:flex;justify-content:space-between;font-weight:700;font-size:17px;padding-top:12px;border-top:2px solid var(--line);margin-top:4px}
@media (max-width:640px){.act{flex-direction:column;gap:4px}.act .amt{text-align:left}}
.hero{display:flex;justify-content:space-between;gap:16px;align-items:center;background:linear-gradient(135deg,var(--accbg),var(--card));border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:4px 0 8px}
.hero-k{font-size:13px;color:var(--muted)}.hero-t{font-size:26px;font-weight:750;margin:2px 0}.hero-s{color:var(--muted)}
.hero-mode{text-align:center;font-weight:650;font-size:14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}.hero-mode span{font-weight:400;font-size:12px;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.idea,.hold{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.idea.big{border:2px solid var(--up);box-shadow:0 2px 12px rgba(0,0,0,.05);padding:20px}
.idea-top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.src{font-size:12px;font-weight:650;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.src.live{color:var(--up)}
.dir{font-size:13px;font-weight:700;padding:3px 10px;border-radius:999px}.dir.CE{background:var(--upbg);color:var(--up)}.dir.PE{background:var(--dnbg);color:var(--dn)}
.idea-title{font-size:19px;font-weight:700;margin:8px 0 2px}.idea.big .idea-title{font-size:23px}
.idea-contract{color:var(--muted)}.idea-contract b{color:var(--ink)}
.money{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;margin:12px 0}
.money>div{background:var(--soft);border-radius:10px;padding:8px 10px}.money .k{font-size:11px}.money .m{font-size:19px;font-weight:750}
.idea.big .money .m{font-size:24px}
.why{font-size:14px;margin:6px 0}.small-warn{font-size:13px;color:var(--warn);margin:4px 0}
details.steps{margin-top:10px}details.steps summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:14px}
details.steps ol{margin:8px 0;padding-left:20px}details.steps li{margin:5px 0;font-size:14px}
.tip{border-bottom:1px dotted var(--muted);cursor:help}
.prog{margin:12px 0 8px}.bar-bg{position:relative;height:8px;border-radius:4px;background:linear-gradient(90deg,var(--dnbg),var(--soft),var(--upbg))}
.bar-bg i{position:absolute;top:-5px;width:6px;height:18px;margin-left:-3px;background:var(--ink);border-radius:3px}
.bar-bg .z0{position:absolute;top:-2px;width:2px;height:12px;background:var(--muted)}
.prog-l{display:flex;justify-content:space-between;font-size:12px;margin-top:6px}
.gloss{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.gloss>div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13px}
@media (max-width:640px){.hero{flex-direction:column;align-items:flex-start}.hero-t{font-size:22px}}
.ticker{display:none;gap:18px;flex-wrap:wrap;align-items:center;margin-top:10px;font-size:14px}.ticker.on{display:flex}
.ticker .ti b{font-variant-numeric:tabular-nums}.ticker .dot{color:var(--up);font-weight:700;font-size:12px}.ticker .dot.off{color:var(--muted)}
.flash-up{animation:fu 1.2s}.flash-dn{animation:fd 1.2s}@keyframes fu{from{background:var(--upbg)}}@keyframes fd{from{background:var(--dnbg)}}
.livep{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}.livep b{color:var(--ink)}
.seg{display:inline-flex;background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:4px;gap:4px;margin:4px 0 12px}
.seg button{border:0;background:none;color:var(--ink);font-size:15px;font-weight:600;padding:9px 16px;border-radius:9px;cursor:pointer}
.seg button span{font-size:12px;background:var(--line);border-radius:999px;padding:1px 7px;margin-left:4px}
.seg button.on{background:var(--card);box-shadow:0 1px 4px rgba(0,0,0,.12)}.segp{display:none}.segp.on{display:block}
.chk{margin:8px 0;font-size:14px}.chk summary{cursor:pointer}.chk ul,.hl{margin:6px 0 0;padding-left:4px;list-style:none}.chk li,.hl li{margin:4px 0;font-size:13px}
.hb{display:inline-block;min-width:30px;text-align:center;font-size:12px;font-weight:700;border-radius:999px;padding:1px 7px}.hb.g{background:var(--upbg);color:var(--up)}.hb.m{background:var(--warnbg);color:var(--warn)}.hb.b{background:var(--dnbg);color:var(--dn)}
.hscore{display:flex;gap:12px;align-items:center;margin-bottom:6px}.ring{width:54px;height:54px;border-radius:50%;border:5px solid currentColor;display:grid;place-items:center;font-weight:800;font-size:18px;flex:none}
.pbars{display:flex;gap:10px;align-items:flex-end;height:66px;margin-top:4px}.pbars div{display:flex;flex-direction:column;align-items:center;gap:3px;font-size:11px;color:var(--muted)}.pbars i{width:26px;border-radius:4px 4px 0 0;display:block}
.tech{font-size:11px;color:var(--muted);background:var(--soft);border-radius:4px;padding:0 5px;margin-left:4px}.seg small{font-weight:400;color:var(--muted)}
.range{position:relative;height:6px;background:var(--line);border-radius:3px;margin:8px 0 4px}
.range i{position:absolute;top:-4px;width:3px;height:14px;background:var(--acc);border-radius:2px}
svg text{fill:var(--muted);font-size:11px}
</style></head><body>
<header><h1>📈 My Market Helper</h1>
<div class="sub" id="upd"></div>
<div id="ticker" class="ticker"></div>
<div class="warn">These are computer-generated ideas, not financial advice. Start in practice mode and check “My results” before using real money.</div>
</header>
<nav><button data-t="plan" class="on">🏠 Today</button><button data-t="live">📊 NIFTY</button><button data-t="scan">🔎 Stock movers</button><button data-t="picks">🌙 Tomorrow's ideas</button>
<button data-t="track">📈 My results</button><button data-t="lt">🌱 Long-term</button><button data-t="guide">📖 Learn</button></nav>
<main>
<section id="plan" class="on"></section><section id="live"></section><section id="scan"></section><section id="picks"></section>
<section id="track"></section><section id="lt"></section><section id="guide" class="guide"></section>
</main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const num=(n,d=2)=>Number(n).toLocaleString("en-IN",{maximumFractionDigits:d});
const inr=(n,d=2)=>n==null||n===""?"–":(n<0?"−":"")+"₹"+num(Math.abs(n),d);
const sgn=(n,d=2)=>n==null?"–":(n>0?"+":n<0?"−":"")+num(Math.abs(n),d);
const cls=n=>n>0?"up":n<0?"dn":"";
const big=n=>{n=Number(n);const a=Math.abs(n);return a>=1e7?num(n/1e7,1)+" Cr":a>=1e5?num(n/1e5,1)+" L":num(n,0)};
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{
 document.querySelectorAll("nav button,section").forEach(e=>e.classList.remove("on"));
 b.classList.add("on");$("#"+b.dataset.t).classList.add("on");try{localStorage.tab=b.dataset.t}catch(e){}});
try{const t=localStorage.tab;t&&document.querySelector(`nav button[data-t=${t}]`)?.click()}catch(e){}
$("#upd").textContent=`Last updated ${D.built} (India time)`;
function card(k,v,c="",sub=""){return `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div>${sub?`<div class="muted" style="font-size:12px">${sub}</div>`:""}</div>`}
function table(cols,rows,empty,detail){if(!rows.length)return `<div class="tw"><div class="empty">${empty}</div></div>`;
 return `<div class="tw"><table><tr>${cols.map(c=>`<th>${c[0]}</th>`).join("")}</tr>${rows.map((r,i)=>
 `<tr class="${detail?"click":""}" ${detail?`onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')"`:""}>${cols.map(c=>`<td>${c[1](r)}</td>`).join("")}</tr>`+
 (detail?`<tr class="det"><td colspan="${cols.length}">${detail(r)}</td></tr>`:"")).join("")}</table></div>`}
function line(points,h=140,opts={}){ // points [{x,y}]
 if(points.length<2)return `<div class="muted" style="font-size:12px">Not enough data yet.</div>`;
 const w=1000,ys=points.map(p=>p.y),base=opts.base??(opts.zero?0:null);
 const mn=Math.min(...ys,...(base!=null?[base]:[])),mx=Math.max(...ys,...(base!=null?[base]:[])),rg=mx-mn||1;
 const X=i=>i/(points.length-1)*w,Y=v=>h-8-(v-mn)/rg*(h-20);
 const path=points.map((p,i)=>`${i?"L":"M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
 const col=opts.color||((ys[ys.length-1]-(base??ys[0]))>=0?"var(--up)":"var(--dn)");
 return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
 ${base!=null?`<line x1="0" x2="${w}" y1="${Y(base)}" y2="${Y(base)}" stroke="var(--line)" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>`:""}
 <path d="${path}" fill="none" stroke="${col}" stroke-width="2.2" vector-effect="non-scaling-stroke"/></svg>
 <div class="muted" style="font-size:12px;display:flex;justify-content:space-between"><span>${points[0].x} · ${opts.fmt?opts.fmt(ys[0]):num(ys[0])}</span><span>${points[points.length-1].x} · ${opts.fmt?opts.fmt(ys[ys.length-1]):num(ys[ys.length-1])}</span></div>`}

// =============================== Today (beginner view)
const GLOSS={CE:"Call option: makes money if the price goes UP",PE:"Put option: makes money if the price goes DOWN",
 lot:"Options are sold in fixed bundles called lots. You must buy at least 1 lot.",premium:"The price of one option unit. You pay premium × lot size.",
 target:"The price where you sell to take your profit",stoploss:"The price where you sell to cap your loss. Always set it.",
 expiry:"The last date the option exists. After that it's worth only what it's 'in the money', often zero.",
 paper:"Practice mode: the app tracks pretend trades so you can see if the ideas work before using real money."};
const tip=(w,k)=>`<span class="tip" title="${GLOSS[k]}">${w}</span>`;
function chartHTML(ch,compact){if(!ch)return "";
 const v={strong:["✅","The price chart supports this"],ok:["👍","The price chart mostly supports this"],weak:["⚠️","The price chart is mixed, be careful"],against:["⛔","The price chart disagrees"]}[ch.verdict];
 return `<details class="chk"><summary>📊 ${v[0]} ${v[1]} <span class="muted">(${ch.passed} of 5 signs good, tap to see)</span></summary><ul>${ch.checks.map(c=>`<li>${c.ok?"✅":"❌"} <b>${c.name}:</b> ${c.text}${c.tech?` <span class="tech">${c.tech}</span>`:""}</li>`).join("")}</ul></details>`}
function healthHTML(f){if(!f)return `<div class="muted" style="font-size:13px">Company data not available.</div>`;
 const col=f.health>=70?"up":f.health>=50?"":"dn";
 const ph=(f.profit_history||[]).slice().reverse(),mx=Math.max(...ph.map(x=>Math.abs(x[1])),1);
 return `<div class="hscore"><div class="ring ${col}">${f.health}</div><div><b>${f.grade==="Strong"?"Strong, healthy company":f.grade==="Average"?"Average company":"Weak company"}</b><div class="muted" style="font-size:12px">Score out of 100, based on: profit, growth, borrowing, price and margins</div></div></div>
 <ul class="hl">${f.good.map(g=>`<li>✅ ${g}</li>`).join("")}${f.bad.map(g=>`<li>⚠️ ${g}</li>`).join("")}${f.info.map(g=>`<li>ℹ️ ${g}</li>`).join("")}</ul>
 ${ph.length>1?`<div class="k" style="margin-top:8px">Profit each year (taller = more)</div><div class="pbars">${ph.map(x=>`<div><i style="height:${Math.max(4,Math.abs(x[1])/mx*48)}px;background:${x[1]<0?"var(--dn)":"var(--acc)"}"></i><span>${x[0].slice(0,4)}</span></div>`).join("")}</div>`:""}`}
function stepsHTML(x){return `<details class="steps"><summary>Show me how to buy this in Groww</summary><ol>
 <li>Open <b>Groww</b> and search <b>${x.sym}</b>. Open its <b>F&amp;O</b> section, then <b>Option chain</b>.</li>
 <li>Choose expiry <b>${x.expiry}</b>. Find the <b>${x.strike}</b> row and tap <b>${x.side}</b>, then <b>Buy</b>.</li>
 <li>Quantity: <b>${x.qty}</b> (that's 1 lot). Order type: <b>Limit</b>, price ${x.maxText}. Product: <b>Intraday</b>.</li>
 <li>As soon as it's bought, place two sell orders: a <b>Stop-loss</b> at about <b>${inr(x.stop)}</b> and a <b>Limit sell</b> at about <b>${inr(x.target)}</b>. When one happens, cancel the other.</li>
 <li>If neither happens, <b>sell before 3:15 PM</b>. Never hold overnight.</li></ol>
 <div class="muted" style="font-size:12px">Button names in the app may differ slightly. In practice (paper) mode, just note what you would have done.</div></details>`}
function ideaCard(x,big){
 return `<div class="idea ${big?"big":""}">
 <div class="idea-top"><span class="src ${x.live?"live":""}">${x.live?"● Live now":"From last night's scan"}</span><span class="dir ${x.side}">${x.side==="CE"?"▲ Bet it goes UP":"▼ Bet it goes DOWN"}</span></div>
 <div class="idea-title">${x.title}</div>
 <div class="idea-contract">Buy: <b>${x.contract}</b> ${tip(x.side,x.side)}</div>
 <div class="livep" data-stock="${x.sym}"></div>
 <div class="money"><div><div class="k">You pay</div><div class="m">${inr(x.pay,0)}</div></div>
  <div><div class="k">If it works</div><div class="m up">+${inr(x.win,0)}</div></div>
  <div><div class="k">If it doesn't</div><div class="m dn">${inr(x.lose,0)}</div></div></div>
 <div class="why">💡 ${x.why}</div>
 ${chartHTML(x.chart)}
 ${x.warn?`<div class="small-warn">⚠️ ${x.warn}</div>`:""}
 ${stepsHTML(x)}</div>`}
(()=>{const now=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
 const hm=now.toTimeString().slice(0,5),wd=now.getDay(),open=wd>0&&wd<6&&hm>="09:15"&&hm<="15:30";
 const today=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
 const fmt=s=>new Date(s+"T12:00:00").toLocaleDateString("en-IN",{weekday:"short",day:"numeric",month:"short"});
 const d=D.daily||{},st=D.state||{},l=st.last_scan,sl=D.stocks||{},snaps=D.snapshots||[];
 const liveToday=sl.time&&sl.time.startsWith(today), lToday=l&&l.time.startsWith(today);
 let h="";

 // ---- 1. market mood banner
 const nifty=lToday?l.spot:null,prevC=snaps.length?+snaps[snaps.length-1].prev_close:null,nchg=nifty&&prevC?(nifty/prevC-1)*100:null;
 const adv=liveToday?sl.rows.filter(r=>r.chg>0).length:null,dec=liveToday?sl.rows.length-adv:null;
 const mood=nchg==null?"":nchg>0.3?"🟢 Market is UP today":nchg<-0.3?"🔴 Market is DOWN today":"🟡 Market is FLAT today";
 h+=`<div class="hero"><div><div class="hero-k">${open?"Market open · closes 3:30 PM":"Market closed · opens 9:15 AM Mon–Fri"}</div>
 <div class="hero-t">${mood||"Welcome 👋"}</div>
 <div class="hero-s">${nifty?`NIFTY 50 at <b data-idx="NIFTY 50">${num(nifty,0)}</b> (<span data-idxp="NIFTY 50">${sgn(nchg,2)}%</span>)`:""}${adv!=null?` · ${adv} of ${adv+dec} big stocks rising`:""}</div></div>
</div>`;

 // ---- NIFTY card: engine position / pending order / opening-range status
 const en=D.engine||{},ep=en.day===today?en.position:null,eo=en.day===today?en.pending:null,es=en.day===today?(en.status||{}):{};
 const legacy=st.open_trade&&lToday?st.open_trade:null,w=(l&&l.watch)||{};
 if(ep||eo||legacy||es.status||l){
  h+=`<h2>📊 NIFTY 50 (the whole market)</h2>`;
  const active=ep?{side:ep.side,strike:ep.strike,expiry:ep.expiry,entry:ep.entry,now:ep.last_bid,target:ep.target,stop:ep.stop,since:ep.fill_time.slice(11,16),lots:ep.lots,
     why:`NIFTY closed ${ep.side==="CE"?"above":"below"} its opening range (${num(ep.or_low,0)}–${num(ep.or_high,0)}) at ${ep.signal_time.slice(11,16)}, so we bought at the asking price. Checked every 30 seconds against the real selling price.`}
   :legacy?{side:legacy.side,strike:legacy.strike,expiry:legacy.expiry,entry:legacy.entry,now:legacy.last_price,target:legacy.target,stop:legacy.stop,since:legacy.time.slice(11,16),lots:legacy.lots,
     why:"Opened by the earlier 3-check rule. It's tracked to its target, stop or 3:15 PM; new NIFTY trades now use the opening-range rule. Checked every 15 minutes (with a 5-minute high/low check in between)."}:null;
  if(active){const t=active,pnl=(t.now-t.entry)*t.lots*D.lot,up=t.side==="CE";
   h+=`<div class="idea big"><div class="idea-top"><span class="src live">● Active NIFTY call since ${t.since}</span><span class="dir ${t.side}">${up?"▲ Bet the market goes UP":"▼ Bet the market goes DOWN"}</span></div>
   <div class="idea-title">BUY NIFTY ${t.expiry} ${t.strike} ${t.side}</div>
   <div class="idea-contract">Bought at <b>${inr(t.entry)}</b> · now <b><span data-opt="${t.strike}${t.side}" class="livep">${inr(t.now)}</span></b> (selling price) · ${t.lots} lot = ${t.lots*D.lot} units</div>
   <div class="money"><div><div class="k">You paid</div><div class="m">${inr(t.entry*t.lots*D.lot,0)}</div></div>
    <div><div class="k">Sell for profit at</div><div class="m up">${inr(t.target)}</div></div>
    <div><div class="k">Sell to stop loss at</div><div class="m dn">${inr(t.stop)}</div></div>
    <div><div class="k">So far</div><div class="m ${cls(pnl)}">${pnl>=0?"+":"−"}${inr(Math.abs(pnl),0)}</div></div></div>
   <div class="why">💡 ${t.why} You'll get a message when it hits the profit or stop price. Sold by 3:15 PM either way.</div></div>`}
  else if(eo){
   h+=`<div class="card"><div style="font-size:17px;font-weight:650">🕐 Buying NIFTY ${eo.strike} ${eo.side}: waiting for the price</div>
   <p style="margin:6px 0">NIFTY broke ${eo.side==="CE"?"above":"below"} its opening range at ${eo.signal_time.slice(11,16)}. We'll buy at <b>${inr(eo.limit)}</b> or less. If the price runs away in the next 2 minutes, we skip it (that counts as "not filled").</p></div>`}
  else{
   const rng=es.or_low?`${num(es.or_low,0)} – ${num(es.or_high,0)}`:null;
   h+=`<div class="card"><div style="font-size:17px;font-weight:650">⏳ No NIFTY call right now</div>
   <p style="margin:6px 0 4px">${rng?`Our NIFTY rule is simple: in the first 15 minutes NIFTY moved between <b>${rng}</b>. If it then closes a 5-minute period <b>above</b> that range, we buy a CE (bet on up); <b>below</b> it, a PE (bet on down).`:"Our NIFTY rule waits for the first 15 minutes of trading (9:15–9:30) to set today's range."}
   ${es.status?`<br><span class="muted">${es.status}${es.bar?` (as of ${es.bar})`:""}</span>`:""}</p>
   ${Object.keys(w).length?`<div class="cards" style="margin-top:10px">${["CE","PE"].filter(s=>w[s]).map(s=>`<div class="hold"><span class="dir ${s}">${s==="CE"?"▲ If NIFTY breaks above"+(es.or_high?" "+num(es.or_high,0):""):"▼ If NIFTY breaks below"+(es.or_low?" "+num(es.or_low,0):"")}</span>
    <div class="idea-contract" style="margin-top:6px">We'd buy about: <b>NIFTY ${l.expiry} ${w[s].strike} ${s}</b> ${tip(s,s)}</div>
    <div class="livep" data-opt="${w[s].strike}${s}">Price now ${inr(w[s].ask)}</div>
    <div class="money"><div><div class="k">You pay</div><div class="m">${inr(w[s].cost_lot,0)}</div></div><div><div class="k">If it works</div><div class="m up">+${inr(w[s].profit_lot,0)}</div></div><div><div class="k">If it doesn't</div><div class="m dn">${inr(w[s].loss_lot,0)}</div></div></div>
    <div class="small-warn">Not yet: wait for our message before buying.</div></div>`).join("")}</div>`:""}</div>`}}

 // ---- 3. ideas: F&O and normal trades
 const fno=[];
 if(liveToday)(sl.signals||[]).filter(r=>r.option&&r.affordable).forEach(r=>{const o=r.option;
  fno.push({live:true,side:r.signal,sym:r.symbol,sector:r.sector,contract:r.contract,expiry:r.contract.split(" ").slice(1,3).join(" "),strike:o.strike,qty:o.lot,
   pay:o.cost_lot,win:o.profit_lot,lose:o.loss_lot,target:o.target,stop:o.stop,maxText:`about <b>${inr(o.est)}</b> (estimate: use the live price shown, skip if it's more than 5% higher)`,
   title:`${r.symbol} is ${r.signal==="CE"?"rising":"falling"} strongly`,
   why:`${r.name||r.symbol} (${r.sector}) is ${r.chg>0?"up":"down"} ${Math.abs(r.chg)}% today, trading at ${r.rvol}× its usual volume, and it kept ${r.signal==="CE"?"rising":"falling"} in the last 30 minutes${r.agree?". Last night's scan expected this too":""}.`,
   warn:"The option price is an estimate. Check the real price in Groww first.",chart:r.chart,score:r.score+(r.agree?2:0)})});
 const valid=d.date&&(new Date(today)-new Date(d.date))/864e5<=4;
 if(valid)(d.options||[]).filter(p=>p.affordable).forEach(p=>{
  fno.push({live:false,side:p.side,sym:p.symbol,contract:p.contract,expiry:p.contract.split(" ").slice(1,3).join(" "),strike:p.strike,qty:p.lot,
   pay:p.cost_per_lot,win:p.profit_per_lot,lose:p.loss_per_lot,target:p.target,stop:p.stop,
   maxText:`between <b>${inr(p.entry*(1-D.gap/100))}</b> and <b>${inr(p.entry*(1+D.gap/100))}</b>. If it's outside this range, skip it`,
   title:`${p.symbol} looked strong at yesterday's close`,
   why:`On ${fmt(d.date)}, ${p.symbol} ${p.price_chg>0?"rose":"fell"} ${Math.abs(p.price_chg)}% and many new traders joined the move (open interest +${p.oi_chg}%). It's also ${p.side==="CE"?"above":"below"} its 20-day average.`,
   warn:open&&hm>"09:30"?"The market has been open a while, so this may have already moved. Only buy inside the price range.":"",chart:p.chart,score:-1+(p.chart?p.chart.passed-3:0)})});
 fno.sort((a,b)=>b.score-a.score);
 const cash=liveToday?(sl.signals||[]).filter(r=>r.cash):[];

 // sector note when one sector dominates
 const hot=Object.entries(sl.hot_sectors||{}).sort((a,b)=>b[1]-a[1]);
 const sectorNote=liveToday&&hot.length&&hot[0][1]>=3?`<p class="note">🔥 <b>${hot[0][0]}</b> stocks are leading today (${hot[0][1]} of ${sl.all_signals} signals). To avoid putting everything on one sector, we show at most 2 ideas per sector.</p>`:"";

 h+=`<h2>🎯 Trade ideas ${open?"right now":"for the next session"}</h2>${sectorNote}
 <div class="seg"><button class="on" data-seg="fno">⚡ Options <small>(F&amp;O)</small> <span>${fno.length}</span></button><button data-seg="cash">🛒 Shares <small>(normal)</small> <span>${cash.length}</span></button></div>`;

 // F&O panel
 h+=`<div class="segp on" id="seg-fno"><p class="note"><b>Options in simple words:</b> you pay a small amount to bet on whether a share price goes up or down <b>today</b>. If you're right you can earn a lot quickly, but if you're wrong you lose quickly too, and the bet loses a little value every day. Pick <b>only one</b>, and never more than ${inr(D.capital,0)}.</p>`;
 if(fno.length){h+=ideaCard(fno[0],true);if(fno.length>1)h+=`<h3 style="margin:18px 0 8px">Other F&amp;O ideas</h3><div class="cards">${fno.slice(1,5).map(x=>ideaCard(x,false)).join("")}</div>`}
 else h+=`<div class="card empty">😴 No good F&amp;O setups right now. That's normal: no trade is better than a bad trade.</div>`;
 h+=`</div>`;

 // Normal (shares) panel
 h+=`<div class="segp" id="seg-cash"><p class="note"><b>Shares in simple words:</b> you buy a small piece of the company, then sell it later <b>the same day</b>. Safer and slower than options. You sell when the price is up ${D.st.cash_target_pct}% (profit), or down ${D.st.cash_stop_pct}% (to stop a bigger loss).</p>`;
 if(cash.length){h+=`<div class="cards">${cash.map((r,i)=>{const c=r.cash,up=r.signal==="CE";
  return `<div class="idea ${i?"":"big"}"><div class="idea-top"><span class="src live">● Live now · ${r.sector}</span><span class="dir ${r.signal}">${up?"▲ Buy shares":"▼ Short-sell (advanced)"}</span></div>
  <div class="idea-title">${up?"Buy":"Short-sell"} ${c.qty} shares of ${r.symbol}</div>
  <div class="idea-contract">${r.name||r.symbol} at about <b>${inr(c.entry)}</b></div><div class="livep" data-stock="${r.symbol}"></div>
  <div class="money"><div><div class="k">You ${up?"invest":"trade"}</div><div class="m">${inr(c.invest,0)}</div></div>
   <div><div class="k">If it works</div><div class="m up">+${inr(c.profit,0)}</div></div>
   <div><div class="k">If it doesn't</div><div class="m dn">${inr(c.loss,0)}</div></div></div>
  <div class="why">💡 ${r.symbol} is ${r.chg>0?"up":"down"} ${Math.abs(r.chg)}% today on ${r.rvol}× its usual volume and still ${up?"rising":"falling"}.</div>
  ${chartHTML(r.chart)}
  ${up?"":`<div class="small-warn">⚠️ Short-selling means you sell first and buy back later the same day. If you're new, skip down-trades and only take ▲ ideas.</div>`}
  <details class="steps"><summary>Show me how to do this in Groww</summary><ol>
   <li>Search <b>${r.symbol}</b> and tap <b>${up?"Buy":"Sell"}</b>. Choose <b>Intraday</b>.</li>
   <li>Quantity <b>${c.qty}</b>, order type <b>Limit</b> at about <b>${inr(c.entry)}</b>. Skip if the price has moved more than 0.5% away.</li>
   <li>After it fills, place a <b>Stop-loss</b> order at <b>${inr(c.stop)}</b> and a <b>Limit ${up?"sell":"buy"}</b> at <b>${inr(c.target)}</b>. Cancel the other when one fills.</li>
   <li>If neither happens, Groww auto-closes intraday positions near 3:20 PM, but close it yourself by 3:15.</li></ol></details></div>`}).join("")}</div>`}
 else h+=`<div class="card empty">😴 No strong share moves right now. Ideas appear here when a stock passes all 5 checks.</div>`;
 h+=`</div>`;

 // ---- long term
 const alloc=(d.long_term||[]).filter(r=>r.alloc_shares>0),ltTot=alloc.reduce((a,r)=>a+r.alloc_amount,0),b=d.benchmark||{};
 if(alloc.length){h+=`<h2>🌱 Long-term savings (${inr(d.lt_budget,0)}, keep 3+ years)</h2><p class="note">This is separate from trading: money you invest and leave alone. Choose one way:</p><div class="cards">
  <div class="hold"><div class="src">Easiest · recommended for beginners</div><div class="idea-title">NIFTY 50 index fund</div>
   <p style="margin:6px 0">Buys the top 50 companies at once. No picking needed. On Groww, search “Nifty 50 index fund”, pick one with a low expense ratio, and invest the full amount or a monthly SIP.</p>
   <div class="money"><div><div class="k">Invest</div><div class="m">${inr(d.lt_budget,0)}</div></div><div><div class="k">Last 5 years</div><div class="m ${cls(b.cagr5)}">${sgn(b.cagr5,1)}%/yr</div></div></div></div>
  <div class="hold"><div class="src">Pick stocks · more effort</div><div class="idea-title">${alloc.length} strong stocks</div>
   <table class="mini">${alloc.map(r=>`<tr><td><b>${r.symbol}</b> ${r.health!=null?`<span class="hb ${r.health>=70?"g":r.health>=50?"m":"b"}">${r.health}</span>`:""}<br><span class="muted" style="font-size:12px">${r.extended?"⏳ wait for a small dip":"✅ fair price now"}</span></td><td>${r.alloc_shares} shares</td><td><b>${inr(r.alloc_amount,0)}</b></td></tr>`).join("")}</table>
   <div class="muted" style="font-size:13px;margin-top:6px">Green number = company health score (out of 100). Total ${inr(ltTot,0)}. Buy with “Delivery”, in 2–3 parts over a few weeks. See the Long-term tab for details.</div></div></div>`}

 // ---- glossary
 h+=`<h2>📖 Words you'll see</h2><div class="gloss">${[["CE (Call)",GLOSS.CE],["PE (Put)",GLOSS.PE],["Lot",GLOSS.lot],["Premium",GLOSS.premium],["Target",GLOSS.target],["Stop-loss",GLOSS.stoploss],["Expiry",GLOSS.expiry],["Practice mode",GLOSS.paper]].map(g=>`<div><b>${g[0]}</b><br>${g[1]}</div>`).join("")}</div>
 <p class="note" style="margin-top:14px">⚠️ Options are risky: you can lose the whole amount you pay. Only trade money you can afford to lose, and use the Learn tab before going live.</p>`;
 $("#plan").innerHTML=h;
 const segs=document.querySelectorAll(".seg button");
 const pick=k=>{segs.forEach(b=>b.classList.toggle("on",b.dataset.seg===k));document.querySelectorAll(".segp").forEach(p=>p.classList.toggle("on",p.id==="seg-"+k));try{localStorage.seg=k}catch(e){}};
 segs.forEach(b=>b.onclick=()=>pick(b.dataset.seg));try{localStorage.seg&&pick(localStorage.seg)}catch(e){}})();

// =============================== NIFTY live
(()=>{const s=D.state||{},l=s.last_scan,t=s.open_trade,ch=D.chain;let h="";
 if(!l){$("#live").innerHTML=`<div class="card empty">No intraday scan yet. It runs every 15 min, 9:15–15:30 IST, Mon–Fri.</div>`;return}
 const bc=l.bias==="Bullish"?"up":l.bias==="Bearish"?"dn":"";
 h+=`<div class="grid">${card("NIFTY",num(l.spot))}${card("Bias",`${l.bias} (${sgn(l.score,0)})`,bc,"score −3 … +3, trade at ±2")}
 ${card("Support / Resistance",`${l.support??"–"} / ${l.resistance??"–"}`,"","biggest put OI below / call OI above")}
 ${card("PCR",l.pcr,"",l.pcr>1.2?"puts dominate: bullish lean":l.pcr<0.8?"calls dominate: bearish lean / capped":"neutral zone")}
 ${card("ATM IV",l.atm_iv+"%","","option price level; high = expensive")}</div>`;
 h=`<p class="note">🔧 <b>Advanced page</b> with the full details for experienced traders. If you're new, the 🏠 Today page has everything you need.</p>`+h;
 h+=`<div class="card" style="margin-bottom:14px"><b>Last scan ${l.time.slice(11,16)} · expiry ${l.expiry}:</b> ${l.note==="signal"?"signal fired":l.note}
 <div class="muted" style="margin-top:4px">${l.reasons.map(r=>"• "+r).join("<br>")}</div></div>`;
 if(t){const pnl=(t.last_price-t.entry)/t.entry*100;
  h+=`<h2>Open paper trade</h2><div class="grid">${card("Contract",`NIFTY ${t.strike} <span class="pill ${t.side}">${t.side}</span>`,"",t.expiry)}
  ${card("Entry → now",`${inr(t.entry)} → ${inr(t.last_price)}`)}${card("P&L",sgn(pnl,1)+"%",cls(pnl),inr((t.last_price-t.entry)*t.lots*D.lot,0)+" on "+t.lots+" lot")}
  ${card("Target / Stop",`${inr(t.target)} / ${inr(t.stop)}`)}${card("Δ · θ/lot/day",`${t.delta} · ${inr(t.theta_lot,0)}`)}</div>`}
 if(ch&&ch.rows){
  const maxOI=Math.max(...ch.rows.flatMap(r=>[r.CE?.oi||0,r.PE?.oi||0]),1);
  h+=`<h2>Open interest by strike <span class="muted" style="font-weight:400;font-size:13px">(${ch.expiry}, ${ch.time.slice(11,16)})</span></h2>
  <div class="card"><div class="legend"><span><span class="bar" style="width:14px;background:var(--ce)"></span> Call OI = sellers capping the upside (resistance)</span>
  <span><span class="bar" style="width:14px;background:var(--pe)"></span> Put OI = sellers defending the downside (support)</span><span>lighter part = added today</span></div><div class="oi">`;
  ch.rows.slice().reverse().forEach(r=>{const c=r.CE||{},p=r.PE||{},atm=r.strike===ch.atm;
   const seg=(o,col,dir)=>{const tot=(o.oi||0)/maxOI*100,add=Math.max(o.oi_chg||0,0)/maxOI*100;
    return `<span class="bar" style="width:${Math.max(tot-add,0)}%;background:${col}"></span><span class="bar" style="width:${add}%;background:${col};opacity:.45"></span>`};
   h+=`<div class="l" title="Call OI ${num(c.oi||0,0)} (${sgn(c.oi_chg||0,0)} today)">${seg(c,"var(--ce)")}</div>
   <div class="s ${atm?"atm":""}">${r.strike}${r.strike===ch.resistance?" R":""}${r.strike===ch.support?" S":""}</div>
   <div title="Put OI ${num(p.oi||0,0)} (${sgn(p.oi_chg||0,0)} today)">${seg(p,"var(--pe)")}</div>`});
  h+=`</div><p class="note" style="margin-bottom:0">Blue strike = at-the-money. NIFTY tends to stall near the strike with the biggest call wall above and bounce near the biggest put wall below.</p></div>`;
  h+=`<h2>Option chain with Greeks <span class="muted" style="font-weight:400;font-size:13px">(per lot of ${ch.lot})</span></h2>
  <p class="note">CALLS on the left, PUTS on the right. Δ = change per ₹1 NIFTY move · θ/lot = rupees lost per day per lot · Vega/lot = rupees per 1% IV change.</p>
  <div class="tw"><table class="chain"><tr><th>OI</th><th>OI chg</th><th>IV</th><th>Vega/lot</th><th>θ/lot</th><th>Δ</th><th>LTP</th><th style="text-align:center">Strike</th>
  <th>LTP</th><th>Δ</th><th>θ/lot</th><th>Vega/lot</th><th>IV</th><th>OI chg</th><th style="text-align:right">OI</th></tr>`;
  ch.rows.forEach(r=>{const c=r.CE||{},p=r.PE||{};h+=`<tr class="${r.strike===ch.atm?"atm":""}">
   <td>${big(c.oi||0)}</td><td class="${cls(c.oi_chg)}">${sgn(c.oi_chg||0,0)}</td><td>${c.iv??"–"}</td><td>${inr(c.vega_lot,0)}</td><td class="dn">${inr(c.theta_lot,0)}</td><td>${c.delta??"–"}</td><td><b>${inr(c.ltp)}</b></td>
   <td class="st">${r.strike}</td>
   <td><b>${inr(p.ltp)}</b></td><td>${p.delta??"–"}</td><td class="dn">${inr(p.theta_lot,0)}</td><td>${inr(p.vega_lot,0)}</td><td>${p.iv??"–"}</td><td class="${cls(p.oi_chg)}">${sgn(p.oi_chg||0,0)}</td><td>${big(p.oi||0)}</td></tr>`});
  h+=`</table></div>`}
 const sn=D.snapshots;
 if(sn.length>1){h+=`<h2>Today so far</h2><div class="cols">
  <div class="box"><h3>NIFTY</h3>${line(sn.map(r=>({x:r.time.slice(11,16),y:+r.spot})),110,{base:+sn[0].day_open})}</div>
  <div class="box"><h3>Put/Call ratio</h3>${line(sn.map(r=>({x:r.time.slice(11,16),y:+r.pcr})),110,{color:"var(--acc)",fmt:v=>v.toFixed(2)})}</div>
  <div class="box"><h3>ATM implied volatility</h3>${line(sn.map(r=>({x:r.time.slice(11,16),y:+r.atm_iv})),110,{color:"var(--warn)",fmt:v=>v.toFixed(1)+"%"})}</div></div>`}
 h+=`<h2>Today's scans</h2>`+table([["Time",r=>r.time.slice(11,16)],["NIFTY",r=>num(+r.spot,0)],["Score",r=>`<span class="${cls(+r.score)}">${sgn(+r.score,0)}</span>`],
  ["PCR",r=>r.pcr],["ATM IV",r=>r.atm_iv],["S / R",r=>`${r.support} / ${r.resistance}`],["Result",r=>r.note||""]],sn.slice().reverse(),"No scans today");
 $("#live").innerHTML=h})();

// =============================== Live stock scanner
(()=>{const s=D.stocks;if(!s||!s.rows){$("#scan").innerHTML=`<div class="card empty">The live stock scan runs every 15 min during market hours.</div>`;return}
 const ok=b=>b?`<span class="up">✓</span>`:`<span class="muted">·</span>`;
 const gain=s.rows.filter(r=>r.chg>0).length,lose=s.rows.length-gain;
 let h=`<p class="note">🔧 <b>Advanced page:</b> every big stock we check, and why it did or didn't become an idea. If you're new, use the 🏠 Today page.</p><p class="note">Scanned the <b>${s.scanned}</b> most-traded F&amp;O stocks at <b>${s.time.slice(11,16)}</b> (prices up to the ${s.bar_time} 5-min bar, from Yahoo Finance).
 A <b>signal</b> needs all 5 checks: moved ≥${D.st.chg_min}% on the day · on the right side of VWAP · ≥${D.st.mom_min}% more in the last 30 min · volume ≥${D.st.rvol_min}× normal for this time · broke the first-15-min range. Option premiums are <b>estimates</b> (yesterday's IV at today's price): check Groww before buying. ${s.entry_open?"":"<b>New entries only between "+D.st.entry_start+" and "+D.st.entry_end+".</b>"}</p>
 <div class="grid">${card("Signals now",s.signals.length,s.signals.length?"up":"")}${card("Advancing / declining",`${gain} / ${lose}`,gain>lose?"up":"dn")}
 ${card("Top gainer",s.rows.slice().sort((a,b)=>b.chg-a.chg)[0].symbol,"up",sgn(s.rows.slice().sort((a,b)=>b.chg-a.chg)[0].chg)+"%")}
 ${card("Top loser",s.rows.slice().sort((a,b)=>a.chg-b.chg)[0].symbol,"dn",sgn(s.rows.slice().sort((a,b)=>a.chg-b.chg)[0].chg)+"%")}</div>`;
 if(s.signals.length){h+=`<h2>Signals</h2>`+table([["Option",r=>`<b>${r.contract}</b> <span class="pill ${r.signal}">${r.signal}</span>`],["Stock",r=>`${r.symbol} ${inr(r.price)}`],
  ["Day",r=>`<span class="${cls(r.chg)}">${sgn(r.chg)}%</span>`],["Vol",r=>r.rvol+"×"],["Prem. est.",r=>inr(r.option.est)],["Lot",r=>r.option.lot],
  ["Cost/lot",r=>`<span class="${r.affordable?"":"muted"}">${inr(r.option.cost_lot,0)}</span>`],["Δ",r=>r.option.delta],["θ/lot",r=>`<span class="dn">${inr(r.option.theta_lot,0)}</span>`],
  ["Also last night",r=>r.agree?`<span class="up">yes</span>`:"–"]],s.signals,"")}
 h+=`<h2>All scanned stocks (biggest movers first)</h2>`+table([["Stock",r=>`<b>${r.symbol}</b>${r.signal?` <span class="pill ${r.signal}">${r.signal}</span>`:""}`],["Sector",r=>`<span class="muted">${r.sector||""}</span>`],["Price",r=>inr(r.price)],
  ["Day",r=>`<span class="${cls(r.chg)}">${sgn(r.chg)}%</span>`],["vs VWAP",r=>`<span class="${cls(r.vs_vwap)}">${sgn(r.vs_vwap)}%</span>`],["30 min",r=>`<span class="${cls(r.mom30)}">${sgn(r.mom30)}%</span>`],
  ["Volume",r=>r.rvol!=null?r.rvol+"×":"–"],["Day range",r=>`${inr(r.day_low,1)} – ${inr(r.day_high,1)}`],
  ["Move",r=>ok(r.checks.move)],["VWAP",r=>ok(r.checks.vwap)],["Mom.",r=>ok(r.checks.momentum)],["Vol.",r=>ok(r.checks.volume)],["Range",r=>ok(r.checks.range)]],s.rows,"");
 $("#scan").innerHTML=h})();

// =============================== Next-day options
function pickDetail(r){const ce=r.side==="CE",lot=r.lot;
 return `<div class="cols">
 <div class="box"><h3>Why this was picked</h3><ul>${(r.why||[]).map(w=>`<li>${w}</li>`).join("")}</ul></div>
 <div class="box"><h3>Key numbers (1 lot = ${lot} qty)</h3><table class="mini">
  <tr><td>Cost of 1 lot</td><td>${inr(r.cost_per_lot,0)}</td></tr>
  <tr><td>Profit if +${D.target}% target hits</td><td class="up">+${inr(r.profit_per_lot,0)}</td></tr>
  <tr><td>Loss if −${D.stop}% stop hits</td><td class="dn">${inr(r.loss_per_lot,0)}</td></tr>
  <tr><td>Worst case (no stop, expires worthless)</td><td class="dn">${inr(-r.max_loss_lot,0)}</td></tr>
  <tr><td>${r.symbol} move needed for target</td><td>~${inr(r.need_move)} (${r.need_move_pct}%) ${ce?"up":"down"}</td></tr>
  <tr><td>Break-even at expiry</td><td>${r.symbol} ${ce?"above":"below"} ${inr(r.breakeven)}</td></tr>
  <tr><td>Days to expiry</td><td>${r.days}</td></tr></table></div>
 <div class="box"><h3>Greeks in plain words</h3><ul>
  <li><b>Delta ${r.delta}</b>: if ${r.symbol} moves ₹10 ${ce?"up":"down"}, this option gains about ${inr(Math.abs(r.delta)*10)} (${inr(Math.abs(r.delta)*10*lot,0)} per lot).</li>
  <li><b>Theta ${inr(r.theta_lot,0)}/lot/day</b>: the option loses this much each day if ${r.symbol} doesn't move. That's why these are 1-day trades.</li>
  <li><b>IV ${r.iv}%</b>: how expensive the option is. If IV falls 1 point, you lose about ${inr(r.vega_lot,0)} per lot even with no price move (vega).</li>
  <li><b>Gamma ${r.gamma}</b>: delta changes by this per ₹1 move, so profits speed up if the move continues.</li></ul></div>
 <div class="box"><h3>What-if tomorrow (IV unchanged)</h3><table class="mini"><tr><th>${r.symbol} move</th><th>Option ≈</th><th>%</th><th>P&L / lot</th></tr>
  ${(r.scenarios||[]).map(s=>`<tr><td>${sgn(s.move,0)}% (${inr(r.spot*(1+s.move/100),0)})</td><td>${inr(s.price)}</td><td class="${cls(s.pct)}">${sgn(s.pct,1)}%</td><td class="${cls(s.pnl_lot)}">${sgn(s.pnl_lot,0)}</td></tr>`).join("")}</table>
  <div class="muted" style="font-size:12px;margin-top:6px">Includes 1 day of time decay and estimated charges.</div></div>
 <div class="box"><h3>How to place it in Groww</h3><ol>
  <li>At 9:15–9:20 AM, search <b>${r.symbol}</b> → F&amp;O → Option chain → expiry <b>${r.contract.split(" ").slice(1,3).join(" ")}</b>.</li>
  <li>Tap the <b>${r.strike} ${r.side}</b> row → <b>Buy</b>. Check the price is within ${D.gap}% of ${inr(r.entry)} (between ${inr(r.entry*(1-D.gap/100))} and ${inr(r.entry*(1+D.gap/100))}). If not, skip it.</li>
  <li>Quantity <b>${lot}</b> (1 lot). Order type <b>Limit</b> at the current ask. Product <b>Intraday</b> so it auto-closes if you forget.</li>
  <li>Right after it fills, place a <b>Stop-loss sell</b> at fill price −${D.stop}% and a <b>Limit sell</b> at fill +${D.target}%. When one executes, cancel the other.</li>
  <li>If neither hits, sell before 3:15 PM. Don't carry it overnight.</li></ol>
  <div class="muted" style="font-size:12px">Menu names in the app may differ slightly.</div></div>
 <div class="box"><h3>📊 Chart check</h3>${r.chart?`<ul class="hl">${r.chart.checks.map(c=>`<li>${c.ok?"✅":"❌"} <b>${c.name}:</b> ${c.text}${c.tech?` <span class="tech">${c.tech}</span>`:""}</li>`).join("")}</ul>`:"–"}</div>
 <div class="box"><h3>Data behind it</h3><table class="mini">
  <tr><td>${r.symbol} close</td><td>${inr(r.spot)} (${sgn(r.price_chg)}%)</td></tr>
  <tr><td>Futures OI</td><td>${big(r.fut_oi)} (${sgn(r.oi_chg,1)}%)</td></tr>
  <tr><td>Option close</td><td>${inr(r.entry)}${r.opt_chg!=null?` (${sgn(r.opt_chg,1)}% on day)`:""}</td></tr>
  <tr><td>Option OI / change</td><td>${big(r.oi)} / ${sgn(r.opt_oi_chg,0)}</td></tr>
  <tr><td>Contracts traded</td><td>${num(r.volume,0)}</td></tr></table></div>
 </div>`}
(()=>{const d=D.daily;if(!d||!d.options){$("#picks").innerHTML=`<div class="card empty">Daily scan has not run yet (runs ~7 PM IST).</div>`;return}
 let h=`<p class="note">Built from NSE's closing data for <b>${d.date}</b>. <b>Click any row</b> for the reasons, the Greeks explained, what-if scenarios and step-by-step Groww instructions.
 Prices are the last close: buy at the next open only if within ${D.gap}%. Grey cost = over your ${inr(D.capital,0)} budget.</p>`;
 h+=table([["Option",r=>`<b>${r.contract}</b> <span class="pill ${r.side}">${r.side}</span>`],["Setup",r=>`${r.buildup} <span class="muted">(price ${sgn(r.price_chg)}%, OI ${sgn(r.oi_chg,1)}%)</span>`],
  ["Ref price",r=>inr(r.entry)],["Lot",r=>r.lot],["Cost/lot",r=>`<span class="${r.affordable?"":"muted"}">${inr(r.cost_per_lot,0)}</span>`],
  ["If target",r=>`<span class="up">+${inr(r.profit_per_lot,0)}</span>`],["If stop",r=>`<span class="dn">${inr(r.loss_per_lot,0)}</span>`],
  ["Δ",r=>r.delta],["θ/lot/day",r=>`<span class="dn">${inr(r.theta_lot,0)}</span>`],["IV",r=>r.iv+"%"],["Expiry",r=>r.days+"d"]],
  d.options,"No option setups passed the filters for this session.",pickDetail);
 if(d.banned&&d.banned.length)h+=`<p class="note">In F&amp;O ban (no new positions allowed, excluded): ${d.banned.join(", ")}</p>`;
 $("#picks").innerHTML=h})();

// =============================== Track record
(()=>{const it=D.trades,dl=D.results.filter(r=>["TARGET","STOP","CLOSE"].includes(r.result));let h="";
 function summary(rows,label){const n=rows.map(r=>+r.net_pnl),w=n.filter(x=>x>0),l=n.filter(x=>x<=0),tot=n.reduce((a,b)=>a+b,0);
  const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
  return `<h2>${label}</h2><div class="grid">${card("Trades",rows.length)}${card("Win rate",rows.length?Math.round(w.length/rows.length*100)+"%":"–","","need ~35%+ to profit with +10/−5")}
  ${card("Avg win / loss",rows.length?`${inr(avg(w)??0,0)} / ${inr(avg(l)??0,0)}`:"–")}${card("Net P&L",rows.length?sgn(Math.round(tot),0):"–",cls(tot),"after estimated charges")}</div>`}
 function curve(rows,key){if(rows.length<2)return "";let c=0;return `<div class="card" style="margin-bottom:14px"><h3>Cumulative P&L</h3>${line(rows.map(r=>({x:(r[key]||"").slice(0,10),y:c+=+r.net_pnl})),130,{zero:true,fmt:v=>inr(v,0)})}</div>`}
 h+=summary(dl,"Next-day option picks (1 lot each)")+curve(dl,"trade_date");
 h+=table([["Day",r=>r.trade_date],["Option",r=>`${r.contract} <span class="pill ${r.side}">${r.side}</span>`],["Entry (open)",r=>inr(r.entry)],
  ["Exit",r=>inr(r.exit)],["Result",r=>`<span class="pill ${r.result==="TARGET"?"CE":r.result==="STOP"?"PE":"n"}">${r.result}</span>`],
  ["%",r=>`<span class="${cls(+r.pct)}">${sgn(+r.pct)}%</span>`],["Net P&L",r=>`<span class="${cls(+r.net_pnl)}">${sgn(+r.net_pnl,0)}</span>`]],
  D.results.slice().reverse(),"Picks are graded the evening after each session. First results after the next trading day.");
 h+=`<p class="note">Graded on the next day's open, high, low and close: entry at the open, then +${D.target}% target / −${D.stop}% stop. If both were touched the same day it counts as a stop (we can't see which came first). “SKIP GAP” = opened more than ${D.gap}% away. “CLOSE” = neither hit, sold at the close.</p>`;
 const em=D.engine_metrics||{};
 h+=`<h2>NIFTY engine (opening-range rule, real NSE prices)</h2>
 <p class="note">The main test. Bought at the asking price and sold at the bid price, with charges, 1-tick slippage and orders that don't fill all counted. Judge it on <b>average profit per trade</b> after 30+ trades, not on single wins.</p>
 <div class="grid">${card("Avg profit per trade",em.expectancy!=null?sgn(em.expectancy,0):"–",cls(em.expectancy),"= win% × avg win − loss% × avg loss")}
 ${card("Trades / win rate",em.trades?`${em.trades} · ${em.win_rate}%`:"0","","")}${card("Avg win / avg loss",em.trades?`${inr(em.avg_win,0)} / ${inr(em.avg_loss,0)}`:"–")}
 ${card("Total after costs",em.trades?sgn(em.net_total,0):"–",cls(em.net_total))}${card("Worst drop from a high",em.trades?inr(-em.max_drawdown,0):"–","dn",em.trades?`longest losing run: ${em.worst_streak}`:"")}
 ${card("Data problems",`${em.rejected_quotes||0} bad quotes`,"",`${em.unfilled||0} not filled · ${em.missed_exits||0} missed · ${em.unresolved||0} unresolved (not counted) · avg slippage ${em.avg_slippage!=null?inr(em.avg_slippage):"–"}`)}</div>`;
 const brk=(o,t)=>Object.keys(o||{}).length?`<div class="box"><h3>${t}</h3><table class="mini">${Object.entries(o).map(([k,v])=>`<tr><td>${k}</td><td>${v.n} trades</td><td class="${cls(v.exp)}">${sgn(v.exp,0)}/trade</td></tr>`).join("")}</table></div>`:"";
 if(em.trades)h+=`<div class="cols">${brk(em.by_hour,"By time of day")}${brk(em.by_expiry,"By days to expiry")}${brk(em.by_iv,"By option price level (IV)")}</div>`;
 h+=table([["Signal",r=>(r.signal_time||"").slice(0,16).replace("T"," ")],["Option",r=>`NIFTY ${r.strike} <span class="pill ${r.side}">${r.side}</span>`],["Bought",r=>r.entry?inr(+r.entry):"–"],["Sold",r=>r.exit?inr(+r.exit):"–"],
  ["Result",r=>`<span class="pill ${r.result==="TARGET"?"CE":r.result==="STOP"?"PE":"n"}">${r.result}</span>`],["How exit was priced",r=>`<span class="muted">${r.exit_basis||""}</span>`],["Net",r=>`<span class="${cls(+r.net_pnl)}">${sgn(+r.net_pnl||0,0)}</span>`]],
  (em.rows||[]).slice().reverse(),"No NIFTY engine trades yet. The first one comes when NIFTY breaks its opening range.");
 const ct=D.cash_trades||[];
 h+=summary(ct,"Normal share trades (live signals, real prices)")+curve(ct,"exit_time");
 h+=table([["Entry",r=>r.entry_time.slice(0,16).replace("T"," ")],["Stock",r=>`<b>${r.symbol}</b> ${r.action}`],["Qty",r=>r.qty],["Entry",r=>inr(r.entry)],["Exit",r=>inr(r.exit)],
  ["Result",r=>r.result],["%",r=>`<span class="${cls(+r.pct)}">${sgn(+r.pct)}%</span>`],["Net P&L",r=>`<span class="${cls(+r.net_pnl)}">${sgn(+r.net_pnl,0)}</span>`]],
  ct.slice().reverse(),"No share trades closed yet.");
 const stt=D.stock_trades||[];
 h+=summary(stt,"Live stock signals (estimated premiums, 1 lot each)")+curve(stt,"exit_time");
 h+=table([["Entry",r=>r.entry_time.slice(0,16).replace("T"," ")],["Option",r=>`${r.contract} <span class="pill ${r.side}">${r.side}</span>`],["Stock in → out",r=>`${inr(r.spot_in)} → ${inr(r.spot_out)}`],
  ["Prem. est. in → out",r=>`${inr(r.entry_est)} → ${inr(r.exit_est)}`],["Result",r=>r.result],["%",r=>`<span class="${cls(+r.pct)}">${sgn(+r.pct)}%</span>`],["Net P&L",r=>`<span class="${cls(+r.net_pnl)}">${sgn(+r.net_pnl,0)}</span>`]],
  stt.slice().reverse(),"No live stock paper trades closed yet.");
 h+=`<p class="note">⚠️ These option results are a <b>model estimate</b>: there are no live quotes for stock options, so prices are calculated from the share price and yesterday's volatility, with a 1% price penalty each way. Real results can differ a lot. Trust the share trades and NIFTY results more.</p>`;
 h+=summary(it,"NIFTY intraday (15-min scanner)")+curve(it,"exit_time");
 h+=table([["Entry",r=>r.entry_time.slice(0,16).replace("T"," ")],["Option",r=>r.contract],["Entry",r=>inr(r.entry)],["Exit",r=>inr(r.exit)],
  ["Result",r=>r.result],["%",r=>`<span class="${cls(+r.pct)}">${sgn(+r.pct)}%</span>`],["Net P&L",r=>`<span class="${cls(+r.net_pnl)}">${sgn(+r.net_pnl,0)}</span>`]],
  it.slice().reverse(),"No intraday paper trades closed yet.");
 $("#track").innerHTML=h})();

// =============================== Long-term
function ltDetail(r){const b=D.daily.benchmark||{},pos=(r.price-r.low52)/((r.high52-r.low52)||1)*100;
 const cmp=(a,x)=>a==null?"–":`<span class="${cls(a)}">${sgn(a,1)}%</span>`+(x!=null?` <span class="muted">vs NIFTY ${sgn(x,1)}%</span>`:"");
 return `<div class="cols">
 <div class="box"><h3>${r.name}: price over the last 12 months</h3>${line(r.spark.map(p=>({x:p[0],y:p[1]})),120,{fmt:v=>inr(v,0)})}
  <div class="range"><i style="left:${pos}%"></i></div><div class="muted" style="font-size:12px;display:flex;justify-content:space-between"><span>Lowest this year ${inr(r.low52,0)}</span><span>Highest this year ${inr(r.high52,0)}</span></div></div>
 <div class="box"><h3>How much it grew</h3><table class="mini">
  <tr><td>6 months</td><td>${cmp(r.ret6m)}</td></tr><tr><td>1 year</td><td>${cmp(r.ret12m,b.ret12m)}</td></tr>
  <tr><td>Each year, last 3 years</td><td>${cmp(r.cagr3,b.cagr3)}</td></tr><tr><td>Each year, last 5 years</td><td>${cmp(r.cagr5,b.cagr5)}</td></tr>
  <tr><td>Biggest drop this year</td><td class="dn">${r.dd1y}%</td></tr><tr><td>Biggest drop in 5 years</td><td class="dn">${r.dd5y}% <span class="muted">vs NIFTY ${b.dd5y??"–"}%</span></td></tr>
  <tr><td>How much it swings</td><td>${r.volatility}%</td></tr></table></div>
 <div class="box"><h3>Key numbers</h3><table class="mini">
  <tr><td>Price vs yearly profit (P/E)</td><td>${r.pe??"–"}</td></tr><tr><td>Price vs company's assets (P/B)</td><td>${r.pb??"–"}</td></tr>
  <tr><td>Company size (market value)</td><td>${r.mcap_cr?"₹"+num(r.mcap_cr,0)+" Cr":"–"}</td></tr><tr><td>Yearly cash paid to shareholders</td><td>${r.div_yield!=null?r.div_yield+"%":"–"}</td></tr>
  <tr><td>Usual price (last 50 days)</td><td>${inr(r.ma50,0)}</td></tr><tr><td>Usual price (last 200 days)</td><td>${inr(r.ma200,0)}</td></tr>
  <tr><td>Group · business type</td><td>${r.index} · ${r.industry}</td></tr></table></div>
 <div class="box"><h3>🏢 Company health</h3>${healthHTML(r.fund)}</div>
 <div class="box"><h3>📊 Chart now</h3>${r.chart?`<ul class="hl">${r.chart.checks.map(c=>`<li>${c.ok?"✅":"❌"} <b>${c.name}:</b> ${c.text}${c.tech?` <span class="tech">${c.tech}</span>`:""}</li>`).join("")}</ul>`:"–"}</div>
 <div class="box"><h3>How to use this</h3><ul>
  <li><b>When to buy:</b> ${r.zone}.</li>
  <li>Buy in 2–3 parts over a few weeks instead of all at once.</li>
  <li>Before buying, look at the company's latest results on Groww (stock page → Financials).</li>
  <li><b>Think about selling</b> if the price falls below ${inr(r.ma200,0)} (its usual level over the last 200 days): the steady rise has ended.</li>
  <li>Plan to hold for 3+ years. Profits on shares held over 1 year are taxed less.</li></ul></div></div>`}
(()=>{const d=D.daily;if(!d||!d.long_term||!d.long_term.length){$("#lt").innerHTML=`<div class="card empty">Runs with the daily scan.</div>`;return}
 const b=d.benchmark||{},alloc=d.long_term.filter(r=>r.alloc_shares>0),tot=alloc.reduce((a,r)=>a+r.alloc_amount,0);
 let h=`<p class="note">${d.long_term_note}. We pick companies whose share price has been rising steadily <b>and</b> whose business is healthy (weak companies are left out). <b>Tap a stock</b> to see its price chart, how much it has grown, how healthy it is, and when to buy. Use this as a starting list, then do your own checks.</p>`;
 if(b.cagr5!=null)h+=`<div class="grid">${card("Whole market · last 1 year",sgn(b.ret12m,1)+"%",cls(b.ret12m))}${card("Whole market · per year (3 yrs)",sgn(b.cagr3,1)+"%",cls(b.cagr3))}${card("Whole market · per year (5 yrs)",sgn(b.cagr5,1)+"%",cls(b.cagr5),"what an index fund gave, with no stock picking")}${card("Biggest drop in 5 years",b.dd5y+"%","dn")}</div>`;
 if(alloc.length)h+=`<h2>Example: how to split ${inr(d.lt_budget,0)}</h2><p class="note">Roughly equal money in up to 5 companies, not more than 2 from the same type of business, so one bad sector can't hurt you too much.</p>`+
  table([["Stock",r=>`<b>${r.symbol}</b>`],["Price",r=>inr(r.price)],["Shares",r=>r.alloc_shares],["Amount",r=>inr(r.alloc_amount,0)],["When to buy",r=>`<span class="muted">${r.zone}</span>`]],alloc,"")+
  `<p class="note">Total ${inr(tot,0)} · leftover ${inr(d.lt_budget-tot,0)}. Many people put half in a NIFTY 50 index fund and half in picks like these.</p>`;
 h+=`<h2>Watchlist</h2>`+table([["Stock",r=>`<b>${r.symbol}</b> <span class="muted">${r.name}</span>`],["Price",r=>inr(r.price)],
  ["1 yr",r=>`<span class="${cls(r.ret12m)}">${sgn(r.ret12m,1)}%</span>`],["Per yr (3 yrs)",r=>r.cagr3!=null?`<span class="${cls(r.cagr3)}">${sgn(r.cagr3,1)}%</span>`:"–"],
  ["Per yr (5 yrs)",r=>r.cagr5!=null?`<span class="${cls(r.cagr5)}">${sgn(r.cagr5,1)}%</span>`:"–"],["Health",r=>r.health!=null?`<span class="hb ${r.health>=70?"g":r.health>=50?"m":"b"}">${r.health}</span>`:"–"],["P/E",r=>r.pe??"–"],["Below its top",r=>r.from_high+"%"],
  ["When to buy",r=>`<span class="pill ${r.extended?"n":"CE"}">${r.extended?"wait for a dip":"OK to buy now"}</span>`]],d.long_term,"No stocks passed the screen.",ltDetail);
 $("#lt").innerHTML=h})();

// =============================== Guide
$("#guide").innerHTML=`
<h2 style="margin-top:8px">How this system works</h2>
<p>Two automatic jobs feed this page:</p>
<table><tr><th>Job</th><th>When</th><th>What it does</th></tr>
<tr><td><b>NIFTY intraday</b></td><td>Every 15 min, 9:15–3:30 PM, Mon–Fri</td><td>Reads the live NIFTY option chain, scores the market −3 to +3, and if strong enough “buys” one option on paper. It then tracks it to +${D.target}% target, −${D.stop}% stop or 3:15 PM, and logs the result.</td></tr>
<tr><td><b>Daily scan</b></td><td>About 7 PM on trading days</td><td>Downloads NSE's official closing data for all F&amp;O stocks. It grades yesterday's picks, finds next-day CE/PE setups and refreshes the long-term watchlist.</td></tr></table>
<p>You get alerts on WhatsApp / Telegram / Mac. Everything is <b>paper trading</b> until you decide the track record is good enough.</p>

<h2>Reading an option chain</h2>
<ul><li><b>CE (call)</b> gains when the price goes <b>up</b>. <b>PE (put)</b> gains when it goes <b>down</b>.</li>
<li><b>Strike</b>: the reference price of the contract. <b>ATM</b> (at-the-money) is the strike nearest the current price, highlighted blue.</li>
<li><b>ITM</b> options are already “winning” (expensive, move like the stock). <b>OTM</b> options are cheap but usually expire worthless.</li>
<li><b>LTP</b>: last traded premium per share. Cost = LTP × lot size (NIFTY lot = ${D.lot}).</li>
<li><b>OI (open interest)</b>: open contracts. Option <i>sellers</i> are usually big players, so a large call OI wall above the price acts as <b>resistance</b> and a large put OI wall below acts as <b>support</b>.</li>
<li><b>OI change</b>: today's new positions. This shows where fresh money is going and matters more than total OI.</li>
<li><b>PCR</b> (put/call OI ratio): above 1.2 means put sellers dominate (bullish lean). Below 0.8 means call sellers dominate (bearish lean or upside capped).</li></ul>

<h2>The Greeks</h2>
<table><tr><th>Greek</th><th>Meaning</th><th>What to do with it</th></tr>
<tr><td><b>Delta</b></td><td>How much the option moves per ₹1 move in the underlying. 0.5 means about 50 paise.</td><td>We pick 0.40–0.60: enough movement, not too expensive. Below 0.2 is a lottery ticket.</td></tr>
<tr><td><b>Theta</b></td><td>Rupees the option loses per day from time passing. Always works against buyers.</td><td>It speeds up in the last week before expiry. That's why we avoid options with under 2 days (NIFTY) or 7 days (stocks) left, and exit the same day.</td></tr>
<tr><td><b>Gamma</b></td><td>How fast delta changes.</td><td>High near expiry: profits and losses swing wildly. Fine for experts, dangerous for beginners.</td></tr>
<tr><td><b>Vega</b></td><td>Rupees gained or lost per 1% change in IV.</td><td>Don't buy just before big events (results, RBI, budget). IV drops right after and you can lose even when right on direction.</td></tr>
<tr><td><b>IV</b></td><td>Implied volatility, how expensive options are.</td><td>The scanner skips trades when NIFTY IV spikes 25% above its usual level.</td></tr></table>

<h2>How the NIFTY signal is scored</h2>
<p>Three votes, each +1 (bullish), −1 (bearish) or 0:</p>
<ol><li><b>Day trend</b>: NIFTY more than 0.15% above or below today's open.</li>
<li><b>Momentum</b>: NIFTY moved more than 0.10% in the last 30 minutes.</li>
<li><b>OI build-up</b>: put sellers adding more than call sellers (support building) or the reverse.</li></ol>
<p>Score <b>+2 or more → buy CE</b>, <b>−2 or less → buy PE</b>. It's then blocked if NIFTY is within 0.4% of the OI wall it would have to break, before 9:45 or after 2:30 PM, IV has spiked, 3 trades are done today, 2 losses happened today, or the last exit was under 30 minutes ago.</p>

<h2>How next-day stock picks are chosen</h2>
<table><tr><th>Price</th><th>Open interest</th><th>Meaning</th><th>Action</th></tr>
<tr><td>Up ≥1%</td><td>Up ≥3%</td><td><b>Long build-up</b>: new buyers entering</td><td>Buy CE</td></tr>
<tr><td>Down ≥1%</td><td>Up ≥3%</td><td><b>Short build-up</b>: new sellers entering</td><td>Buy PE</td></tr>
<tr><td>Up</td><td>Down</td><td>Short covering (weaker)</td><td>Skipped</td></tr>
<tr><td>Down</td><td>Down</td><td>Long unwinding (weaker)</td><td>Skipped</td></tr></table>
<p>Then it keeps only the ~120 most-traded F&amp;O stocks plus NIFTY/BANKNIFTY, drops stocks in the F&amp;O ban, and requires the build-up to agree with the 20-day average trend. It picks the nearest expiry with 7+ days left (2+ for indices), delta closest to 0.5, at least 200 contracts traded. Top 5 calls and top 5 puts by strength.</p>

<h2>Trading a pick: the rules that matter</h2>
<ol><li><b>Paper-trade first.</b> Watch the Track record tab for 2–3 weeks.</li>
<li><b>Skip gaps.</b> If the option opens more than ${D.gap}% away from the listed price, the setup has changed.</li>
<li><b>Always use the stop.</b> With +${D.target}% / −${D.stop}%, you only need to win about 35% of trades to break even after costs. Without a stop, one bad day wipes out many wins.</li>
<li><b>One lot at a time</b>, and never more than ${inr(D.capital,0)} per trade (change it in config.json).</li>
<li><b>Exit the same day.</b> Theta and overnight news hurt option buyers.</li>
<li><b>Stop after 2 losses in a day.</b> Revenge trading is how most F&amp;O losses happen.</li></ol>

<h2>Reading the track record</h2>
<ul><li><b>Win rate</b> alone means little. Look at <b>net P&amp;L after charges</b> and the cumulative curve.</li>
<li>Judge after at least <b>30 trades</b>. A few days of results is mostly luck.</li>
<li>Grading is deliberately strict: if a day touched both target and stop, it counts as a loss.</li>
<li>If after 30+ trades the net P&amp;L is negative, the rules don't work in the current market. Change them or don't trade them.</li></ul>

<h2>Reading candles and chart checks</h2>
<p>Each candle shows one period (a day, or 5 minutes intraday): where the price <b>opened</b>, its <b>high</b> and <b>low</b>, and where it <b>closed</b>. Green means it closed higher than it opened; red means lower.</p>
<table><tr><th>Pattern</th><th>Looks like</th><th>Usually means</th></tr>
<tr><td><b>Bullish engulfing</b></td><td>A green candle that fully covers the previous red one</td><td>Buyers took over. Supports an UP idea</td></tr>
<tr><td><b>Bearish engulfing</b></td><td>A red candle that fully covers the previous green one</td><td>Sellers took over. Supports a DOWN idea</td></tr>
<tr><td><b>Hammer</b></td><td>Small body at the top, long lower wick</td><td>Price fell, then buyers pushed it back up</td></tr>
<tr><td><b>Shooting star</b></td><td>Small body at the bottom, long upper wick</td><td>Price rose, then sellers pushed it back down</td></tr>
<tr><td><b>Doji</b></td><td>Open ≈ close, tiny body</td><td>Indecision. Wait for the next candle</td></tr>
<tr><td><b>Strong candle</b></td><td>Big body, small wicks</td><td>One side was firmly in control</td></tr></table>
<p>Every idea gets 5 checks: <b>Trend</b> (price vs its average), <b>RSI</b> (momentum: above 70 is overbought, below 30 oversold), <b>MACD</b> (whether buyers or sellers are in control and getting stronger), <b>Candle</b> (the last candle's pattern) and <b>Room</b> (distance to the nearest resistance or support). Ideas whose chart clearly disagrees, such as a bearish engulfing candle on an UP idea, are removed automatically.</p>

<h2>Company health score</h2>
<p>For long-term picks, each company gets a score out of 100 from five things, each worth the same:</p>
<table><tr><th>Part</th><th>What it measures</th><th>Good sign</th></tr>
<tr><td><b>Profitability</b></td><td>Return on equity (for banks: return on assets)</td><td>ROE above 15–18%; bank ROA above 1%</td></tr>
<tr><td><b>Growth</b></td><td>Profit growth per year over the last 3 years</td><td>Above 12% a year</td></tr>
<tr><td><b>Debt</b></td><td>Debt compared with shareholders' money (not used for banks)</td><td>Below 0.5×</td></tr>
<tr><td><b>Valuation</b></td><td>P/E compared with similar companies</td><td>Equal to or cheaper than peers</td></tr>
<tr><td><b>Margins</b></td><td>How much of each ₹100 of sales is kept as profit</td><td>Above 12%</td></tr></table>
<p>70+ = strong, 50–69 = average, under 50 = weak. Data comes from Yahoo Finance and can be a few months old, so check the latest results on Groww before buying.</p>

<h2>Long-term watchlist</h2>
<p>From NIFTY 50 + NIFTY Next 50, it keeps stocks in a healthy uptrend: price above the 200-day average, 50-day above 200-day, within 15% of the 52-week high, and positive over 1 year. It ranks them by 6- and 12-month momentum minus a volatility penalty. “Fair zone” means the price is near its 50-day average. “Wait for dip” means it has run up more than 8% above it.</p>
<p>Momentum lists change over time, and a stock can drop off when its trend breaks. Always compare with the NIFTY 50 numbers shown: if the picks don't beat the index after 3+ years, an index fund is the better choice.</p>

<h2>Limitations</h2>
<ul><li>Data comes from NSE's public website and Yahoo Finance. Either can be late, missing or blocked.</li>
<li>The 15-minute scan can miss quick moves through the target or stop. Place real stop-loss orders in Groww.</li>
<li>Charges are estimates. Check a Groww contract note to confirm.</li>
<li>Past results never guarantee future results. SEBI's studies found about 9 in 10 individual F&amp;O traders lose money.</li></ul>`;

// =============================== live updates (only when served by app.py live)
(()=>{const ticker=$("#ticker");
 const setv=(el,txt,dir)=>{if(!el||el.textContent===txt)return;el.textContent=txt;if(dir){el.classList.remove("flash-up","flash-dn");void el.offsetWidth;el.classList.add(dir>0?"flash-up":"flash-dn")}};
 const last={};
 function apply(L){
  const ix=L.indices||{};ticker.classList.add("on");
  const age=L.ts?Math.round((Date.now()-new Date(L.ts))/1000):null;
  ticker.innerHTML=`<span class="dot ${L.market_open?"":"off"}">● ${L.market_open?"LIVE":"MARKET CLOSED"}</span>`+
   ["NIFTY 50","NIFTY BANK"].filter(k=>ix[k]).map(k=>`<span class="ti">${k} <b data-t="${k}">${num(ix[k].last)}</b> <span class="${cls(ix[k].pchg)}">${sgn(ix[k].pchg)}%</span></span>`).join("")+
   `<span class="muted" style="font-size:12px">${L.quote_time?"NSE prices as of "+L.quote_time.slice(-8):(age!=null?"fetched "+(age<90?age+"s":Math.round(age/60)+" min")+" ago":"")}${(()=>{try{const q=new Date(L.quote_time.replace(/-/g," "));return L.market_open&&(Date.now()-q)/6e4>5?' · <b style="color:var(--dn)">prices may be stale</b>':""}catch(e){return ""}})()} · ideas update every 15 min</span>`;
  Object.entries(ix).forEach(([k,v])=>{const dir=last[k]!=null?Math.sign(v.last-last[k]):0;last[k]=v.last;
   document.querySelectorAll(`[data-t="${k}"]`).forEach(e=>dir&&e.classList.add(dir>0?"flash-up":"flash-dn"));
   document.querySelectorAll(`[data-idx="${k}"]`).forEach(e=>setv(e,num(v.last,0),dir));
   document.querySelectorAll(`[data-idxp="${k}"]`).forEach(e=>{e.textContent=sgn(v.pchg)+"%";e.className=cls(v.pchg)})});
  document.querySelectorAll("[data-stock]").forEach(e=>{const s=(L.stocks||{})[e.dataset.stock];if(!s)return;
   const k="s:"+e.dataset.stock,dir=last[k]!=null?Math.sign(s.price-last[k]):0;last[k]=s.price;
   e.innerHTML=`${e.dataset.stock} live: <b>${inr(s.price)}</b>${s.pchg!=null?` <span class="${cls(s.pchg)}">${sgn(s.pchg)}%</span>`:""}`;
   if(dir){e.classList.remove("flash-up","flash-dn");void e.offsetWidth;e.classList.add(dir>0?"flash-up":"flash-dn")}});
  document.querySelectorAll("[data-opt]").forEach(e=>{const o=(L.nifty_opts||{})[e.dataset.opt];if(!o)return;
   e.innerHTML=e.closest(".idea-contract")?inr(o.ltp):`Price now <b>${inr(o.ltp)}</b> (live)`});
  if(L.built_epoch&&L.built_epoch>D.built_epoch+2){try{localStorage.scroll=scrollY}catch(e){}location.reload()}}
 async function poll(){try{const r=await fetch("live.json",{cache:"no-store"});if(r.ok)apply(await r.json())}catch(e){}}
 if(location.protocol.startsWith("http")){poll();setInterval(poll,5000)}
 else setTimeout(()=>location.reload(),300000); // static file: reload every 5 min
 try{const y=+localStorage.scroll;if(y){scrollTo(0,y);localStorage.removeItem("scroll")}}catch(e){}
})();
</script></body></html>"""


def build():
    today = now_ist().date().isoformat()
    data = {
        "built": now_ist().strftime("%d %b %Y %H:%M"), "mode": CONFIG["mode"],
        "built_epoch": __import__("time").time(),
        "target": CONFIG["target_pct"], "stop": CONFIG["stop_pct"],
        "capital": CONFIG["capital_per_trade"], "gap": CONFIG["daily"]["gap_skip_pct"],
        "lot": CONFIG["intraday"]["lot_size"],
        "state": read_json(DATA / "state.json", {}),
        "chain": read_json(DATA / "chain.json", {}),
        "snapshots": [r for r in read_csv(DATA / "snapshots.csv") if r["time"].startswith(today)],
        "trades": read_csv(DATA / "trades.csv"),
        "daily": read_json(DATA / "daily.json", {}),
        "results": read_csv(DATA / "daily_results.csv"),
        "stocks": read_json(DATA / "stocks_live.json", {}),
        "stock_state": read_json(DATA / "stock_state.json", {}),
        "stock_trades": read_csv(DATA / "stock_trades.csv"),
        "cash_trades": read_csv(DATA / "cash_trades.csv"),
        "engine": read_json(DATA / "engine_state.json", {}),
        "engine_metrics": __import__("engine").metrics(),
        "st": CONFIG["stocks"], "min_health": CONFIG["daily"]["lt_min_health"],
    }
    if data["stock_state"].get("day") != today:
        data["stock_state"] = {}
    DOCS.mkdir(exist_ok=True)
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    out = DOCS / "index.html"
    out.write_text(TEMPLATE.replace("__DATA__", blob))
    return out
