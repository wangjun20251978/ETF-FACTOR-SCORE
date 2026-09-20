#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 多因子增强打分看板生成器
A股口径 8 因子横截面打分:
  F1 动量20日(↑,25) F2 动量60日(↑,20) F3 趋势排列(↑,15) F4 位置突破(↑,10)
  F5 短期反转(↓,10) F6 低波动(↓,10)  F7 量能配比(↑,5)  F8 乖离保护(↓,5)
数据源: 新浪财经日K公开接口 (与 ETF-ROTATION-PRO 同源)
输出: docs/index.html (单文件看板, 含个股打分面板) + docs/factors.json
本地用法: python etf_factor_score.py
GitHub Actions 每日 15:35(北京时间) 自动运行
"""
import json
import os
import time
import datetime
import urllib.request
import urllib.error
import math

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")

# ===================== 参数区 (可改) =====================
# 权重按 A 股市场有效性排序: 反转/低波/乖离等 A 股特色因子在前且权重大,
# 动量(中期>短期)、趋势次之, 量能配比垫底。元组: (显示ID, 名称, 方向, 权重, 原始因子键)
WEIGHTS = [
    ("F1", "短期反转", "down", 20, "f5"),
    ("F2", "低波动", "down", 15, "f6"),
    ("F3", "动量60日", "up", 15, "f2"),
    ("F4", "动量20日", "up", 15, "f1"),
    ("F5", "趋势排列", "up", 10, "f3"),
    ("F6", "位置突破", "up", 10, "f4"),
    ("F7", "乖离保护", "down", 10, "f8"),
    ("F8", "量能配比", "up", 5, "f7"),
]
MARKET_INDEX = "sh000001"

ETFS = [
    ("sz159915", "创业板"), ("sh510500", "中证500"), ("sh518880", "黄金ETF"),
    ("sh512100", "中证1000"), ("sh588000", "科创50"), ("sh516160", "新能源"),
    ("sh510300", "沪深300"), ("sh512480", "半导体"), ("sh512660", "军工"),
    ("sz159766", "旅游"), ("sh515050", "电信"), ("sh513100", "纳指ETF"),
    ("sz159981", "有色金属"), ("sh513500", "标普500"), ("sz159928", "消费"),
    ("sh513180", "恒生科技"), ("sh512690", "白酒"), ("sh512800", "银行"),
    ("sz159920", "恒生ETF"), ("sh512070", "证券"), ("sh512010", "医药"),
    ("sh510050", "上证50"), ("sh563300", "中证2000"), ("sz159901", "深证100"),
    ("sz159601", "MSCI中国A50"),
    ("sh515080", "中证红利"), ("sh512890", "红利低波"),
    ("sh515790", "光伏"), ("sh515220", "煤炭"), ("sh516150", "稀土"),
    ("sh515210", "钢铁"), ("sz159870", "化工"), ("sz159825", "农业"),
    ("sz159996", "家电"), ("sz159745", "建材"), ("sh516110", "汽车"),
    ("sh516950", "基建"), ("sz159611", "电力"),
    ("sh515980", "人工智能"), ("sh562500", "机器人"), ("sh515230", "软件"),
    ("sh512980", "传媒"),
    ("sh513520", "日经225"), ("sh513030", "德国DAX"), ("sh513080", "法国CAC"),
    ("sz159985", "豆粕"), ("sh511260", "十年国债"), ("sh511090", "三十年国债"),
]

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


def fetch_kline(symbol, datalen=200, tries=5):
    """新浪财经日K线, 升序 [{day,open,high,low,close,volume}]"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d" % (symbol, datalen))
    last_err = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk")
            data = json.loads(raw)
            rows = [{"day": d["day"], "open": float(d["open"]), "high": float(d["high"]),
                     "low": float(d["low"]), "close": float(d["close"]),
                     "volume": float(d["volume"])} for d in data]
            if not rows:
                raise ValueError("空数据")
            rows.sort(key=lambda x: x["day"])
            return rows
        except Exception as e:  # 新浪偶发 456 限流, 退避重试
            last_err = e
            if attempt < tries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise last_err


def ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / float(n)


def pct_rank(v, arr):
    """v 在 arr(非None值)中的百分位 0-100"""
    vals = [x for x in arr if x is not None]
    if v is None or not vals:
        return None
    if len(vals) == 1:
        return 50.0
    below = sum(1 for x in vals if x < v)
    return below / float(len(vals) - 1) * 100.0


def compute_raw(k):
    """单只ETF的8个因子原始值"""
    closes = [r["close"] for r in k]
    vols = [r["volume"] for r in k]
    highs = [r["high"] for r in k]
    lows = [r["low"] for r in k]
    n = len(closes)
    c = closes[-1]
    out = {"price": c}
    # 日涨跌
    out["chg1d"] = (c / closes[-2] - 1) * 100 if n >= 2 else None
    # F1 动量20
    out["f1"] = (c / closes[-21] - 1) * 100 if n >= 21 else None
    # F2 动量60
    out["f2"] = (c / closes[-61] - 1) * 100 if n >= 61 else None
    # F3 趋势排列: 收盘>MA20, MA20>MA60, MA60>MA120 各1分
    m20, m60, m120 = ma(closes, 20), ma(closes, 60), ma(closes, 120)
    pts, mx = 0, 0
    if m20 is not None:
        pts += 1 if c > m20 else 0
        mx += 1
    if m20 is not None and m60 is not None:
        pts += 1 if m20 > m60 else 0
        mx += 1
    if m60 is not None and m120 is not None:
        pts += 1 if m60 > m120 else 0
        mx += 1
    out["f3"] = pts / float(mx) * 100 if mx else None
    out["_ma20"] = m20
    # F4 位置突破: 收盘在120日高低区间的位置
    if n >= 20:
        hi, lo = max(highs[-120:]), min(lows[-120:])
        out["f4"] = (c - lo) / (hi - lo) * 100 if hi > lo else 50.0
    else:
        out["f4"] = None
    # F5 短期反转: 5日收益(方向↓)
    out["f5"] = (c / closes[-6] - 1) * 100 if n >= 6 else None
    # F6 低波动: 20日日收益标准差(方向↓)
    if n >= 21:
        rets = [(closes[i] / closes[i - 1] - 1) for i in range(n - 20, n)]
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / len(rets)
        out["f6"] = math.sqrt(var) * 100
    else:
        out["f6"] = None
    # F7 量能配比: 5日均量/60日均量, 上限3
    if n >= 61:
        ratio = sum(vols[-5:]) / 5.0 / (sum(vols[-60:]) / 60.0)
        out["f7"] = min(ratio, 3.0) if ratio > 0 else None
    else:
        out["f7"] = None
    # F8 乖离保护: 收盘/MA20-1(方向↓)
    out["f8"] = (c / m20 - 1) * 100 if m20 else None
    return out


def market_timing():
    """大盘择时: 上证综指 MA20/MA60"""
    try:
        k = fetch_kline(MARKET_INDEX, datalen=130)
        closes = [r["close"] for r in k]
        c = closes[-1]
        m20, m60 = ma(closes, 20), ma(closes, 60)
        if c > m20 > m60:
            return {"tag": "强势", "pos": "建议总仓位 80~100%", "cls": "bull",
                    "detail": "收盘 %.2f > MA20 %.2f > MA60 %.2f, 多头排列" % (c, m20, m60)}
        if c > m20 or c > m60:
            return {"tag": "中性", "pos": "建议总仓位 40~60%", "cls": "neutral",
                    "detail": "收盘 %.2f, MA20 %.2f, MA60 %.2f, 震荡市控制节奏" % (c, m20, m60)}
        return {"tag": "弱势", "pos": "建议总仓位 0~20%", "cls": "bear",
                "detail": "收盘 %.2f 跌破 MA20 %.2f / MA60 %.2f, 防御为主" % (c, m20, m60)}
    except Exception as e:
        return {"tag": "未知", "pos": "择时数据获取失败", "cls": "neutral", "detail": str(e)[:80]}


def main():
    os.makedirs(DOCS, exist_ok=True)
    raws, fails = [], []
    results = {}
    failed_pairs = []
    for code, name in ETFS:
        try:
            results[code] = fetch_kline(code, datalen=200)
        except Exception:
            failed_pairs.append((code, name))
        time.sleep(0.3)
    # 456 限流二次补抓: 停 5 秒让限流窗口过去, 再逐只慢速重试
    if failed_pairs:
        time.sleep(5)
        still = []
        for code, name in failed_pairs:
            try:
                results[code] = fetch_kline(code, datalen=200, tries=3)
            except Exception:
                still.append((code, name))
            time.sleep(1.0)
        failed_pairs = still
    for code, name in ETFS:
        if code not in results:
            fails.append("%s %s: 抓取失败" % (code, name))
            continue
        r = compute_raw(results[code])
        r["code"], r["name"] = code, name
        raws.append(r)

    # 横截面百分位 -> 加权综合分
    keymap = []
    for w in WEIGHTS:
        if w[4] not in keymap:
            keymap.append(w[4])
    cols = {k: [r.get(k) for r in raws] for k in keymap}
    for r in raws:
        total, wsum = 0.0, 0.0
        scores = {}
        for fid, _dn, d, w, rk in WEIGHTS:
            p = pct_rank(r.get(rk), cols[rk])
            if p is None:
                scores[fid] = None
                continue
            sc = 100.0 - p if d == "down" else p
            scores[fid] = round(sc, 1)
            total += sc * w
            wsum += w
        r["scores"] = scores
        r["total"] = round(total / wsum, 1) if wsum else None
        t = r["total"]
        r["signal"] = ("强势·可买" if t >= 75 else "持有·关注" if t >= 60
                       else "观察" if t >= 45 else "回避") if t is not None else "—"

    raws.sort(key=lambda x: -(x["total"] or -1))
    mt = market_timing()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    payload = {"updated": now, "market": mt, "fails": fails, "rows": raws, "weights": WEIGHTS}
    with open(os.path.join(DOCS, "factors.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    html = TEMPLATE
    html = html.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    html = html.replace("__WEIGHTS_JSON__", json.dumps(WEIGHTS, ensure_ascii=False))
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print("updated:", now)
    print("ok=%d fail=%d" % (len(raws), len(fails)))
    for s in fails:
        print("FAIL", s)
    print("top5:", [(r["name"], r["total"]) for r in raws[:5]])


# ===================== HTML 模板 (token 替换, 避免 % 转义坑) =====================
TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ETF多因子增强打分 | A股口径8因子</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--bd:#30363d;--tx:#e6edf3;--tx2:#8b949e;
--r:#f85149;--g:#3fb950;--a:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding-bottom:48px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--tx2);font-size:12px;margin-bottom:14px}
.chip{display:inline-block;background:var(--panel);border:1px solid var(--bd);border-radius:6px;padding:2px 10px;margin:2px 4px 2px 0;font-size:12px;color:var(--tx2)}
.chip b{color:var(--tx);font-weight:500}
.mt{border-radius:10px;border:1px solid var(--bd);padding:12px 16px;margin:14px 0;display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline}
.mt .tag{font-size:16px;font-weight:600}
.mt.bull .tag{color:var(--r)}.mt.neutral .tag{color:var(--a)}.mt.bear .tag{color:var(--g)}
.mt .pos{font-size:13px}.mt .det{color:var(--tx2);font-size:12px;width:100%}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{border-bottom:1px solid var(--bd);padding:7px 8px;text-align:center;white-space:nowrap}
th{color:var(--tx2);font-weight:500;background:var(--panel);cursor:pointer;position:sticky;top:0}
td.l{text-align:left}
.pos{color:var(--r)}.neg{color:var(--g)}.flat{color:var(--tx2)}
.scorebar{display:inline-block;width:64px;height:8px;background:#21262d;border-radius:4px;vertical-align:middle;margin-left:6px;overflow:hidden}
.scorebar i{display:block;height:100%;border-radius:4px}
.fs{display:inline-block;min-width:34px;border-radius:4px;padding:1px 4px;font-size:12px}
.sig{border-radius:5px;padding:1px 8px;font-size:12px;border:1px solid var(--bd)}
.s1{color:var(--r);border-color:var(--r)}.s2{color:#ffb347;border-color:#ffb347}
.s3{color:var(--tx2)}.s4{color:var(--g);border-color:var(--g)}
.panel{border:1px solid var(--bd);border-radius:10px;background:var(--panel);padding:16px;margin-top:22px}
.panel h2{font-size:15px;margin:0 0 10px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text]{background:#0d1117;border:1px solid var(--bd);border-radius:6px;color:var(--tx);padding:8px 10px;font-size:14px;width:180px}
button{background:#21262d;border:1px solid #444c56;border-radius:6px;color:var(--tx);padding:8px 16px;font-size:14px;cursor:pointer}
button:hover{background:#30363d}
.hint{color:var(--tx2);font-size:12px}
#stkResult{margin-top:14px;display:none}
.fbar{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12px}
.fbar .n{width:110px;color:var(--tx2)}
.fbar .bar{flex:1;height:8px;background:#21262d;border-radius:4px;overflow:hidden}
.fbar .bar i{display:block;height:100%}
.fbar .v{width:40px;text-align:right}
.warn{background:#3d2e00;border:1px solid #9e6a03;color:#d29922;border-radius:8px;padding:8px 12px;font-size:12px;margin-top:10px;display:none}
.foot{color:var(--tx2);font-size:12px;margin-top:24px;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
<h1>ETF 多因子增强打分</h1>
<div class="sub">A股口径 8 因子(按A股有效性排序加权) · 横截面排名打分 · 数据源: 新浪财经日K · 更新: <span id="upd">—</span></div>
<div id="chips"></div>
<div id="mt" class="mt"></div>
<div id="banner"></div>
<div style="overflow-x:auto">
<table id="tb">
<thead id="thead"><tr></tr></thead>
<tbody></tbody>
</table>
</div>

<div class="panel">
<h2>个股 / 任意ETF 实时打分</h2>
<div class="row">
<input type="text" id="code" placeholder="6位代码, 如 600519 / 510300" maxlength="8">
<button onclick="scoreStock()">打分</button>
<span class="hint">支持沪深A股、ETF；盘中输入即为最新价口径</span>
</div>
<div id="stkErr" class="warn"></div>
<div id="stkResult"></div>
<div class="hint" style="margin-top:8px">说明: ETF榜单为48只横截面排名打分；个股为单标的经验映射打分(同一套因子与权重, 分位换算口径不同), 供快照参考。</div>
</div>

<div class="foot">
因子口径(按A股有效性排序): F1 近5日涨幅反转(反向, A股散户市最强) · F2 20日波动率(反向, 低波占优) ·
F3/F4 动量60/20日(越强越好, 中期动量比短期稳) · F5 收盘与均线多头排列 · F6 收盘在120日区间位置 ·
F7 相对MA20乖离(反向, 反转家族防追高) · F8 5日均量/60日均量(温和放量加分)。<br>
信号档位: 综合分 ≥75 强势·可买 | 60-75 持有·关注 | 45-60 观察 | &lt;45 回避。<br>
本页面为量化工具输出, 不构成投资建议; 历史规律可能失效, 仓位与止损纪律优先。配套看板:
<a href="https://wangjun20251978.github.io/ETF-ROTATION-PRO/" style="color:#58a6ff">三因子轮动看板</a>
</div>
</div>
<script>
var DATA=__DATA__;
var WEIGHTS=__WEIGHTS_JSON__;
var WMAP={};WEIGHTS.forEach(function(w){WMAP[w[0]]=w});
function esc(s){return String(s).replace(/[&<>]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})}
function fmt(v,d){return v===null||v===undefined?"—":Number(v).toFixed(d===undefined?2:d)}
function sgn(v){if(v===null||v===undefined)return '<span class="flat">—</span>';return '<span class="'+(v>=0?"pos":"neg")+'">'+(v>=0?"+":"")+v.toFixed(2)+"%</span>"}
function heat(v){if(v===null||v===undefined)return '<span class="flat">—</span>';var a=0.12+0.78*(v/100);return '<span class="fs" style="background:rgba(248,81,73,'+a.toFixed(2)+');color:'+(v>=60?"#ffd6d3":"#e6edf3")+'">'+v.toFixed(0)+"</span>"}
function sigCls(t){return t>=75?"s1":t>=60?"s2":t>=45?"s3":"s4"}
function scoreColor(t){return t>=75?"#f85149":t>=60?"#d29922":t>=45?"#8b949e":"#3fb950"}

function buildHead(){
  var base=[["idx","#"],["name","名称"],["price","现价"],["chg1d","日涨跌"],["total","综合分"]];
  var h="";
  base.forEach(function(c){h+='<th data-k="'+c[0]+'">'+c[1]+"</th>"});
  WEIGHTS.forEach(function(w){h+='<th data-k="'+w[0]+'">'+w[0]+w[1]+"</th>"});
  h+='<th data-k="signal">信号</th>';
  document.querySelector("#thead tr").innerHTML=h;
}
function render(){
  buildHead();
  document.getElementById("upd").textContent=DATA.updated||"—";
  var chips="";
  WEIGHTS.forEach(function(w){
    chips+='<span class="chip"><b>'+w[0]+" "+w[1]+'</b> '+(w[2]==="up"?"↑":"↓")+" 权重"+w[3]+"</span>";
  });
  document.getElementById("chips").innerHTML=chips;
  var m=DATA.market||{};
  document.getElementById("mt").innerHTML='<span class="tag">大盘择时: '+esc(m.tag||"—")+'</span><span class="pos">'+esc(m.pos||"")+'</span><span class="det">'+esc(m.detail||"")+"</span>";
  document.getElementById("mt").className="mt "+(m.cls||"neutral");
  if(DATA.fails&&DATA.fails.length){
    document.getElementById("banner").innerHTML='<div class="warn" style="display:block">今日有 '+DATA.fails.length+' 只数据获取失败: '+esc(DATA.fails.join("；"))+"</div>";
  }
  draw(DATA.rows||[]);
}
var sortK="total",sortAsc=false;
function draw(rows){
  var tb=document.querySelector("#tb tbody");
  var rs=rows.slice();
  rs.sort(function(a,b){
    var va,vb;
    if(sortK==="idx"){va=rows.indexOf(a);vb=rows.indexOf(b)}
    else if(sortK==="name"||sortK==="signal"){va=a[sortK];vb=b[sortK]}
    else{va=a[sortK];vb=b[sortK];if(va===null||va===undefined)va=-1e9;if(vb===null||vb===undefined)vb=-1e9}
    if(typeof va==="string")return sortAsc?va.localeCompare(vb):vb.localeCompare(va);
    return sortAsc?va-vb:vb-va;
  });
  var h="";
  rs.forEach(function(r,i){
    h+="<tr><td>"+(i+1)+'</td><td class="l"><b>'+esc(r.name)+"</b> <span class='flat'>"+r.code+"</span></td>";
    h+="<td>"+fmt(r.price)+"</td><td>"+sgn(r.chg1d)+"</td>";
    h+='<td><b style="color:'+scoreColor(r.total)+'">'+fmt(r.total,1)+'</b><span class="scorebar"><i style="width:'+(r.total||0)+"%;background:"+scoreColor(r.total)+'"></i></span></td>';
    WEIGHTS.forEach(function(w){h+="<td>"+heat(r.scores?r.scores[w[0]]:null)+"</td>"});
    h+='<td><span class="sig '+sigCls(r.total||0)+'">'+esc(r.signal||"—")+"</span></td></tr>";
  });
  tb.innerHTML=h;
}
document.getElementById("thead").addEventListener("click",function(e){
  var th=e.target.closest("th");
  if(!th)return;
  var k=th.dataset.k;
  if(sortK===k)sortAsc=!sortAsc;else{sortK=k;sortAsc=false}
  draw(DATA.rows||[]);
});

/* ===================== 个股实时打分 (东方财富 JSONP) ===================== */
function clamp(v,a,b){return Math.max(a,Math.min(b,v))}
function lin(v,lo,hi){return clamp((v-lo)/(hi-lo)*100,0,100)}
function absScores(closes,vols){
  var n=closes.length,c=closes[n-1],out={};
  var ret20=n>=21?(c/closes[n-21]-1)*100:null;
  var ret60=n>=61?(c/closes[n-61]-1)*100:null;
  var ret5=n>=6?(c/closes[n-6]-1)*100:null;
  function ma(nn){if(n<nn)return null;var s=0;for(var i=n-nn;i<n;i++)s+=closes[i];return s/nn}
  var m20=ma(20),m60=ma(60),m120=ma(120);
  var pts=0,mx=0;
  if(m20!==null){pts+=c>m20?1:0;mx++}
  if(m20!==null&&m60!==null){pts+=m20>m60?1:0;mx++}
  if(m60!==null&&m120!==null){pts+=m60>m120?1:0;mx++}
  var vol20=null;
  if(n>=21){var s=0,s2=0;for(var i=n-20;i<n;i++){var rr=closes[i]/closes[i-1]-1;s+=rr;s2+=rr*rr}var mu=s/20;vol20=Math.sqrt(Math.max(s2/20-mu*mu,0))*100}
  var vr=null;if(n>=61){var s5=0,s60=0;for(var i=n-5;i<n;i++)s5+=vols[i];for(var i=n-60;i<n;i++)s60+=vols[i];vr=s60>0?(s5/5)/(s60/60):null}
  out.raw={ret20:ret20,ret60:ret60,ret5:ret5,pts:pts,mx:mx,vol20:vol20,vr:vr,bias:m20?(c/m20-1)*100:null};
  out.s={};
  out.s.f1=ret20===null?null:lin(ret20,-20,20);
  out.s.f2=ret60===null?null:lin(ret60,-30,30);
  out.s.f3=mx?pts/mx*100:null;
  var hi=-1e9,lo=1e9;for(var i=Math.max(0,n-120);i<n;i++){hi=Math.max(hi,closes[i]);lo=Math.min(lo,closes[i])}
  out.s.f4=hi>lo?(c-lo)/(hi-lo)*100:50;
  out.raw.pos=hi>lo?(c-lo)/(hi-lo)*100:50;
  out.s.f5=ret5===null?null:clamp(50-ret5*10,0,100);
  out.s.f6=vol20===null?null:clamp(100-vol20*20,0,100);
  out.s.f7=vr===null?null:lin(Math.min(vr,3),0.3,2.5);
  out.s.f8=out.raw.bias===null?null:clamp(60-out.raw.bias*5,0,100);
  var t=0,w=0;WEIGHTS.forEach(function(x){var sv=out.s[x[4]];if(sv!==null&&sv!==undefined){t+=sv*x[3];w+=x[3]}});
  out.total=w?Math.round(t/w*10)/10:null;
  return out;
}
function secid(code){
  if(/^sh/i.test(code))return "1."+code.replace(/^sh/i,"");
  if(/^sz/i.test(code))return "0."+code.replace(/^sz/i,"");
  if(/^[569]/.test(code))return "1."+code;
  return "0."+code;
}
function fetchEM(secid,cb){
  var cbn="emcb"+Date.now();
  window[cbn]=function(res){cb(res)};
  var s=document.createElement("script");
  s.src="https://push2his.eastmoney.com/api/qt/stock/kline/get?secid="+secid+"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&end=20500101&lmt=260&cb="+cbn;
  s.onerror=function(){cb(null)};
  document.body.appendChild(s);
  setTimeout(function(){try{delete window[cbn]}catch(e){}if(s.parentNode)s.parentNode.removeChild(s)},15000);
}
function scoreStock(){
  var code=document.getElementById("code").value.trim();
  var err=document.getElementById("stkErr"),box=document.getElementById("stkResult");
  if(!/^([a-z]{2})?\\d{6}$/i.test(code)){err.style.display="block";err.textContent="请输入6位代码, 可带 sh/sz 前缀";box.style.display="none";return}
  err.style.display="none";box.style.display="none";
  fetchEM(secid(code),function(res){
    if(!res||!res.data||!res.data.klines||!res.data.klines.length){
      err.style.display="block";err.textContent="未取到行情数据, 请确认代码是否正确(北交所/退市股可能不支持)";return;
    }
    var closes=[],vols=[],lastDay="";
    res.data.klines.forEach(function(line){
      var p=line.split(",");
      lastDay=p[0];closes.push(parseFloat(p[2]));vols.push(parseFloat(p[5]));
    });
    var r=absScores(closes,vols);
    var t=r.total;
    var sig=t>=75?"强势·可买":t>=60?"持有·关注":t>=45?"观察":"回避";
    var h="<div style='font-size:15px'><b>"+esc(res.data.name)+"</b>("+esc(code)+") 现价 "+fmt(closes[closes.length-1]);
    h+=" <span class='flat'>截至 "+lastDay+" K线 "+closes.length+" 根</span></div>";
    h+="<div style='margin:8px 0'><b style='font-size:22px;color:"+scoreColor(t)+"'>"+fmt(t,1)+"</b> ";
    h+="<span class='sig "+sigCls(t||0)+"'>"+sig+"</span></div>";
    var RMAP={f1:"ret20",f2:"ret60",f4:"pos",f5:"ret5",f6:"vol20",f7:"vr",f8:"bias"};
    WEIGHTS.forEach(function(w){
      var v=r.s[w[4]];
      var raw="";
      if(w[4]==="f3"&&r.raw){raw=" "+r.raw.pts+"/"+r.raw.mx}
      else if(r.raw&&RMAP[w[4]]&&r.raw[RMAP[w[4]]]!==null&&r.raw[RMAP[w[4]]]!==undefined){
        var rv=r.raw[RMAP[w[4]]];
        raw=" "+(typeof rv==="number"?rv.toFixed(2):rv);
      }
      h+="<div class='fbar'><span class='n'>"+w[0]+" "+w[1]+(w[2]==="up"?" ↑":" ↓")+"×"+w[3]+"</span><div class='bar'><i style='width:"+(v||0)+"%;background:"+scoreColor(v||0)+"'></i></div><span class='v'>"+(v===null?"—":v.toFixed(0))+raw+"</span></div>";
    });
    h+="<div class='hint' style='margin-top:6px'>↑ 越高越好, ↓ 反向因子(已换算为越高越好)。个股为单标的经验映射口径。</div>";
    box.innerHTML=h;box.style.display="block";
  });
}
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
