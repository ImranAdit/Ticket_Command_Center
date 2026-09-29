"""
SLA preview router (rules v3) — side-by-side with the current dashboard.

GET  /api/sla/preview        JSON: per-department evaluations + counts
GET  /api/sla/preview.html   simple page to review the new rules
POST /api/sla/refresh        re-run the preview on the last synced tickets
GET  /api/sla/inspect?id=    structure-only view of one ticket's Zoho detail payloads
"""
from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import HTMLResponse

from services import sla_preview

router = APIRouter()


@router.get("/preview")
def preview(state: str | None = Query(None, description="Filter: breach, at_risk, unclear, scheduled, ok")):
    s = sla_preview.get_state()
    depts = s["departments"]
    if state:
        wanted = set(state.split(","))
        depts = {d: [r for r in rows if r["state"] in wanted] for d, rows in depts.items()}
    return {
        "generated_at": s["generated_at"],
        "running": s["running"],
        "progress": s["progress"],
        "counts": s["counts"],
        "errors": s["errors"],
        "departments": depts,
    }


@router.post("/refresh")
async def refresh(background_tasks: BackgroundTasks):
    from services import zoho_fetcher_v2
    raw = getattr(zoho_fetcher_v2, "LAST_GROUPED_RAW", None)
    if not raw:
        return {"status": "no_data", "message": "Run a sync first"}
    background_tasks.add_task(sla_preview.refresh, raw)
    return {"status": "triggered"}


@router.get("/inspect")
async def inspect(id: str):
    return await sla_preview.inspect(id)


@router.get("/probe-sources")
async def probe_sources():
    """
    Read-only diagnostic: for each ZOHO_REPORT_* link, check which Zoho Desk API calls can
    read it (report or view). Returns status codes / key names only — no ticket content.
    """
    import os, re, httpx
    from services.sla_preview import _get_raw_status

    def slug(t):
        return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")

    out = []
    async with httpx.AsyncClient() as client:
        views_status, views = await _get_raw_status(client, "/api/v1/views", {"module": "tickets", "limit": 100})
        view_list = [{"id": v.get("id"), "name": v.get("name")} for v in ((views or {}).get("data") or [])]
        # custom views are per department — try each department seen on synced tickets
        from services import zoho_fetcher_v2
        dept_ids = sorted({str(t.get("departmentId")) for ts in (zoho_fetcher_v2.LAST_GROUPED_RAW or {}).values()
                           for t in ts if t.get("departmentId")})
        dept_view_status = {}
        for did in dept_ids + ["allDepartment"]:
            st, j = await _get_raw_status(client, "/api/v1/views", {"module": "tickets", "departmentId": did, "limit": 100})
            dept_view_status[did] = st
            for x in ((j or {}).get("data") or []) if isinstance(j, dict) else []:
                if not any(y["id"] == x.get("id") for y in view_list):
                    view_list.append({"id": x.get("id"), "name": x.get("name"), "departmentId": did})
        for name in sorted(k for k in os.environ if k.startswith("ZOHO_REPORT_")):
            url = os.getenv(name) or ""
            entry = {"variable": name, "attempts": []}
            m = re.search(r"/reports/details/(\d+)", url)
            v = re.search(r"/tickets/(?:q/status|list|view)/([\w-]+)", url)
            if m:
                rid = m.group(1)
                entry.update(kind="report", id=rid)
                st, j = await _get_raw_status(client, f"/api/v1/reports/{rid}")
                entry["report"] = {"status": st, "name": (j or {}).get("name") if isinstance(j, dict) else None,
                                   "reportType": (j or {}).get("reportType") if isinstance(j, dict) else None}
                from services.sla_preview import _headers, _api_base
                try:
                    r = await client.get(f"{_api_base()}/api/v1/reports/{rid}/export", headers=_headers(), timeout=40)
                    body = r.content or b""
                    text = body[:4000].decode("utf-8", "replace")
                    lines = text.splitlines()
                    entry["export"] = {"status": r.status_code, "content_type": r.headers.get("content-type"),
                                       "bytes": len(body), "first_line_columns": lines[0][:400] if lines else None,
                                       "approx_rows": body.count(b"\n"),
                                       "json_keys": (sorted(r.json().keys()) if "json" in r.headers.get("content-type", "") else None)}
                except Exception as e:
                    entry["export"] = {"error": str(e)[:150]}
            elif v:
                entry.update(kind="view", slug=v.group(1))
                match = next((x for x in view_list if slug(x["name"]) == v.group(1)), None)
                entry["view_match"] = match
                if match:
                    st, j = await _get_raw_status(client, "/api/v1/tickets", {"viewId": match["id"], "limit": 5})
                    entry["attempts"].append({"path": "/api/v1/tickets?viewId=", "status": st,
                                              "rows": len((j or {}).get("data") or []) if isinstance(j, dict) else None})
            else:
                entry["kind"] = "unrecognised link"
            out.append(entry)
    return {"views_api_status": views_status, "dept_view_status": dept_view_status, "views_found": len(view_list),
            "view_names": [x["name"] for x in view_list][:80], "sources": out}


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>SLA Preview — Ticket Command Center</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0e14;--card:#131722;--line:#232a3a;--txt:#e6e9ef;--mut:#8a93a6;--red:#ff4d5e;--amb:#f5a524;--blu:#3fb6ff;--grn:#35c46a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:16px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0;letter-spacing:.5px}.mut{color:var(--mut)}main{padding:16px 24px;max-width:1400px;margin:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.tile b{font-size:22px;display:block}
.dept{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:14px;overflow:hidden}
.dept h2{font-size:14px;margin:0;padding:12px 14px;border-bottom:1px solid var(--line);display:flex;gap:10px;flex-wrap:wrap}
table{width:100%;border-collapse:collapse}td,th{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px}a{color:var(--blu);text-decoration:none}
.pill{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid;white-space:nowrap}
.breach{color:var(--red);border-color:#ff4d5e55}.at_risk{color:var(--amb);border-color:#f5a52455}
.unclear,.scheduled{color:var(--blu);border-color:#3fb6ff55}.ok,.paused{color:var(--grn);border-color:#35c46a55}
select,button{background:var(--card);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
.wrap{overflow-x:auto}.err{color:var(--amb);font-size:12px}
</style></head><body>
<header><h1>SLA PREVIEW · new breach rules</h1><span class="mut" id="meta">loading…</span>
<select id="f"><option value="breach,at_risk,unclear">Breach + At risk + Unclear</option><option value="breach">Breach only</option>
<option value="at_risk">At risk only</option><option value="unclear">Callback time unclear</option><option value="scheduled">Callbacks scheduled</option><option value="">All tickets</option></select>
<button id="r">Re-run</button></header>
<main><div class="tiles" id="tiles"></div><div id="errs"></div><div id="depts"></div></main>
<script>
const RULE={first_response:"First response",inactivity:"Agent inactivity",carried_over:"Carried over (24h)",callback:"Pending Meeting callback",paused:"Paused",unassigned:"Unassigned"};
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function load(){
  const f=document.getElementById('f').value;
  const r=await fetch('/api/sla/preview'+(f?'?state='+f:'')).then(r=>r.json());
  const t=r.counts||{};let tot={breach:0,at_risk:0,unclear:0,scheduled:0};
  Object.values(t).forEach(c=>Object.keys(tot).forEach(k=>tot[k]+=c[k]||0));
  document.getElementById('meta').textContent=(r.running?`Refreshing ${r.progress.done}/${r.progress.total}… · `:'')+(r.generated_at?'Updated '+new Date(r.generated_at).toLocaleString():'Not generated yet — waits for next sync');
  document.getElementById('tiles').innerHTML=[['Breach','breach'],['At risk (7h)','at_risk'],['Callback time unclear','unclear'],['Callbacks scheduled','scheduled']]
    .map(([l,k])=>`<div class="tile"><span class="mut">${l}</span><b class="${k}">${tot[k]}</b></div>`).join('');
  document.getElementById('errs').innerHTML=(r.errors||[]).slice(-5).map(e=>`<div class="err">⚠ ${esc(e)}</div>`).join('');
  document.getElementById('depts').innerHTML=Object.entries(r.departments||{}).map(([d,rows])=>{
    const c=t[d]||{};
    return `<div class="dept"><h2>${esc(d)} <span class="pill breach">${c.breach||0} breach</span><span class="pill at_risk">${c.at_risk||0} at risk</span><span class="pill unclear">${c.unclear||0} unclear</span></h2>
    <div class="wrap"><table><tr><th>Ticket</th><th>State</th><th>Rule</th><th>Agent</th><th>Status</th><th>Detail</th></tr>
    ${rows.map(x=>`<tr><td><a href="${esc(x.zoho_url)}" target="_blank">#${esc(x.ticketNumber)}</a><div class="mut">${esc((x.subject||'').slice(0,70))}</div></td>
    <td><span class="pill ${x.state}">${x.state.replace('_',' ')}</span></td><td>${RULE[x.rule]||x.rule}</td><td>${esc(x.agent)}</td><td>${esc(x.status)}</td><td class="mut">${esc(x.detail)}</td></tr>`).join('')||'<tr><td colspan="6" class="mut">Nothing in this view</td></tr>'}
    </table></div></div>`}).join('');
}
document.getElementById('f').onchange=load;
document.getElementById('r').onclick=async()=>{await fetch('/api/sla/refresh',{method:'POST'});setTimeout(load,1500)};
load();setInterval(load,20000);
</script></body></html>"""


@router.get("/preview.html", response_class=HTMLResponse)
def preview_page():
    return _PAGE
