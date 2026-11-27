#!/usr/bin/env python3
\"\"\"Add-on dashboard builder. Reads ranking_observations.csv and writes docs/index.html.
Does not modify collector.py, daily_analysis.py, or the raw CSV. Standard library only.
Run from repository root: python build_dashboard.py
\"\"\"
import csv, html, json, math, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "ranking_observations.csv"
DEST = ROOT / "docs" / "index.html"
MT = ZoneInfo("America/Denver")
REQUIRED = {"snapshot_id","collected_at","position","title","url","upvotes","predicted_position"}

def avg(xs):
    return statistics.mean(xs) if xs else None

def med(xs):
    return statistics.median(xs) if xs else None

def ranks(xs):
    order = sorted(enumerate(xs), key=lambda z:z[1])
    out = [0.0]*len(xs); i = 0
    while i < len(order):
        j=i+1
        while j<len(order) and order[j][1]==order[i][1]: j+=1
        rank=((i+1)+j)/2
        for k in range(i,j): out[order[k][0]]=rank
        i=j
    return out

def rho(xs,ys):
    if len(xs)<2: return None
    a,b=ranks(xs),ranks(ys); ma,mb=avg(a),avg(b)
    num=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    da=math.sqrt(sum((x-ma)**2 for x in a)); db=math.sqrt(sum((y-mb)**2 for y in b))
    return num/(da*db) if da and db else None

def fnum(x,d=2):
    return "—" if x is None else f"{x:.{d}f}"

def fpct(x):
    return "—" if x is None else f"{x:.1f}%"

def read_data():
    if not SOURCE.exists():
        raise FileNotFoundError("ranking_observations.csv must be in the repository root.")
    with SOURCE.open(encoding="utf-8-sig", newline="") as f:
        reader=csv.DictReader(f)
        missing=REQUIRED-set(reader.fieldnames or [])
        if missing: raise ValueError("CSV missing columns: "+", ".join(sorted(missing)))
        rows=[]
        for n,r in enumerate(reader,2):
            dt=datetime.fromisoformat(r["collected_at"].replace("Z","+00:00"))
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            dt=dt.astimezone(timezone.utc)
            actual=float(r["position"]); predicted=float(r["predicted_position"])
            rows.append(dict(snapshot=r["snapshot_id"],dt=dt,date=dt.astimezone(MT).strftime("%Y-%m-%d"),
                actual=actual,predicted=predicted,diff=predicted-actual,error=abs(predicted-actual),
                title=r["title"] or "(untitled)",url=r["url"] or "",upvotes=float(r["upvotes"])))
    if not rows: raise ValueError("ranking_observations.csv has no data rows.")
    return sorted(rows,key=lambda x:(x["dt"],x["actual"]))

def analyze(rows):
    groups=defaultdict(list)
    for r in rows: groups[r["snapshot"]].append(r)
    snaps=[]
    for sid,items in groups.items():
        items.sort(key=lambda x:x["actual"]); errors=[x["error"] for x in items]
        snaps.append(dict(id=sid,dt=items[0]["dt"],date=items[0]["date"],items=items,n=len(items),
            exact=sum(x["diff"]==0 for x in items)/len(items)*100,mae=avg(errors),median=med(errors),
            rho=rho([x["actual"] for x in items],[x["predicted"] for x in items])))
    snaps.sort(key=lambda x:x["dt"])
    days=defaultdict(list)
    for s in snaps: days[s["date"]].append(s)
    daily=[dict(date=d,n=len(ss),obs=sum(s["n"] for s in ss),
        exact=avg([s["exact"] for s in ss]),mae=avg([s["mae"] for s in ss]),
        median=avg([s["median"] for s in ss]),rho=avg([s["rho"] for s in ss if s["rho"] is not None]))
        for d,ss in sorted(days.items())]
    cumulative=[]; running=[]
    for s in snaps:
        running.extend(s["items"])
        cumulative.append(dict(date=s["date"],count=len(cumulative)+1,obs=len(running),
            exact=sum(x["diff"]==0 for x in running)/len(running)*100,
            mae=avg([x["error"] for x in running]),median=med([x["error"] for x in running]),
            rho=rho([x["actual"] for x in running],[x["predicted"] for x in running])))
    posts=defaultdict(list)
    for r in rows: posts[(r["url"],r["title"])].append(r)
    postlist=[]
    for (url,title),items in posts.items():
        postlist.append(dict(url=url,title=title,n=len(items),mae=avg([x["error"] for x in items]),
            maxerr=max(x["error"] for x in items),votes=avg([x["upvotes"] for x in items]),
            actual=avg([x["actual"] for x in items]),pred=avg([x["predicted"] for x in items])))
    postlist.sort(key=lambda x:(x["mae"],x["n"]),reverse=True)
    errors=[r["error"] for r in rows]; exact=sum(r["diff"]==0 for r in rows)
    overall=dict(n=len(rows),snapshots=len(snaps),posts=len(set(r["url"] for r in rows)),
        exact=exact/len(rows)*100,exactn=exact,mae=avg(errors),median=med(errors),
        rho=rho([r["actual"] for r in rows],[r["predicted"] for r in rows]),
        first=snaps[0]["date"],last=snaps[-1]["date"])
    quality=[]
    for s in snaps:
        items=s["items"]; urls=[x["url"] for x in items]; positions=[x["actual"] for x in items]
        ok=len(items)==len(set(urls))==len(set(positions)) and all(x["url"] and x["title"] for x in items)
        quality.append(dict(id=s["id"],date=s["date"],n=len(items),urls=len(set(urls)),
            positions=len(set(positions)),range=f"{int(min(positions))}–{int(max(positions))}",ok=ok))
    return overall,snaps,daily,cumulative,postlist,quality

def table(headers, rows):
    h="<div class='tablewrap'><table><thead><tr>"+"".join("<th>"+html.escape(str(x))+"</th>" for x in headers)+"</tr></thead><tbody>"
    for row in rows: h+="<tr>"+"".join("<td>"+str(x)+"</td>" for x in row)+"</tr>"
    return h+"</tbody></table></div>"

def make_html(result):
    o,snaps,daily,cum,posts,quality=result
    cards=[
      ("Observations",f"{o['n']:,}","Post appearances across all snapshots"),
      ("Snapshots",f"{o['snapshots']:,}","Top-20 feed captures"),
      ("Unique posts",f"{o['posts']:,}","Distinct post URLs"),
      ("Exact matches",fpct(o["exact"]),f"{o['exactn']:,} of {o['n']:,} observations"),
      ("Mean absolute error",fnum(o["mae"],3),"Average positions away from predicted rank"),
      ("Median absolute error",fnum(o["median"],1),"Middle absolute rank difference"),
      ("Pooled Spearman",fnum(o["rho"],3),"Rank-order association"),
      ("Latest snapshot MAE",fnum(snaps[-1]["mae"],3),snaps[-1]["date"]+" · "+str(snaps[-1]["n"])+" posts")]
    cardhtml="".join(f"<article class='metric'><div class='muted'>{a}</div><div class='big'>{b}</div><small>{c}</small></article>" for a,b,c in cards)
    daily_t=table(["Date (MT)","Snapshots","Observations","Avg. exact match","Avg. MAE","Avg. median error","Avg. Spearman"],
      [[x["date"],x["n"],x["obs"],fpct(x["exact"]),fnum(x["mae"]),fnum(x["median"],1),fnum(x["rho"],3)] for x in reversed(daily)])
    cum_t=table(["Through date","Snapshots included","Observations","Cumulative exact match","Cumulative MAE","Median error","Pooled Spearman"],
      [[x["date"],x["count"],x["obs"],fpct(x["exact"]),fnum(x["mae"]),fnum(x["median"],1),fnum(x["rho"],3)] for x in reversed(cum)])
    snap_t=table(["Snapshot","Date (MT)","Posts","Exact match","Mean error","Median error","Spearman"],
      [[html.escape(str(x["id"])),x["date"],x["n"],fpct(x["exact"]),fnum(x["mae"]),fnum(x["median"],1),fnum(x["rho"],3)] for x in reversed(snaps)])
    postrows=[]
    for x in posts[:20]:
        title=html.escape(x["title"])
        if x["url"]: title=f"<a href='{html.escape(x['url'],quote=True)}' target='_blank' rel='noopener'>{title}</a>"
        postrows.append([title,x["n"],fnum(x["mae"]),fnum(x["maxerr"],0),fnum(x["votes"],1),fnum(x["actual"],1),fnum(x["pred"],1)])
    post_t=table(["Post","Appearances","Avg. absolute error","Max error","Avg. upvotes","Avg. actual rank","Avg. predicted rank"],postrows)
    quality_t=table(["Snapshot","Date (MT)","Rows","Unique URLs","Unique positions","Position range","Check"],
      [[html.escape(str(x["id"])),x["date"],x["n"],x["urls"],x["positions"],x["range"],"<b class='good'>PASS</b>" if x["ok"] else "<b class='bad'>CHECK</b>"] for x in reversed(quality)])
    chartdata=json.dumps(dict(daily=daily,cumulative=cum,latest=[dict(actual=int(x["actual"]),pred=int(x["predicted"]),title=x["title"]) for x in snaps[-1]["items"]]),ensure_ascii=False).replace("</","<\\/")
    generated=datetime.now(MT).strftime("%b %d, %Y at %I:%M %p MT")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bear Blog Trending — Ranking Algorithm Analysis</title>
<meta name="description" content="Longitudinal analysis of Bear Blog Trending rankings compared with its published ranking formula.">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{{--bg:#f4f5f7;--panel:#fff;--ink:#202532;--muted:#687181;--line:#e3e6eb;--accent:#5b61d6;--green:#16845b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{background:#20202d;color:white;padding:38px max(24px,calc((100% - 1200px)/2)) 32px}}.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#c5c3dc;font-weight:700}}
h1{{font-size:clamp(28px,4vw,42px);line-height:1.12;margin:10px 0;letter-spacing:-.035em}}.sub{{color:#d4d3df;max-width:780px;margin:0}}.meta{{color:#b8b7c8;font-size:12px;margin-top:18px}}
main{{max-width:1200px;margin:28px auto 65px;padding:0 24px}}section{{margin-top:30px}}h2{{font-size:21px;margin:0;letter-spacing:-.02em}}.intro,.muted{{color:var(--muted);font-size:13px;margin:4px 0 13px}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}}.metric,.panel,.tablewrap{{background:white;border:1px solid var(--line);border-radius:13px;box-shadow:0 8px 28px #1920300e}}
.metric{{padding:17px;min-height:116px}}.big{{font-size:29px;font-weight:750;letter-spacing:-.04em;margin:7px 0 2px}}small{{color:var(--muted);font-size:11px}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.panel{{padding:18px}}.panel strong{{display:block;margin-bottom:12px}}canvas{{width:100%;height:250px}}
.tablewrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}}th{{background:#f8f9fb;color:#586174;font-size:10px;text-transform:uppercase;letter-spacing:.06em}}tr:last-child td{{border:0}}tbody tr:hover{{background:#fafaff}}a{{color:#4e57c9;text-decoration:none}}a:hover{{text-decoration:underline}}.good{{color:var(--green)}}.bad{{color:#bd4b4b}}
.defs{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.def,.note{{background:white;border:1px solid var(--line);border-radius:10px;padding:14px 16px;color:var(--muted);font-size:13px}}.def b{{display:block;color:var(--ink);margin-bottom:3px}}.note{{margin-top:13px;border-left:3px solid var(--accent);border-radius:0 10px 10px 0}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding-top:28px}}
@media(max-width:800px){{.grid{{grid-template-columns:repeat(2,1fr)}}.charts{{grid-template-columns:1fr}}}}@media(max-width:520px){{main{{padding:0 14px}}header{{padding:28px 18px}}.defs{{grid-template-columns:1fr}}.metric{{padding:13px}}.big{{font-size:23px}}}}
</style></head><body>
<header><div class="eyebrow">Longitudinal monitoring · INFO 4617</div>
<h1>Bear Blog Trending:<br>Ranking Algorithm Analysis</h1>
<p class="sub">How closely does Bear Blog’s published ranking formula predict the ordering of posts in its Trending feed over time?</p>
<div class="meta">Data: {o["first"]} – {o["last"]} (Mountain Time) · Generated {generated} · Collection remains ongoing</div></header>
<main>
<section><h2>At a glance</h2><p class="intro">All collected post appearances; repeated appearances are counted again.</p><div class="grid">{cardhtml}</div></section>
<section><h2>Performance over time</h2><p class="intro">Daily snapshot averages and cumulative results as observations accumulate.</p><div class="charts">
<div class="panel"><strong>Daily average ranking error</strong><canvas id="d1"></canvas></div>
<div class="panel"><strong>Daily exact-match rate</strong><canvas id="d2"></canvas></div>
<div class="panel"><strong>Cumulative mean absolute error</strong><canvas id="d3"></canvas></div>
<div class="panel"><strong>Latest snapshot: actual vs. predicted position</strong><canvas id="d4"></canvas></div>
</div></section>
<section><h2>Daily performance</h2><p class="intro">Each date averages the snapshots collected on that Mountain Time calendar day.</p>{daily_t}</section>
<section><h2>Cumulative performance</h2><p class="intro">Pooled observations from the first snapshot through each successive snapshot.</p>{cum_t}</section>
<section><h2>Snapshot-by-snapshot results</h2><p class="intro">Individual captures of the Trending feed, newest first.</p>{snap_t}</section>
<section><h2>Posts with the largest discrepancies</h2><p class="intro">Posts ranked by average absolute difference between predicted and observed position.</p>{post_t}</section>
<section><h2>Data quality checks</h2><p class="intro">Checks for duplicate URLs or positions within each snapshot.</p>{quality_t}</section>
<section><h2>How to read the results</h2><p class="intro">Metric definitions and interpretation notes.</p><div class="defs">
<div class="def"><b>Exact-match rate</b>Percentage of observed posts for which predicted position equals actual Trending position.</div>
<div class="def"><b>Mean absolute error (MAE)</b>Average number of ranking positions separating predicted and actual positions. Lower is better.</div>
<div class="def"><b>Median absolute error</b>Middle absolute rank difference; less affected by unusually large mismatches.</div>
<div class="def"><b>Spearman correlation</b>Measures association between predicted and actual ordering. Values closer to 1 indicate stronger positive rank-order association.</div></div>
<div class="note"><b>Interpretation caution.</b> Pooled metrics count each post appearance, including repeat appearances across snapshots. These observations are therefore not statistically independent. Daily averages give each snapshot equal weight within its day. Predictive agreement does not establish that the published formula is the only factor determining Trending order.</div></section>
<footer>Automatically generated from ranking_observations.csv · Raw collection data is not modified.</footer>
</main>
<script>
const D={chartdata};
const common={{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{color:'#596273'}}}}}},scales:{{x:{{ticks:{{color:'#737b8b'}},grid:{{color:'#64708a1c'}}}},y:{{ticks:{{color:'#737b8b'}},grid:{{color:'#64708a1c'}}}}}}}};
function line(id,labels,values,label,color,extra={{}}){{new Chart(document.getElementById(id),{{type:'line',data:{{labels,datasets:[{{label,data:values,borderColor:color,backgroundColor:color+'22',fill:true,tension:.25,pointRadius:3}}]}},options:{{...common,...extra}}}})}}
line('d1',D.daily.map(x=>x.date),D.daily.map(x=>x.mae),'Mean absolute error','#5b61d6');
line('d2',D.daily.map(x=>x.date),D.daily.map(x=>x.exact),'Exact-match rate (%)','#16845b');
line('d3',D.cumulative.map(x=>'#'+x.count),D.cumulative.map(x=>x.mae),'Cumulative MAE','#8d72d6');
new Chart(document.getElementById('d4'),{{type:'line',data:{{labels:D.latest.map(x=>'#'+x.actual),datasets:[{{label:'Actual',data:D.latest.map(x=>x.actual),borderColor:'#16845b'}},{{label:'Predicted',data:D.latest.map(x=>x.pred),borderColor:'#5b61d6'}}]}},options:{{...common,scales:{{...common.scales,y:{{...common.scales.y,reverse:true,min:1}}}},plugins:{{tooltip:{{callbacks:{{title:items=>D.latest[items[0].dataIndex]?.title||items[0].label}}}}}}}}}});
</script></body></html>'''

def main():
    rows=read_data()
    result=analyze(rows)
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(make_html(result),encoding="utf-8")
    o=result[0]
    print(f"Created {DEST}")
    print(f"{o['snapshots']} snapshots · {o['n']} observations · {o['posts']} unique posts · MAE {o['mae']:.3f}")

if __name__=="__main__":
    main()
