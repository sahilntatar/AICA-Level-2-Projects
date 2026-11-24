# -*- coding: utf-8 -*-
"""
 ArthaDrishti (अर्थदृष्टि) — "the vision of wealth"
 WEB EDITION — desktop dashboard in your browser
 ICAI AI Level-2 Capstone · Investment Analysis Tool for Chartered Accountants
 ---------------------------------------------------------------------------
 What it does
   • Type a company name: live suggestions as you type (NSE master list)
   • 3 years of audited P&L, balance sheet and cash flow (Screener.in)
   • 20+ ratios, green/red flags, rule-based 6-axis scorecard
   • Peer face-off (e.g. Ambuja Cements vs UltraTech) + full peer universe
   • AGM/EGM & exchange disclosures auto-classified; news with sentiment
   • Annual-report PDF deep scan: KAMs, capex, contingent liabilities, RPTs, outlook
   • Industry analysis: drivers, KPIs, tailwinds/headwinds, CA audit lens, live pulse
 How to run
   Double-click this file (Python 3.9+ on Windows). Missing packages
   (requests, beautifulsoup4, pypdf) are installed automatically on first run.
 Note
   Analytical aid only; the investment decision rests with the professional.
"""
# =====================================================================
#  ArthaDrishti  (अर्थदृष्टि)  —  analysis engine
#  Shared by the web and mobile launchers.
# =====================================================================
import os, sys, re, json, time, math, threading, statistics, io, hashlib, logging, traceback, subprocess
from datetime import datetime
from urllib.parse import quote_plus, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET

APP_NAME = "ArthaDrishti"
APP_DEVANAGARI = "अर्थदृष्टि"
APP_TAGLINE = "Audited insight, at a glance"
APP_VERSION = "1.0"

HOME = os.path.join(os.path.expanduser("~"), ".arthadrishti")
CACHE_DIR = os.path.join(HOME, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
logging.basicConfig(filename=os.path.join(HOME, "arthadrishti.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(APP_NAME)

SCREENER = "https://www.screener.in"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

# ---------------------------------------------------------------------
#  Dependency bootstrap (pip-installs missing packages on first run)
# ---------------------------------------------------------------------
REQUIRED = {"requests": "requests", "bs4": "beautifulsoup4"}
OPTIONAL = {"pypdf": "pypdf"}


def _missing(mods):
    import importlib.util
    return [pkg for mod, pkg in mods.items() if importlib.util.find_spec(mod) is None]


def ensure_dependencies(extra=None):
    """Install missing packages silently. Returns list of packages that still failed."""
    mods = dict(REQUIRED); mods.update(OPTIONAL); mods.update(extra or {})
    missing = _missing(mods)
    if not missing:
        return []
    win = None
    try:
        import tkinter as tk
        win = tk.Tk(); win.title(APP_NAME); win.geometry("420x120"); win.configure(bg="#0E1B33")
        tk.Label(win, text=f"{APP_NAME} — first-run setup", fg="#E8A33D", bg="#0E1B33",
                 font=("Segoe UI", 13, "bold")).pack(pady=(18, 4))
        tk.Label(win, text="Installing: " + ", ".join(missing), fg="white", bg="#0E1B33",
                 font=("Segoe UI", 10)).pack()
        win.update()
    except Exception:
        win = None
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        alt = py[:-11] + "python.exe"
        if os.path.exists(alt):
            py = alt
    for pkg in missing:
        try:
            in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
            subprocess.run([py, "-m", "pip", "install", "--quiet"] + ([] if in_venv else ["--user"]) + [pkg],
                           creationflags=flags, timeout=600)
        except Exception as e:
            log.error("pip install %s failed: %s", pkg, e)
    if win:
        try: win.destroy()
        except Exception: pass
    import importlib, site
    importlib.invalidate_caches()
    try:
        up = site.getusersitepackages()
        if up not in sys.path: sys.path.append(up)
    except Exception:
        pass
    return _missing(mods)


_session = None
def S():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers.update(BROWSER_HEADERS)
    return _session


def http_get(url, timeout=20, **kw):
    last = None
    for attempt in range(2):
        try:
            r = S().get(url, timeout=timeout, **kw)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2); continue
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(0.8)
    raise last

# ---------------------------------------------------------------------
#  Disk cache
# ---------------------------------------------------------------------
def _ck(key): return os.path.join(CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".json")

def cache_get(key, ttl):
    p = _ck(key)
    if not os.path.exists(p): return None, False
    try:
        with open(p, "r", encoding="utf-8") as f: obj = json.load(f)
        return obj["data"], (time.time() - obj["ts"]) < ttl
    except Exception:
        return None, False

def cache_put(key, data):
    try:
        with open(_ck(key), "w", encoding="utf-8") as f: json.dump({"ts": time.time(), "data": data}, f)
    except Exception as e:
        log.warning("cache write failed %s", e)

# ---------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------
def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()

def num(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    t = clean(str(s)).replace(",", "").replace("₹", "").replace("%", "").replace("Cr.", "").strip()
    if t in ("", "-", "--", "—", "NA", "N/A"): return None
    try: return float(t)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", t)
        return float(m.group()) if m else None

def safe_div(a, b):
    try:
        if a is None or b in (None, 0): return None
        return a / b
    except Exception:
        return None

def pct(a, b):
    v = safe_div(a, b); return None if v is None else v * 100

def growth(new, old):
    if new is None or old in (None, 0) or old < 0: return None
    return (new / old - 1) * 100

def cagr(first, last, years):
    if first in (None, 0) or last is None or years <= 0 or first < 0 or last < 0: return None
    return ((last / first) ** (1 / years) - 1) * 100

def rnd(v, d=1):
    return None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else round(v, d)

def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

def fy_label(col):
    """'Mar 2025' -> 'FY25', 'Dec 2021' -> 'CY21', 'TTM' stays."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", col or "")
    if not m: return col
    mon, yr = m.group(1).lower(), m.group(2)[2:]
    return ("FY" if mon in ("mar", "jun", "sep") else "CY") + yr

def month_index(col):
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", col or "")
    if not m: return None
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    try: return int(m.group(2)) * 12 + months.index(m.group(1).lower())
    except ValueError: return None

# ---------------------------------------------------------------------
#  Company master list (autocomplete)
# ---------------------------------------------------------------------
POPULAR = """RELIANCE|Reliance Industries Ltd
TCS|Tata Consultancy Services Ltd
HDFCBANK|HDFC Bank Ltd
ICICIBANK|ICICI Bank Ltd
INFY|Infosys Ltd
HINDUNILVR|Hindustan Unilever Ltd
ITC|ITC Ltd
SBIN|State Bank of India
BHARTIARTL|Bharti Airtel Ltd
KOTAKBANK|Kotak Mahindra Bank Ltd
LT|Larsen & Toubro Ltd
AXISBANK|Axis Bank Ltd
BAJFINANCE|Bajaj Finance Ltd
BAJAJFINSV|Bajaj Finserv Ltd
ASIANPAINT|Asian Paints Ltd
MARUTI|Maruti Suzuki India Ltd
HCLTECH|HCL Technologies Ltd
SUNPHARMA|Sun Pharmaceutical Industries Ltd
TITAN|Titan Company Ltd
ULTRACEMCO|UltraTech Cement Ltd
AMBUJACEM|Ambuja Cements Ltd
ACC|ACC Ltd
SHREECEM|Shree Cement Ltd
DALBHARAT|Dalmia Bharat Ltd
JKCEMENT|J K Cement Ltd
RAMCOCEM|The Ramco Cements Ltd
INDIACEM|The India Cements Ltd
NUVOCO|Nuvoco Vistas Corporation Ltd
BIRLACORPN|Birla Corporation Ltd
JKLAKSHMI|JK Lakshmi Cement Ltd
HEIDELBERG|HeidelbergCement India Ltd
STARCEMENT|Star Cement Ltd
ORIENTCEM|Orient Cement Ltd
SAGCEM|Sagar Cements Ltd
NESTLEIND|Nestle India Ltd
WIPRO|Wipro Ltd
TECHM|Tech Mahindra Ltd
LTIM|LTIMindtree Ltd
PERSISTENT|Persistent Systems Ltd
COFORGE|Coforge Ltd
MPHASIS|Mphasis Ltd
TATAELXSI|Tata Elxsi Ltd
KPITTECH|KPIT Technologies Ltd
OFSS|Oracle Financial Services Software Ltd
POWERGRID|Power Grid Corporation of India Ltd
NTPC|NTPC Ltd
ONGC|Oil & Natural Gas Corporation Ltd
COALINDIA|Coal India Ltd
TATASTEEL|Tata Steel Ltd
JSWSTEEL|JSW Steel Ltd
HINDALCO|Hindalco Industries Ltd
VEDL|Vedanta Ltd
HINDZINC|Hindustan Zinc Ltd
NMDC|NMDC Ltd
SAIL|Steel Authority of India Ltd
JINDALSTEL|Jindal Steel & Power Ltd
ADANIENT|Adani Enterprises Ltd
ADANIPORTS|Adani Ports and Special Economic Zone Ltd
ADANIGREEN|Adani Green Energy Ltd
ADANIPOWER|Adani Power Ltd
ADANIENSOL|Adani Energy Solutions Ltd
ATGL|Adani Total Gas Ltd
M&M|Mahindra & Mahindra Ltd
BAJAJ-AUTO|Bajaj Auto Ltd
HEROMOTOCO|Hero MotoCorp Ltd
EICHERMOT|Eicher Motors Ltd
TVSMOTOR|TVS Motor Company Ltd
ASHOKLEY|Ashok Leyland Ltd
BOSCHLTD|Bosch Ltd
MOTHERSON|Samvardhana Motherson International Ltd
BHARATFORG|Bharat Forge Ltd
MRF|MRF Ltd
APOLLOTYRE|Apollo Tyres Ltd
BALKRISIND|Balkrishna Industries Ltd
DRREDDY|Dr. Reddy's Laboratories Ltd
CIPLA|Cipla Ltd
DIVISLAB|Divi's Laboratories Ltd
LUPIN|Lupin Ltd
TORNTPHARM|Torrent Pharmaceuticals Ltd
ZYDUSLIFE|Zydus Lifesciences Ltd
AUROPHARMA|Aurobindo Pharma Ltd
ALKEM|Alkem Laboratories Ltd
BIOCON|Biocon Ltd
MANKIND|Mankind Pharma Ltd
APOLLOHOSP|Apollo Hospitals Enterprise Ltd
MAXHEALTH|Max Healthcare Institute Ltd
BRITANNIA|Britannia Industries Ltd
DABUR|Dabur India Ltd
MARICO|Marico Ltd
GODREJCP|Godrej Consumer Products Ltd
COLPAL|Colgate-Palmolive (India) Ltd
TATACONSUM|Tata Consumer Products Ltd
UNITDSPR|United Spirits Ltd
UBL|United Breweries Ltd
JUBLFOOD|Jubilant FoodWorks Ltd
PIDILITIND|Pidilite Industries Ltd
BERGEPAINT|Berger Paints India Ltd
HAVELLS|Havells India Ltd
POLYCAB|Polycab India Ltd
VOLTAS|Voltas Ltd
BLUESTARCO|Blue Star Ltd
DIXON|Dixon Technologies (India) Ltd
CROMPTON|Crompton Greaves Consumer Electricals Ltd
SIEMENS|Siemens Ltd
ABB|ABB India Ltd
CUMMINSIND|Cummins India Ltd
BEL|Bharat Electronics Ltd
HAL|Hindustan Aeronautics Ltd
BHEL|Bharat Heavy Electricals Ltd
IOC|Indian Oil Corporation Ltd
BPCL|Bharat Petroleum Corporation Ltd
HINDPETRO|Hindustan Petroleum Corporation Ltd
GAIL|GAIL (India) Ltd
PETRONET|Petronet LNG Ltd
IGL|Indraprastha Gas Ltd
TATAPOWER|Tata Power Company Ltd
JSWENERGY|JSW Energy Ltd
NHPC|NHPC Ltd
TORNTPOWER|Torrent Power Ltd
PFC|Power Finance Corporation Ltd
RECLTD|REC Ltd
IRFC|Indian Railway Finance Corporation Ltd
RVNL|Rail Vikas Nigam Ltd
CONCOR|Container Corporation of India Ltd
IRCTC|Indian Railway Catering & Tourism Corporation Ltd
DLF|DLF Ltd
GODREJPROP|Godrej Properties Ltd
OBEROIRLTY|Oberoi Realty Ltd
LODHA|Macrotech Developers Ltd
INDUSINDBK|IndusInd Bank Ltd
BANKBARODA|Bank of Baroda
PNB|Punjab National Bank
CANBK|Canara Bank
UNIONBANK|Union Bank of India
IDFCFIRSTB|IDFC First Bank Ltd
FEDERALBNK|The Federal Bank Ltd
AUBANK|AU Small Finance Bank Ltd
BANDHANBNK|Bandhan Bank Ltd
YESBANK|Yes Bank Ltd
SBILIFE|SBI Life Insurance Company Ltd
HDFCLIFE|HDFC Life Insurance Company Ltd
ICICIPRULI|ICICI Prudential Life Insurance Company Ltd
LICI|Life Insurance Corporation of India
SHRIRAMFIN|Shriram Finance Ltd
CHOLAFIN|Cholamandalam Investment and Finance Company Ltd
MUTHOOTFIN|Muthoot Finance Ltd
HDFCAMC|HDFC Asset Management Company Ltd
LICHSGFIN|LIC Housing Finance Ltd
NAUKRI|Info Edge (India) Ltd
ETERNAL|Eternal Ltd (Zomato)
PAYTM|One 97 Communications Ltd (Paytm)
NYKAA|FSN E-Commerce Ventures Ltd (Nykaa)
DMART|Avenue Supermarts Ltd (DMart)
TRENT|Trent Ltd
INDIGO|InterGlobe Aviation Ltd (IndiGo)
GRASIM|Grasim Industries Ltd
UPL|UPL Ltd
SRF|SRF Ltd
PIIND|PI Industries Ltd
DEEPAKNTR|Deepak Nitrite Ltd
TATACHEM|Tata Chemicals Ltd
AARTIIND|Aarti Industries Ltd
PAGEIND|Page Industries Ltd
IDEA|Vodafone Idea Ltd
INDUSTOWER|Indus Towers Ltd
TATACOMM|Tata Communications Ltd"""

_master = None
_master_lock = threading.Lock()
POPULAR_SET = set()


def load_master():
    """Popular list (bundled) + full NSE equity list (downloaded once, cached 7 days)."""
    global _master
    with _master_lock:
        if _master is not None: return _master
        rows, seen = [], set()
        for line in POPULAR.splitlines():
            sym, name = line.split("|", 1)
            rows.append((sym.strip(), name.strip())); seen.add(sym.strip()); POPULAR_SET.add(sym.strip())
        data, fresh = cache_get("nse_master", 7 * 86400)
        if not fresh:
            try:
                r = http_get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=15)
                lines = r.text.splitlines()[1:]
                data = []
                for ln in lines:
                    parts = ln.split(",")
                    if len(parts) >= 2: data.append([parts[0].strip(), parts[1].strip()])
                if len(data) > 500: cache_put("nse_master", data)
            except Exception as e:
                log.warning("NSE master download failed: %s", e)
        for sym, name in (data or []):
            if sym not in seen:
                rows.append((sym, name.title().replace(" Ltd", " Ltd").replace("Limited", "Ltd"))); seen.add(sym)
        _master = rows
        return rows


def search_companies(q, limit=8):
    q = clean(q).lower()
    if not q: return []
    toks = q.split()
    out = []
    for sym, name in load_master():
        s, n = sym.lower(), name.lower()
        words = re.split(r"[\s\(\)&.\-]+", n)
        sc = 0
        if s == q: sc = 100
        elif n.startswith(q): sc = 88
        elif s.startswith(q): sc = 84
        elif any(w.startswith(q) for w in words): sc = 72
        elif all(any(w.startswith(t) for w in words) for t in toks): sc = 64
        elif q in n: sc = 50
        if sc:
            if sym in POPULAR_SET: sc += 8
            out.append((sc, len(n), sym, name))
    out.sort(key=lambda x: (-x[0], x[1]))
    return [{"symbol": o[2], "name": o[3], "url": f"/company/{o[2]}/consolidated/"} for o in out[:limit]]

# ---------------------------------------------------------------------
#  Screener.in page parser
# ---------------------------------------------------------------------
def _soup(html_text):
    from bs4 import BeautifulSoup
    try: return BeautifulSoup(html_text, "lxml")
    except Exception: return BeautifulSoup(html_text, "html.parser")


def parse_table(tbl):
    if tbl is None: return {"columns": [], "rows": []}
    head = tbl.find("thead")
    ths = head.find_all("th") if head else (tbl.find("tr").find_all("th") if tbl.find("tr") else [])
    cols = [clean(th.get_text(" ")) for th in ths][1:]
    rows = []
    body = tbl.find("tbody") or tbl
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2: continue
        label = clean(tds[0].get_text(" ")).replace("+", "").strip()
        if not label: continue
        rows.append({"label": label, "values": [num(td.get_text()) for td in tds[1:]]})
    return {"columns": cols, "rows": rows}


def _section_table(soup, sid):
    sec = soup.find("section", id=sid)
    if not sec: return {"columns": [], "rows": []}
    return parse_table(sec.select_one("table.data-table") or sec.find("table"))


def fetch_screener_page(url):
    if not url.startswith("http"): url = SCREENER + url
    return http_get(url, timeout=25).text


def parse_company_html(html_text, url):
    soup = _soup(html_text)
    d = {"url": url, "fetched_at": datetime.now().strftime("%d %b %Y, %I:%M %p")}
    h1 = soup.find("h1")
    d["name"] = clean(h1.get_text()) if h1 else ""
    about = soup.select_one(".company-profile .about p") or soup.select_one(".about p") or soup.select_one(".about")
    d["about"] = clean(about.get_text(" ")) if about else ""
    kp = soup.select_one(".company-profile .commentary") or soup.select_one(".commentary")
    d["key_points"] = clean(kp.get_text(" "))[:900] if kp else ""

    # top ratios
    tr = {}
    for li in soup.select("#top-ratios li"):
        nm = li.select_one(".name"); val = li.select_one(".value")
        if not nm: continue
        nums = [num(x.get_text()) for x in li.select(".number")]
        tr[clean(nm.get_text())] = {"text": clean(val.get_text(" ")) if val else "", "nums": nums}
    d["top_ratios"] = tr

    d["pros"] = [clean(li.get_text(" ")) for li in soup.select(".pros li")]
    d["cons"] = [clean(li.get_text(" ")) for li in soup.select(".cons li")]

    # company links
    links = {}
    for a in soup.select(".company-links a, a[href*='bseindia.com'], a[href*='nseindia.com']"):
        href = a.get("href", ""); txt = clean(a.get_text(" "))
        if "bseindia" in href and "bse" not in links:
            m = re.search(r"(\d{6})", href + " " + txt)
            if m: links["bse"] = m.group(1)
        elif "nseindia" in href and "nse" not in links:
            m = re.search(r"symbol=([A-Z0-9&\-]+)", href) or re.search(r"NSE\s*:?\s*([A-Z0-9&\-]+)", txt)
            if m: links["nse"] = m.group(1)
        elif href.startswith("http") and "website" not in links and "screener" not in href \
                and "bseindia" not in href and "nseindia" not in href and a.find_parent(class_="company-links"):
            links["website"] = href
    d["links"] = links

    # sector path
    sector = [clean(a.get_text()) for a in soup.select("section#peers a[href*='/market/']")]
    if not sector:
        sector = [clean(a.get_text()) for a in soup.select("a[href*='/market/']")][:4]
    d["sector_path"] = [s for i, s in enumerate(sector) if s and s not in sector[:i]]

    # financial tables
    d["quarters"] = _section_table(soup, "quarters")
    d["pl"] = _section_table(soup, "profit-loss")
    d["bs"] = _section_table(soup, "balance-sheet")
    d["cf"] = _section_table(soup, "cash-flow")
    d["ratios"] = _section_table(soup, "ratios")

    # compounded growth ranges
    ranges = []
    sec = soup.find("section", id="profit-loss")
    if sec:
        for t in sec.select("table.ranges-table"):
            th = t.find("th"); title = clean(th.get_text()) if th else ""
            items = []
            for row in t.find_all("tr"):
                tds = row.find_all("td")
                if len(tds) == 2: items.append([clean(tds[0].get_text()).rstrip(":"), clean(tds[1].get_text())])
            if title: ranges.append({"title": title, "items": items})
    d["ranges"] = ranges

    # shareholding
    sh = soup.find("section", id="shareholding")
    if sh:
        t = sh.select_one("#quarterly-shp table") or sh.find("table")
        d["shareholding"] = parse_table(t)
    else:
        d["shareholding"] = {"columns": [], "rows": []}

    # ids for peers api
    ci = soup.select_one("#company-info")
    wid = ci.get("data-warehouse-id") if ci else None
    if not wid:
        m = re.search(r'data-warehouse-id="(\d+)"', html_text); wid = m.group(1) if m else None
    d["warehouse_id"] = wid

    d["documents"] = parse_documents(soup)
    return d


def parse_documents(soup):
    docs = {"announcements": [], "annual_reports": [], "concalls": [], "credit_ratings": []}
    sec = soup.find("section", id="documents")
    if not sec: return docs
    seen = set()
    for box in sec.select("div.documents"):
        h = box.find(["h3", "h2", "h4"]); title = clean(h.get_text()).lower() if h else ""
        if "announcement" in title:
            for li in box.select("li"):
                a = li.find("a")
                if not a or not a.get("href") or a["href"] in seen: continue
                seen.add(a["href"])
                sub = a.find("div"); subtxt = clean(sub.get_text(" ")) if sub else ""
                full = clean(a.get_text(" "))
                head = clean(full[: len(full) - len(subtxt)]) if subtxt and full.endswith(subtxt) else full
                docs["announcements"].append({"title": head, "detail": subtxt, "url": _abs(a["href"])})
        elif "annual" in title:
            for a in box.select("a"):
                if a.get("href"):
                    sub = a.find("div"); subtxt = clean(sub.get_text()) if sub else ""
                    t = clean(a.get_text(" ")); t = clean(t.replace(subtxt, "")) if subtxt else t
                    docs["annual_reports"].append({"title": t, "source": subtxt, "url": _abs(a["href"])})
        elif "credit" in title:
            for a in box.select("a"):
                if a.get("href"):
                    docs["credit_ratings"].append({"title": clean(a.get_text(" ")), "url": _abs(a["href"])})
        elif "concall" in title:
            for li in box.select("li"):
                date_div = li.find("div"); date = clean(date_div.get_text()) if date_div else ""
                items = []
                for a in li.find_all("a"):
                    if a.get("href"):
                        items.append({"type": clean(a.get_text()) or a.get("title", "Link"), "url": _abs(a["href"])})
                if items: docs["concalls"].append({"date": date, "links": items})
    return docs


def _abs(href):
    return href if href.startswith("http") else SCREENER + href


def fetch_peers(warehouse_id):
    if not warehouse_id: return []
    try:
        r = http_get(f"{SCREENER}/api/company/{warehouse_id}/peers/", timeout=20,
                     headers={"X-Requested-With": "XMLHttpRequest"})
        soup = _soup(r.text)
        tbl = soup.find("table")
        if not tbl: return []
        heads = [clean(th.get_text(" ")) for th in tbl.find_all("th")]
        out = []
        for tr in tbl.find_all("tr"):
            tds = tr.find_all("td")
            a = tr.find("a")
            if not tds or not a: continue
            row = {"name": clean(a.get_text()), "url": a.get("href", "")}
            for h, td in zip(heads, tds):
                key = _peer_key(h)
                if key and key != "name": row[key] = num(td.get_text())
            out.append(row)
        return out
    except Exception as e:
        log.warning("peers failed: %s", e)
        return []


def _peer_key(h):
    h = h.lower()
    if h.startswith("s.no"): return None
    if h.startswith("name"): return "name"
    if h.startswith("cmp"): return "cmp"
    if h.startswith("p/e"): return "pe"
    if h.startswith("mar cap"): return "mcap"
    if h.startswith("div yld"): return "div_yield"
    if h.startswith("np qtr"): return "np_qtr"
    if h.startswith("qtr profit var"): return "qtr_profit_var"
    if h.startswith("sales qtr"): return "sales_qtr"
    if h.startswith("qtr sales var"): return "qtr_sales_var"
    if h.startswith("roce"): return "roce"
    if h.startswith("roe"): return "roe"
    if h.startswith("p/b") or "price to book" in h: return "pb"
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


def get_company_raw(url, force=False):
    """Fetch + parse a company. Falls back to standalone if consolidated is empty, then to stale cache."""
    url = normalise_url(url)
    key = "co:" + url
    cached, fresh = cache_get(key, 6 * 3600)
    if cached and fresh and not force:
        cached["cache"] = "fresh"; return cached
    try:
        d = parse_company_html(fetch_screener_page(url), url)
        if not d["pl"]["rows"] and "/consolidated/" in url:
            alt = url.replace("consolidated/", "")
            d2 = parse_company_html(fetch_screener_page(alt), alt)
            if d2["pl"]["rows"]: d = d2
        if not d["pl"]["rows"]:
            raise RuntimeError("No financial statements found on the page")
        d["basis"] = "Consolidated" if "/consolidated/" in d["url"] else "Standalone"
        d["peers"] = fetch_peers(d.get("warehouse_id"))
        d["cache"] = "live"
        cache_put(key, d)
        return d
    except Exception as e:
        log.error("fetch %s failed: %s", url, traceback.format_exc())
        if cached:
            cached["cache"] = "stale"; cached["cache_note"] = f"Live fetch failed ({e}); showing last saved copy."
            return cached
        raise


def normalise_url(u):
    u = (u or "").strip()
    if u.startswith("http"): u = urlparse(u).path
    if not u.startswith("/company/"):
        u = f"/company/{u.upper()}/consolidated/"
    if not u.endswith("/"): u += "/"
    return u

# ---------------------------------------------------------------------
#  Financial model
# ---------------------------------------------------------------------
ALIASES = {
    "sales": ["sales", "revenue", "revenue from operations", "total income"],
    "expenses": ["expenses"],
    "op_profit": ["operating profit", "financing profit"],
    "opm": ["opm", "financing margin"],
    "other_income": ["other income"],
    "interest": ["interest"],
    "dep": ["depreciation"],
    "pbt": ["profit before tax"],
    "tax_pct": ["tax"],
    "np": ["net profit"],
    "eps": ["eps in rs", "eps"],
    "payout": ["dividend payout"],
    "equity": ["equity capital", "share capital"],
    "reserves": ["reserves"],
    "borrowings": ["borrowings", "borrowing"],
    "deposits": ["deposits"],
    "other_liab": ["other liabilities"],
    "total_liab": ["total liabilities"],
    "fixed_assets": ["fixed assets", "net block"],
    "cwip": ["cwip", "capital work in progress"],
    "investments": ["investments"],
    "other_assets": ["other assets"],
    "total_assets": ["total assets"],
    "cfo": ["cash from operating activity", "cash from operating activities"],
    "cfi": ["cash from investing activity", "cash from investing activities"],
    "cff": ["cash from financing activity", "cash from financing activities"],
    "net_cf": ["net cash flow"],
    "debtor_days": ["debtor days"],
    "inventory_days": ["inventory days"],
    "payable_days": ["days payable"],
    "ccc": ["cash conversion cycle"],
    "wc_days": ["working capital days"],
    "roce_s": ["roce"],
    "roe_s": ["roe"],
    "promoters": ["promoters"],
    "fii": ["fiis", "fii"],
    "dii": ["diis", "dii"],
    "govt": ["government"],
    "public": ["public"],
    "holders": ["no. of shareholders"],
}


def _norm_label(s): return re.sub(r"[^a-z0-9. ]", "", s.lower()).strip()


class Tbl:
    def __init__(self, t):
        self.columns = t.get("columns", []); self.rows = t.get("rows", [])
        self.idx = {_norm_label(r["label"]): r["values"] for r in self.rows}

    def row(self, key):
        for al in ALIASES.get(key, [key]):
            for lbl, vals in self.idx.items():
                if lbl == al or lbl.startswith(al):
                    return vals
        return None

    def get(self, key, col):
        vals = self.row(key)
        if vals is None or col not in self.columns: return None
        i = self.columns.index(col)
        return vals[i] if i < len(vals) else None

    def series(self, key, cols): return [self.get(key, c) for c in cols]


def build_model(raw):
    pl, bs, cf, rt, q, sh = (Tbl(raw.get(k, {})) for k in ("pl", "bs", "cf", "ratios", "quarters", "shareholding"))
    fy = [c for c in pl.columns if c and not c.upper().startswith("TTM")]
    has_ttm = any(c.upper().startswith("TTM") for c in pl.columns)
    years = fy[-3:]
    trend_years = fy[-10:]
    is_fin = pl.row("op_profit") is not None and any("financing" in r["label"].lower() for r in pl.rows)
    is_bank = bs.row("deposits") is not None

    def year_block(col, prev):
        g = lambda tbl, k, c=col: tbl.get(k, c)
        y = {k: g(pl, k) for k in ("sales", "expenses", "op_profit", "opm", "other_income", "interest", "dep",
                                    "pbt", "tax_pct", "np", "eps", "payout")}
        y.update({k: g(bs, k) for k in ("equity", "reserves", "borrowings", "deposits", "other_liab", "total_liab",
                                         "fixed_assets", "cwip", "investments", "other_assets", "total_assets")})
        y.update({k: g(cf, k) for k in ("cfo", "cfi", "cff", "net_cf")})
        y.update({k: g(rt, k) for k in ("debtor_days", "inventory_days", "payable_days", "ccc", "wc_days",
                                         "roce_s", "roe_s")})
        nw = (y["equity"] or 0) + (y["reserves"] or 0) if y["equity"] is not None else None
        y["net_worth"] = nw
        prev_nw = None
        if prev:
            pe, pr = bs.get("equity", prev), bs.get("reserves", prev)
            prev_nw = (pe or 0) + (pr or 0) if pe is not None else None
        avg_nw = (nw + prev_nw) / 2 if (nw is not None and prev_nw) else nw
        ebit = (y["pbt"] + (y["interest"] or 0)) if y["pbt"] is not None else None
        y["ebit"] = ebit
        cap_emp = (nw or 0) + (y["borrowings"] or 0) if nw is not None else None
        y["roe"] = y["roe_s"] if y["roe_s"] is not None else pct(y["np"], avg_nw)
        y["roce"] = y["roce_s"] if y["roce_s"] is not None else (None if (is_fin or is_bank) else pct(ebit, cap_emp))
        y["pat_margin"] = pct(y["np"], y["sales"])
        y["ebitda_margin"] = y["opm"] if y["opm"] is not None else pct(y["op_profit"], y["sales"])
        y["de"] = safe_div(y["borrowings"], nw) if not is_bank else None
        y["icr"] = safe_div(ebit, y["interest"]) if (y["interest"] or 0) > 0 and not is_fin else None
        y["asset_turnover"] = safe_div(y["sales"], y["total_assets"])
        y["fa_turnover"] = safe_div(y["sales"], y["fixed_assets"])
        y["cfo_pat"] = safe_div(y["cfo"], y["np"]) if (y["np"] or 0) > 0 else None
        y["fcf"] = (y["cfo"] + y["cfi"]) if (y["cfo"] is not None and y["cfi"] is not None) else None
        y["oi_pbt"] = pct(y["other_income"], y["pbt"]) if (y["pbt"] or 0) > 0 else None
        y["cwip_fa"] = pct(y["cwip"], y["fixed_assets"])
        y["bvps"] = None
        return y

    data = {}
    for i, col in enumerate(fy):
        data[col] = year_block(col, fy[i - 1] if i > 0 else None)
    for i, col in enumerate(fy):
        if i > 0:
            p = data[fy[i - 1]]; c = data[col]
            c["sales_g"] = growth(c["sales"], p["sales"]); c["np_g"] = growth(c["np"], p["np"])
            c["eps_g"] = growth(c["eps"], p["eps"])
        else:
            data[col]["sales_g"] = data[col]["np_g"] = data[col]["eps_g"] = None

    # period-length sanity check
    period_notes = []
    for a, b in list(zip(fy, fy[1:]))[-2:]:
        ia, ib = month_index(a), month_index(b)
        if ia and ib and ib - ia != 12:
            period_notes.append(f"{fy_label(b)} covers {ib - ia} months ({a} → {b}); YoY comparisons around it are distorted.")

    ttm = None
    if has_ttm:
        tcol = [c for c in pl.columns if c.upper().startswith("TTM")][0]
        ttm = {"sales": pl.get("sales", tcol), "np": pl.get("np", tcol), "op_profit": pl.get("op_profit", tcol),
               "opm": pl.get("opm", tcol), "eps": pl.get("eps", tcol)}

    qcols = q.columns[-8:]
    quarters = {"cols": qcols, "labels": qcols, "sales": q.series("sales", qcols), "op_profit": q.series("op_profit", qcols),
                "opm": q.series("opm", qcols), "np": q.series("np", qcols)}

    shcols = sh.columns[-8:]
    shareholding = {"cols": shcols, **{k: sh.series(k, shcols) for k in ("promoters", "fii", "dii", "govt", "public")}}

    return {"fy": fy, "years": years, "trend_years": trend_years, "data": data, "ttm": ttm,
            "is_financial": is_fin or is_bank, "is_bank": is_bank, "period_notes": period_notes,
            "quarters": quarters, "shareholding": shareholding}

# ---------------------------------------------------------------------
#  Ratio catalogue (what the CA sees)
# ---------------------------------------------------------------------
RATIO_GROUPS = [
    ("Growth", [
        ("sales_g", "Revenue growth (YoY)", "%", "high", "Top-line momentum; compare with industry volume growth."),
        ("np_g", "PAT growth (YoY)", "%", "high", "Bottom-line momentum; check if driven by core ops or other income."),
        ("eps_g", "EPS growth (YoY)", "%", "high", "Per-share growth after dilution."),
    ]),
    ("Profitability", [
        ("ebitda_margin", "EBITDA / Operating margin", "%", "high", "Core operating efficiency before D&A, interest, tax."),
        ("pat_margin", "PAT margin", "%", "high", "Net profit retained per ₹100 of revenue."),
        ("oi_pbt", "Other income as % of PBT", "%", "low", "High dependence on other income lowers earnings quality."),
        ("tax_pct", "Effective tax rate", "%", "neutral", "Abnormal rates may signal one-offs, MAT credit or deferred tax swings."),
    ]),
    ("Returns", [
        ("roce", "ROCE", "%", "high", "Return on all capital employed; >15% is generally healthy."),
        ("roe", "ROE", "%", "high", "Return to shareholders; read with leverage."),
    ]),
    ("Leverage & Solvency", [
        ("de", "Debt / Equity", "x", "low", "Borrowings relative to net worth."),
        ("icr", "Interest coverage (EBIT / Interest)", "x", "high", "Ability to service debt; <3x warrants attention."),
    ]),
    ("Efficiency & Working capital", [
        ("asset_turnover", "Total asset turnover", "x", "high", "Revenue generated per ₹ of assets."),
        ("fa_turnover", "Fixed asset turnover", "x", "high", "Utilisation of plant & machinery."),
        ("debtor_days", "Debtor days", "d", "low", "Collection period; rising days can hide revenue-quality issues."),
        ("inventory_days", "Inventory days", "d", "low", "Stock holding period."),
        ("payable_days", "Payable days", "d", "neutral", "Credit taken from suppliers."),
        ("ccc", "Cash conversion cycle", "d", "low", "Days cash is locked in operations."),
        ("wc_days", "Working capital days", "d", "low", "Net working capital relative to sales."),
    ]),
    ("Cash flow quality", [
        ("cfo", "Cash from operations", "cr", "high", "Actual cash generated by the business."),
        ("cfo_pat", "CFO / PAT", "x", "high", ">1x means profits are backed by cash."),
        ("fcf", "Free cash flow (CFO + CFI)", "cr", "high", "Proxy for cash left after investing activity."),
        ("cwip_fa", "CWIP as % of fixed assets", "%", "neutral", "Signals capacity under construction (upcoming projects)."),
    ]),
    ("Per share & payout", [
        ("eps", "EPS (₹)", "rs", "high", "Earnings per share as reported."),
        ("payout", "Dividend payout", "%", "neutral", "Share of profit distributed."),
    ]),
]

STATEMENT_ROWS = {
    "pl": [("sales", "Revenue from operations"), ("expenses", "Operating expenses"), ("op_profit", "Operating profit (EBITDA)"),
           ("opm", "OPM %"), ("other_income", "Other income"), ("interest", "Finance cost"), ("dep", "Depreciation"),
           ("pbt", "Profit before tax"), ("tax_pct", "Tax %"), ("np", "Net profit (PAT)"), ("eps", "EPS (₹)"),
           ("payout", "Dividend payout %")],
    "bs": [("equity", "Equity share capital"), ("reserves", "Reserves & surplus"), ("net_worth", "Net worth"),
           ("borrowings", "Borrowings"), ("deposits", "Deposits"), ("other_liab", "Other liabilities"),
           ("total_liab", "Total liabilities"), ("fixed_assets", "Fixed assets (net block)"), ("cwip", "Capital WIP"),
           ("investments", "Investments"), ("other_assets", "Other assets"), ("total_assets", "Total assets")],
    "cf": [("cfo", "Cash from operating activities"), ("cfi", "Cash from investing activities"),
           ("cff", "Cash from financing activities"), ("net_cf", "Net cash flow"), ("fcf", "Free cash flow (CFO + CFI)")],
}


def inr(v, d=0):
    """Indian digit grouping: 1234567 -> 12,34,567"""
    neg = v < 0; s_ = f"{abs(v):.{d}f}"; ip, _, dp = s_.partition(".")
    if len(ip) > 3:
        head, tail = ip[:-3], ip[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        ip = head + "," + tail
    return ("-" if neg else "") + ip + ("." + dp if dp else "")


def fmt_cr(v):
    if v is None: return "—"
    return ("-" if v < 0 else "") + f"₹{inr(abs(v))} Cr"

# ---------------------------------------------------------------------
#  Insight engine — narrative, flags, scorecard
# ---------------------------------------------------------------------
def top_ratio(raw, name):
    for k, v in raw.get("top_ratios", {}).items():
        if k.lower().startswith(name.lower()):
            return v["nums"][0] if v["nums"] else num(v["text"])
    return None


def market_snapshot(raw, model):
    tr = raw.get("top_ratios", {})
    price = top_ratio(raw, "Current Price"); mcap = top_ratio(raw, "Market Cap")
    pe = top_ratio(raw, "Stock P/E"); bv = top_ratio(raw, "Book Value")
    hl = None
    for k, v in tr.items():
        if k.lower().startswith("high"): hl = v["nums"]
    latest = model["data"].get(model["years"][-1], {}) if model["years"] else {}
    pb = safe_div(price, bv)
    ev = (mcap + (latest.get("borrowings") or 0)) if mcap else None
    ebitda = (model.get("ttm") or {}).get("op_profit") or latest.get("op_profit")
    ev_ebitda = safe_div(ev, ebitda) if not model["is_financial"] and (ebitda or 0) > 0 else None
    snap = {
        "price": price, "mcap": mcap, "pe": pe, "book_value": bv, "pb": rnd(pb, 2),
        "div_yield": top_ratio(raw, "Dividend Yield"), "roce": top_ratio(raw, "ROCE"), "roe": top_ratio(raw, "ROE"),
        "face_value": top_ratio(raw, "Face Value"), "high": hl[0] if hl else None,
        "low": hl[1] if hl and len(hl) > 1 else None, "ev_ebitda": rnd(ev_ebitda, 1),
        "earnings_yield": rnd(100 / pe, 2) if pe else None,
    }
    if snap["high"] and price:
        snap["off_high"] = rnd((price / snap["high"] - 1) * 100, 1)
    return snap


def peer_stats(raw, snap):
    peers = raw.get("peers") or []
    me = normalise_url(raw["url"]).split("/")[2] if raw.get("url") else ""
    others = [p for p in peers if me and f"/{me}/" not in p.get("url", "")]
    st = {"count": len(peers),
          "median_pe": rnd(median([p.get("pe") for p in others if (p.get("pe") or 0) > 0]), 1),
          "median_roce": rnd(median([p.get("roce") for p in others]), 1),
          "median_div_yield": rnd(median([p.get("div_yield") for p in others]), 2),
          "median_qtr_sales_var": rnd(median([p.get("qtr_sales_var") for p in others]), 1)}
    ranked = sorted([p for p in peers if p.get("mcap")], key=lambda p: -p["mcap"])
    for i, p in enumerate(ranked):
        if me and f"/{me}/" in p.get("url", ""): st["mcap_rank"] = i + 1
    st["default_peer"] = next((p for p in ranked if not (me and f"/{me}/" in p.get("url", ""))), None)
    return st


def _yl(model, i):
    ys = model["years"]; return fy_label(ys[i]) if ys and -len(ys) <= i < len(ys) else ""


def build_insights(raw, model, snap, pst):
    ys = model["years"]; D = model["data"]
    if not ys: return [], [], []
    if len(ys) < 2:
        return [{"tone": "neu", "text": "Only one audited year is available; trend-based insights need at least two years."}], [], []
    f, l = D[ys[0]], D[ys[-1]]
    n = len(ys) - 1
    ins, green, red = [], [], []
    add = lambda tone, text: ins.append({"tone": tone, "text": text})

    sc = cagr(f["sales"], l["sales"], n) if n else None
    if f["sales"] and l["sales"]:
        add("pos" if (sc or 0) > 8 else "neg" if (sc or 0) < 0 else "neu",
            f"Revenue moved from {fmt_cr(f['sales'])} in {_yl(model,0)} to {fmt_cr(l['sales'])} in {_yl(model,-1)}"
            + (f" — a CAGR of {sc:.1f}% over the audited window." if sc is not None else "."))
    pc = cagr(f["np"], l["np"], n) if n else None
    if f["np"] is not None and l["np"] is not None:
        txt = f"Net profit went from {fmt_cr(f['np'])} to {fmt_cr(l['np'])}"
        txt += f" (CAGR {pc:.1f}%)." if pc is not None else "."
        if pc is not None and sc is not None:
            txt += " Profit grew faster than revenue — operating leverage at work." if pc > sc + 3 else \
                   " Profit lagged revenue — margins are under pressure." if pc < sc - 3 else ""
        add("pos" if (pc or 0) > 10 else "neg" if (pc or 0) < 0 else "neu", txt)
    if f["ebitda_margin"] is not None and l["ebitda_margin"] is not None:
        bps = (l["ebitda_margin"] - f["ebitda_margin"]) * 100
        if abs(bps) < 5:
            add("neu", f"Operating margin held flat at about {l['ebitda_margin']:.1f}% across the window.")
        else:
            add("pos" if bps > 50 else "neg" if bps < -50 else "neu",
                f"Operating margin {'expanded' if bps > 0 else 'contracted'} by {abs(bps):.0f} bps "
                f"({f['ebitda_margin']:.1f}% → {l['ebitda_margin']:.1f}%).")
        (green if bps > 150 else red if bps < -150 else []).append(
            f"Operating margin {'up' if bps > 0 else 'down'} {abs(bps):.0f} bps over {_yl(model,0)}–{_yl(model,-1)}")
    if model["is_financial"] and l["roe"] is not None:
        add("pos" if l["roe"] >= 15 else "neg" if l["roe"] < 10 else "neu",
            f"ROE stands at {l['roe']:.1f}% in {_yl(model,-1)} (for lenders, ROE/RoA matter more than ROCE).")
        if l["roe"] >= 16: green.append(f"Healthy return on equity: {l['roe']:.1f}%")
    elif l["roce"] is not None:
        add("pos" if l["roce"] >= 15 else "neg" if l["roce"] < 10 else "neu",
            f"ROCE stands at {l['roce']:.1f}% in {_yl(model,-1)}" + (f" vs peer median {pst['median_roce']}%." if pst.get("median_roce") else "."))
        if l["roce"] >= 18: green.append(f"Strong capital efficiency — ROCE {l['roce']:.1f}%")
        elif l["roce"] < 10 and not model["is_financial"]: red.append(f"ROCE of {l['roce']:.1f}% is below a typical cost of capital")
    if not model["is_financial"]:
        if l["borrowings"] is not None and l["net_worth"]:
            de = l["de"] or 0
            if de < 0.05: add("pos", f"Virtually debt-free: borrowings of {fmt_cr(l['borrowings'])} against net worth of {fmt_cr(l['net_worth'])}."); green.append("Near debt-free balance sheet")
            else:
                add("neg" if de > 1 else "neu", f"Debt/Equity is {de:.2f}x in {_yl(model,-1)}" +
                    (f" (from {f['de']:.2f}x)." if f.get("de") is not None else "."))
                if de > 1.5: red.append(f"High leverage — D/E {de:.2f}x")
            if f["borrowings"] and l["borrowings"] and f["sales"] and l["sales"]:
                bg = growth(l["borrowings"], f["borrowings"]); sg = growth(l["sales"], f["sales"])
                if bg is not None and sg is not None and bg > sg + 25 and l["borrowings"] > 0.2 * (l["net_worth"] or 1):
                    red.append(f"Borrowings grew {bg:.0f}% vs revenue {sg:.0f}% over the period")
        if l["icr"] is not None and l["icr"] < 3:
            red.append(f"Thin interest cover — {l['icr']:.1f}x")
        cfo_sum = sum((D[y]["cfo"] or 0) for y in ys); np_sum = sum((D[y]["np"] or 0) for y in ys)
        if np_sum > 0 and any(D[y]["cfo"] is not None for y in ys):
            r = cfo_sum / np_sum
            add("pos" if r >= 1 else "neg" if r < 0.7 else "neu",
                f"Cumulative CFO of {fmt_cr(cfo_sum)} vs cumulative PAT of {fmt_cr(np_sum)} — cash conversion of {r:.2f}x.")
            if r >= 1.1: green.append(f"Profits well backed by cash (CFO/PAT {r:.2f}x)")
            elif r < 0.7: red.append(f"Weak cash conversion (CFO/PAT {r:.2f}x) — check receivables, inventory & accruals")
        fcf_sum = sum((D[y]["fcf"] or 0) for y in ys)
        if any(D[y]["fcf"] is not None for y in ys):
            add("neu", f"Aggregate free cash flow (CFO + CFI) across the window: {fmt_cr(fcf_sum)}"
                + (" — the company is in an investment phase." if fcf_sum < 0 else "."))
    if l["cwip"] and l["fixed_assets"]:
        cg = growth(l["cwip"], f["cwip"]) if f["cwip"] else None
        if (l["cwip_fa"] or 0) > 15:
            add("pos", f"Capital WIP of {fmt_cr(l['cwip'])} ({l['cwip_fa']:.0f}% of net block) points to capacity/projects under execution"
                + (f"; CWIP is up {cg:.0f}% over the window." if cg else "."))
            green.append(f"Sizeable projects in pipeline — CWIP {fmt_cr(l['cwip'])}")
    if l["oi_pbt"] is not None and l["oi_pbt"] > 25 and not model["is_financial"]:
        add("neg", f"Other income forms {l['oi_pbt']:.0f}% of PBT — part of profit is non-operational.")
        red.append(f"Other income is {l['oi_pbt']:.0f}% of PBT")
    if l["debtor_days"] is not None and f["debtor_days"] is not None and l["debtor_days"] - f["debtor_days"] > 15:
        red.append(f"Debtor days stretched from {f['debtor_days']:.0f} to {l['debtor_days']:.0f}")
    if l["wc_days"] is not None and f["wc_days"] is not None:
        dd = l["wc_days"] - f["wc_days"]
        if abs(dd) >= 10:
            add("neg" if dd > 0 else "pos", f"Working-capital days {'rose' if dd > 0 else 'fell'} from {f['wc_days']:.0f} to {l['wc_days']:.0f}.")
    if f["equity"] and l["equity"] and l["equity"] > f["equity"] * 1.02:
        add("neu", f"Equity capital rose from {fmt_cr(f['equity'])} to {fmt_cr(l['equity'])} — check for preferential issue, warrants, QIP, ESOPs or merger shares.")
        red.append("Equity dilution during the period — verify issue terms & pricing")
    if l["tax_pct"] is not None and (l["tax_pct"] < 15 or l["tax_pct"] > 35) and (l["pbt"] or 0) > 0:
        add("neu", f"Effective tax rate of {l['tax_pct']:.0f}% in {_yl(model,-1)} is unusual — look for one-offs, deferred tax or regime change.")
    if l["payout"] is not None:
        add("neu", f"Dividend payout of {l['payout']:.0f}% in {_yl(model,-1)}.")
    pe, mpe = snap.get("pe"), pst.get("median_pe")
    if pe and mpe:
        rel = pe / mpe
        add("neg" if rel > 1.3 else "pos" if rel < 0.8 else "neu",
            f"Trades at {pe:.1f}x earnings vs peer median {mpe:.1f}x — a {abs(rel - 1) * 100:.0f}% {'premium' if rel > 1 else 'discount'}.")
    shm = model["shareholding"]
    pr = [x for x in shm.get("promoters", []) if x is not None]
    if len(pr) >= 2:
        ch = pr[-1] - pr[0]
        if abs(ch) >= 0.5:
            add("pos" if ch > 0 else "neg", f"Promoter holding {'increased' if ch > 0 else 'decreased'} from {pr[0]:.2f}% to {pr[-1]:.2f}% across the last {len(pr)} quarters.")
            (green if ch > 0 else red).append(f"Promoter stake {'up' if ch > 0 else 'down'} {abs(ch):.2f} pp")
    for note in model["period_notes"]:
        add("neu", note)
    return ins, green, red


def band(v, cuts, scores):
    if v is None: return None
    for c, s in zip(cuts, scores):
        if v < c: return s
    return scores[-1] if len(scores) > len(cuts) else scores[-1]


def scorecard(raw, model, snap, pst):
    ys = model["years"]; D = model["data"]
    if not ys: return []
    f, l = D[ys[0]], D[ys[-1]]; n = len(ys) - 1
    sc = cagr(f["sales"], l["sales"], n) if n else None
    pc = cagr(f["np"], l["np"], n) if n else None
    g = [band(x, [0, 5, 10, 15, 20], [2, 4, 6, 7.5, 8.5, 9.5]) for x in (sc, pc)]
    g = [x for x in g if x is not None]
    growth_s = sum(g) / len(g) if g else 5
    prof = (band(l["roe"], [8, 12, 15, 18, 22], [3, 5, 6.5, 8, 9, 9.5]) if model["is_financial"]
            else band(l["roce"], [8, 12, 15, 20, 25], [3, 5, 6.5, 8, 9, 9.5])) or 5
    if f["ebitda_margin"] is not None and l["ebitda_margin"] is not None:
        prof += max(-1.5, min(1.5, (l["ebitda_margin"] - f["ebitda_margin"]) / 2))
    if model["is_financial"]:
        bal = band(l["roe"], [8, 12, 15, 18], [4, 5.5, 7, 8, 9]) or 5
    else:
        bal = 10 - (band(l["de"], [0.1, 0.3, 0.6, 1, 2], [0.5, 1.5, 3, 4.5, 6, 8]) or 5)
        if l["icr"] is not None and l["icr"] < 3: bal -= 1.5
    cash = 5
    if not model["is_financial"]:
        cfo_sum = sum((D[y]["cfo"] or 0) for y in ys); np_sum = sum((D[y]["np"] or 0) for y in ys)
        if np_sum > 0: cash = band(cfo_sum / np_sum, [0.5, 0.7, 0.9, 1.1, 1.3], [2.5, 3.5, 5.5, 7.5, 8.5, 9.5])
        if sum((D[y]["fcf"] or 0) for y in ys) > 0: cash += 0.5
    val = 5
    if snap.get("pe") and pst.get("median_pe"):
        val = band(snap["pe"] / pst["median_pe"], [0.6, 0.8, 1.0, 1.2, 1.5], [9, 8, 6.8, 5.5, 4.2, 3])
    elif snap.get("pe") is None and (l["np"] or 0) <= 0: val = 3
    gov = 6
    pr = [x for x in model["shareholding"].get("promoters", []) if x is not None]
    if pr:
        gov = 7 if pr[-1] >= 50 else 6 if pr[-1] >= 35 else 5
        ch = pr[-1] - pr[0]
        gov += 1 if ch > 0.5 else -1.5 if ch < -2 else -0.5 if ch < -0.5 else 0
    clamp = lambda x: round(max(0, min(10, x)), 1)
    return [{"axis": "Growth", "score": clamp(growth_s)}, {"axis": "Profitability", "score": clamp(prof)},
            {"axis": "Balance sheet", "score": clamp(bal)}, {"axis": "Cash quality", "score": clamp(cash)},
            {"axis": "Valuation", "score": clamp(val)}, {"axis": "Ownership", "score": clamp(gov)}]

# ---------------------------------------------------------------------
#  Corporate developments (announcements classifier)
# ---------------------------------------------------------------------
DEV_CATS = [
    ("AGM / EGM", "gold", ["annual general meeting", "agm", "extra-ordinary general meeting", "extraordinary general meeting",
                          "egm", "postal ballot", "e-voting", "scrutinizer", "proceedings of"]),
    ("Legal / Regulatory", "red", ["penalty", "litigation", "show cause", "competition commission", "cci ", "sebi order",
                                   "tax demand", "gst demand", "court", "tribunal", "nclat", "order passed", "adjudication", "fine imposed"]),
    ("Capex & Projects", "green", ["capacity", "commissioning", "commissioned", "expansion", "plant", "greenfield", "brownfield",
                                   "mtpa", "capex", "project", "grinding unit", "new unit", "commercial production",
                                   "order win", "bags order", "receipt of order", "award of order", "letter of award"]),
    ("M&A / Restructuring", "blue", ["acquisition", "acquire", "amalgamation", "merger", "scheme of arrangement", "demerger",
                                     "takeover", "open offer", "stake", "subsidiary", "joint venture"]),
    ("Capital & Dividend", "saffron", ["dividend", "record date", "buyback", "buy-back", "preferential", "warrant",
                                       "allotment", "rights issue", "qip", "bonus", "split", "ncd", "debenture"]),
    ("Results & Board", "navy", ["financial result", "outcome of board", "board meeting", "results", "earnings"]),
    ("Credit rating", "teal", ["credit rating", "rating"]),
    ("Management / Auditor", "red", ["resignation", "resigns", "appointment", "cessation", "auditor", "kmp",
                                     "chief financial officer", "managing director", "change in director", "ceo", "cfo"]),
    ("Investor communication", "grey", ["analyst", "investor meet", "con. call", "concall", "conference call",
                                        "presentation", "transcript", "audio recording"]),
]


def classify_dev(text):
    t = text.lower()
    for name, color, kws in DEV_CATS:
        if any(k in t for k in kws): return name, color
    return "Other disclosure", "grey"


def developments(raw):
    docs = raw.get("documents", {})
    items = []
    for a in docs.get("announcements", [])[:60]:
        cat, color = classify_dev(a["title"] + " " + a.get("detail", ""))
        date = ""
        m = re.match(r"^(\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)\s*-?\s*(.*)$", a.get("detail", ""))
        detail = a.get("detail", "")
        if m: date, detail = m.group(1), m.group(2)
        items.append({"title": a["title"], "detail": detail, "date": date, "url": a["url"], "cat": cat, "color": color})
    counts = {}
    for it in items: counts[it["cat"]] = counts.get(it["cat"], 0) + 1
    return {"items": items, "counts": counts, "annual_reports": docs.get("annual_reports", []),
            "concalls": docs.get("concalls", [])[:8], "credit_ratings": docs.get("credit_ratings", [])[:8]}

# ---------------------------------------------------------------------
#  News + sentiment (Google News RSS)
# ---------------------------------------------------------------------
POS_WORDS = ["surge", "jump", "soar", "rise", "rises", "gain", "record", "growth", "grows", "expands", "expansion", "strong",
             "beat", "beats", "upgrade", "approves", "approval", "commission", "acquire", "acquires", "acquisition",
             "wins", "order", "boost", "robust", "demand", "price hike", "hikes prices", "profit up", "dividend",
             "capacity addition", "new plant", "outperform", "bullish", "recovery", "rebound", "tailwind", "highest",
             "milestone", "launch", "investment", "invests", "buy rating", "target raised", "margin expansion"]
NEG_WORDS = ["fall", "falls", "drop", "drops", "slump", "plunge", "decline", "declines", "loss", "losses", "weak", "cut",
             "cuts", "downgrade", "penalty", "fine", "probe", "raid", "cci", "cartel", "ban", "strike", "slowdown",
             "pressure", "concern", "glut", "oversupply", "price war", "lower", "miss", "misses", "resigns", "resignation",
             "fraud", "default", "headwind", "volatile", "costlier", "cost pressure", "sell rating", "target cut",
             "bearish", "delay", "delayed", "shutdown", "dispute", "notice", "slow", "tepid", "subdued"]


POS_PHRASES = ["demand to grow", "price hike", "hikes prices", "capacity addition", "record high", "profit jumps", "profit rises",
               "beats estimate", "order win", "bags order", "upgrade", "margin expansion", "strong demand", "volume growth"]
NEG_PHRASES = ["costs rise", "cost rise", "costs surge", "costs jump", "pressure on", "margin pressure", "prices fall", "price cut",
               "weak demand", "oversupply", "penalty", "downgrade", "profit falls", "profit declines", "demand slowdown", "input cost"]


def sentiment(text):
    t = " " + text.lower() + " "
    p = sum(1 for w in POS_WORDS if f" {w}" in t) + 2 * sum(1 for w in POS_PHRASES if w in t)
    n = sum(1 for w in NEG_WORDS if f" {w}" in t) + 2 * sum(1 for w in NEG_PHRASES if w in t)
    s = p - n
    return ("Tailwind" if s > 0 else "Headwind" if s < 0 else "Neutral"), s


def google_news(query, limit=12):
    key = "gn:" + query
    cached, fresh = cache_get(key, 3 * 3600)
    if fresh: return cached
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        r = http_get(url, timeout=15)
        root = ET.fromstring(r.content)
        out = []
        for it in root.iter("item"):
            title = clean(it.findtext("title") or "")
            src_el = it.find("source"); src = clean(src_el.text) if src_el is not None and src_el.text else ""
            if src and title.endswith(" - " + src): title = title[: -(len(src) + 3)]
            pub = it.findtext("pubDate") or ""
            try: dt = datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S"); pubs = dt.strftime("%d %b %Y"); ts = dt.timestamp()
            except Exception: pubs, ts = pub[:16], 0
            lab, sc = sentiment(title)
            out.append({"title": title, "url": it.findtext("link") or "", "source": src, "date": pubs, "ts": ts,
                        "sentiment": lab, "score": sc})
        out.sort(key=lambda x: -x["ts"])
        out = out[:limit]
        cache_put(key, out)
        return out
    except Exception as e:
        log.warning("news failed %s: %s", query, e)
        return cached or []


def short_name(name):
    n = re.sub(r"\b(Ltd|Limited|Ltd\.|Corporation|Company|Co\.|India|\(India\)|The)\b", "", name or "", flags=re.I)
    return clean(n.replace("(", "").replace(")", ""))

# ---------------------------------------------------------------------
#  Industry playbooks (structural framework + audit lens)
# ---------------------------------------------------------------------
PLAYBOOKS = {
    "cement": {
        "title": "Cement", "match": ["cement"], "search": "cement industry India",
        "drivers": ["Infrastructure capex — roads, railways, metros, irrigation", "Housing & real-estate cycle (urban + rural)",
                    "Regional supply–demand balance and pricing discipline", "Power & fuel cost (pet coke, imported & domestic coal)",
                    "Freight cost and lead distance", "Capacity utilisation across regions"],
        "kpis": ["Sales volume (MT) & capacity utilisation", "Realisation per tonne", "EBITDA per tonne",
                 "Power & fuel cost per tonne", "Freight cost per tonne / lead distance", "Blended cement & clinker factor",
                 "Green power share (WHRS, solar, wind)", "Net debt / EBITDA during acquisition phases"],
        "tailwinds": ["Sustained government infrastructure spending and housing schemes",
                      "Industry consolidation improving pricing power for large players",
                      "Cost savings from waste-heat recovery, renewables and logistics optimisation",
                      "Low per-capita consumption vs global average leaves a long demand runway"],
        "headwinds": ["Heavy capacity additions can outpace demand and trigger regional price wars",
                      "Monsoon, labour and construction seasonality", "Fuel price volatility (pet coke, coal, diesel)",
                      "Regulatory scrutiny — competition (CCI) cases and environmental clearances",
                      "Decarbonisation capex and potential carbon costs", "Integration risk and goodwill from acquisitions"],
        "audit": ["State incentive / subsidy receivables and their recognition", "Mining rights, mine restoration provisions",
                  "Goodwill & intangibles from acquisitions — impairment testing (KAM)", "Related-party transactions with the promoter group",
                  "Contingent liabilities — CCI penalties, royalty, tax disputes", "CWIP ageing schedule & capitalisation timing"],
    },
    "steel": {
        "title": "Steel & Metals", "match": ["steel", "iron", "metal", "alumin", "zinc", "copper", "ferro", "mining"],
        "search": "steel metal industry India",
        "drivers": ["Global commodity prices & China exports", "Coking coal / iron ore costs", "Infra, auto & construction demand", "Trade remedies (safeguard / anti-dumping duties)"],
        "kpis": ["EBITDA per tonne", "Capacity utilisation", "Raw-material integration (captive ore/coal)", "Net debt / EBITDA", "Realisation spread over raw materials"],
        "tailwinds": ["Domestic infra & manufacturing push", "Protection via trade remedies", "Capacity expansions by integrated players"],
        "headwinds": ["Cheap imports & global oversupply", "Raw-material price spikes", "Cyclical margin swings", "Carbon-border taxes on exports"],
        "audit": ["Inventory valuation (NRV) in falling price cycles", "Mining lease liabilities & royalty disputes", "Impairment of overseas assets", "Hedging & derivative accounting"],
    },
    "bank": {
        "title": "Banking", "match": ["bank"], "search": "banking sector India RBI",
        "drivers": ["Credit growth vs deposit growth", "Interest-rate cycle & RBI policy", "Asset quality cycle", "Liquidity conditions"],
        "kpis": ["NIM", "Gross / Net NPA", "Provision coverage ratio", "CASA ratio", "Credit-deposit ratio", "CET-1 / CRAR", "Credit cost", "RoA"],
        "tailwinds": ["Healthy corporate balance sheets", "Digitisation lowering cost-to-income", "Formalisation of credit"],
        "headwinds": ["Deposit competition squeezing NIMs", "Unsecured retail stress", "Regulatory tightening (risk weights, ECL norms)"],
        "audit": ["Divergence in NPA classification", "Expected credit loss transition", "Restructured book", "Treasury MTM & investment classification"],
    },
    "nbfc": {
        "title": "NBFC & Financial Services", "match": ["finance", "nbfc", "financial", "housing finance", "asset management", "broking", "insurance"],
        "search": "NBFC financial services sector India",
        "drivers": ["Cost of funds & liquidity", "Loan growth by segment", "Asset quality", "Regulatory changes"],
        "kpis": ["AUM growth", "NIM / spread", "GS3 / NS3 (stage-3 assets)", "Cost of borrowing", "Capital adequacy", "RoA / RoE"],
        "tailwinds": ["Under-penetrated credit market", "Co-lending and digital origination"],
        "headwinds": ["Tighter RBI norms on unsecured lending", "Rising funding costs", "Concentration risk"],
        "audit": ["ECL model assumptions (Ind AS 109)", "Stage classification & write-offs", "ALM mismatch", "Securitisation / DA accounting"],
    },
    "it": {
        "title": "IT Services & Software", "match": ["software", "it ", "it -", "computers", "it services", "technology"],
        "search": "Indian IT services sector outlook",
        "drivers": ["US & Europe tech spending", "Deal wins / TCV", "Currency (INR/USD)", "GenAI adoption"],
        "kpis": ["Constant-currency revenue growth", "EBIT margin", "Deal TCV & book-to-bill", "Attrition", "Utilisation", "Client concentration"],
        "tailwinds": ["Cloud, data & AI transformation demand", "Vendor consolidation favouring large players", "Rupee depreciation"],
        "headwinds": ["Discretionary spend cuts", "Pricing pressure from AI-led productivity", "Visa & protectionism", "Wage inflation"],
        "audit": ["Revenue recognition on fixed-price contracts (Ind AS 115)", "Unbilled revenue", "Goodwill on acquisitions", "Transfer pricing"],
    },
    "fmcg": {
        "title": "FMCG & Consumer", "match": ["fmcg", "personal care", "food", "beverage", "consumer", "household", "tobacco", "packaged"],
        "search": "FMCG sector India demand",
        "drivers": ["Rural & urban consumption", "Commodity input costs (palm oil, wheat, milk, packaging)", "Distribution reach", "Pricing power"],
        "kpis": ["Volume growth vs price growth", "Gross margin", "A&P spend %", "Distribution reach", "Working capital days (often negative)"],
        "tailwinds": ["Premiumisation", "Rural recovery", "Quick-commerce channel expansion"],
        "headwinds": ["Input-cost inflation", "Competition from D2C & regional brands", "Down-trading in weak demand"],
        "audit": ["Trade promotions & discounts accruals", "Royalty to parent", "Inventory obsolescence", "Related-party sourcing"],
    },
    "auto": {
        "title": "Automobiles & Auto Components", "match": ["auto", "automobile", "vehicle", "tyre", "two wheeler", "tractor"],
        "search": "auto industry India sales",
        "drivers": ["Monthly volume trends", "Rural demand & monsoon", "Commodity costs (steel, aluminium, rubber)", "EV transition & regulation"],
        "kpis": ["Volume growth by segment", "Market share", "EBITDA margin", "Realisation per vehicle", "Inventory at dealers"],
        "tailwinds": ["Premiumisation & SUV mix", "Exports", "PLI schemes", "Replacement demand"],
        "headwinds": ["EV disruption risk for ICE players", "Regulatory cost (emission/safety norms)", "Commodity spikes"],
        "audit": ["Warranty provisions", "Product development cost capitalisation", "Dealer incentives", "Royalty / technical fees"],
    },
    "pharma": {
        "title": "Pharmaceuticals & Healthcare", "match": ["pharma", "drug", "healthcare", "hospital", "diagnostic", "biotech"],
        "search": "Indian pharma sector USFDA",
        "drivers": ["US generics pricing", "USFDA compliance", "Domestic formulations growth", "R&D pipeline"],
        "kpis": ["R&D % of sales", "US revenue & ANDA pipeline", "Domestic market growth vs IPM", "FDA inspection status (OAI/VAI)", "EBITDA margin"],
        "tailwinds": ["Complex generics & specialty launches", "China+1 in APIs / CDMO", "Chronic therapy growth"],
        "headwinds": ["US price erosion", "Warning letters / import alerts", "Domestic price controls (NLEM)"],
        "audit": ["Capitalised R&D & intangible impairment", "Chargebacks / rebates provisions (US)", "Litigation provisions", "Inventory near-expiry"],
    },
    "power": {
        "title": "Power & Utilities", "match": ["power", "electric", "utilities", "renewable", "energy"],
        "search": "power sector India demand renewable",
        "drivers": ["Electricity demand growth", "Fuel availability & cost", "Regulated returns / tariffs", "Renewable capacity addition"],
        "kpis": ["PLF / CUF", "Regulated equity", "Receivable days from DISCOMs", "Capacity under construction", "Net debt / EBITDA"],
        "tailwinds": ["Rising peak demand", "Energy-transition capex", "Improving DISCOM payment discipline"],
        "headwinds": ["DISCOM financial health", "Execution & land acquisition delays", "Tariff competition in renewables"],
        "audit": ["Regulatory deferral accounts", "Service concession arrangements", "Late-payment surcharge recognition", "Capitalisation of borrowing cost"],
    },
    "oil": {
        "title": "Oil, Gas & Refining", "match": ["oil", "gas", "refiner", "petroleum", "petrochemical", "lng"],
        "search": "oil gas sector India crude",
        "drivers": ["Crude price & gross refining margins", "Marketing margins on fuels", "Government pricing policy", "Gas demand"],
        "kpis": ["GRM ($/bbl)", "Throughput & utilisation", "Marketing margin", "Inventory gains/losses", "Net debt"],
        "tailwinds": ["Rising domestic fuel demand", "City-gas expansion", "Petchem integration"],
        "headwinds": ["Crude volatility & inventory losses", "Windfall taxes / under-recoveries", "Energy-transition risk"],
        "audit": ["Inventory valuation & hedging", "Decommissioning provisions", "Government subsidy receivables", "Exploration cost accounting"],
    },
    "chemicals": {
        "title": "Chemicals", "match": ["chemical", "agro", "fertili", "pesticide", "specialty"],
        "search": "specialty chemicals sector India",
        "drivers": ["Global destocking/restocking cycle", "China pricing", "Raw-material costs", "Capex-led growth"],
        "kpis": ["Volume vs price growth", "Gross margin", "Asset turnover on new capex", "Export share", "Customer concentration"],
        "tailwinds": ["China+1 sourcing", "Long-term contracts with MNCs", "Import substitution"],
        "headwinds": ["Chinese dumping", "Environmental compliance", "Demand slowdown in agrochem"],
        "audit": ["Environmental provisions", "Capitalisation of new plants", "Export incentive receivables", "Inventory valuation"],
    },
    "realty": {
        "title": "Real Estate & Construction", "match": ["realty", "real estate", "construction", "infra", "engineering", "epc", "housing"],
        "search": "real estate infrastructure sector India",
        "drivers": ["Pre-sales / order inflow", "Interest rates & affordability", "Government infra spend", "Land bank & approvals"],
        "kpis": ["Pre-sales / order book", "Collections", "Net debt", "Execution rate", "Book-to-bill"],
        "tailwinds": ["Housing upcycle", "Infra pipeline", "RERA-led consolidation"],
        "headwinds": ["Rate hikes", "Approval delays", "Working-capital intensity", "Commodity costs for EPC"],
        "audit": ["Revenue recognition (Ind AS 115 — POCM vs completion)", "Inventory (WIP) valuation", "Unbilled revenue & retention money", "Related-party land deals"],
    },
    "capital_goods": {
        "title": "Capital Goods & Electricals", "match": ["capital goods", "electrical", "equipment", "machinery", "cable", "defence", "aerospace", "industrial"],
        "search": "capital goods sector India order inflow",
        "drivers": ["Public & private capex cycle", "Order inflows", "Commodity costs (copper, steel)", "Defence indigenisation"],
        "kpis": ["Order book / book-to-bill", "Execution rate", "EBITDA margin", "Working capital days", "Export share"],
        "tailwinds": ["Capex revival, data centres, power T&D", "Make-in-India & PLI", "Defence orders"],
        "headwinds": ["Execution delays", "Commodity volatility", "Working-capital stretch"],
        "audit": ["Contract accounting & cost-to-complete estimates", "Liquidated damages provisions", "Retention receivables", "Warranty provisions"],
    },
    "telecom": {
        "title": "Telecom", "match": ["telecom", "communication"], "search": "telecom sector India tariff",
        "drivers": ["ARPU & tariff hikes", "Subscriber additions", "Spectrum costs", "5G capex"],
        "kpis": ["ARPU", "Subscriber base & churn", "EBITDA margin", "Net debt / EBITDA", "Capex intensity"],
        "tailwinds": ["Tariff repair", "Data consumption growth", "Enterprise & home broadband"],
        "headwinds": ["High leverage", "AGR / spectrum dues", "Heavy capex"],
        "audit": ["Spectrum amortisation", "AGR litigation provisions", "Lease accounting for towers (Ind AS 116)"],
    },
}

GENERIC_PLAYBOOK = {
    "title": "General", "search": None,
    "drivers": ["Demand growth in end-markets", "Input cost trends", "Competitive intensity", "Regulatory environment"],
    "kpis": ["Revenue growth vs industry", "Operating margin", "ROCE", "Working capital cycle", "Leverage"],
    "tailwinds": ["Domestic consumption & formalisation", "Government capex & PLI schemes"],
    "headwinds": ["Input cost inflation", "Competition", "Global slowdown"],
    "audit": ["Revenue recognition", "Related-party transactions", "Contingent liabilities", "Going-concern indicators"],
}


def pick_playbook(sector_path, name=""):
    hay = " ".join(sector_path).lower() + " " + (name or "").lower()
    for key in ["cement", "bank", "it", "pharma", "auto", "steel", "fmcg", "power", "oil", "chemicals", "telecom",
                "realty", "capital_goods", "nbfc"]:
        pb = PLAYBOOKS[key]
        if any(m in hay for m in pb["match"]):
            return pb
    return GENERIC_PLAYBOOK

# ---------------------------------------------------------------------
#  Public API — full analysis
# ---------------------------------------------------------------------
def analyse_company(url, force=False):
    raw = get_company_raw(url, force=force)
    model = build_model(raw)
    snap = market_snapshot(raw, model)
    pst = peer_stats(raw, snap)
    ins, green, red = build_insights(raw, model, snap, pst)
    score = scorecard(raw, model, snap, pst)
    pb = pick_playbook(raw.get("sector_path", []), raw.get("name"))
    sym = normalise_url(raw["url"]).split("/")[2]
    y = model["years"]

    statements = {}
    for key, rows in STATEMENT_ROWS.items():
        out = []
        for k, label in rows:
            vals = [model["data"][c].get(k) for c in y]
            if all(v is None for v in vals): continue
            out.append({"key": k, "label": label, "values": [rnd(v, 2) for v in vals]})
        statements[key] = out

    ratio_groups = []
    for g, items in RATIO_GROUPS:
        rows = []
        for k, label, unit, better, hint in items:
            vals = [rnd(model["data"][c].get(k), 2) for c in y]
            if all(v is None for v in vals): continue
            rows.append({"key": k, "label": label, "unit": unit, "better": better, "hint": hint, "values": vals})
        if rows: ratio_groups.append({"group": g, "rows": rows})

    ty = model["trend_years"]
    T = lambda k: [rnd(model["data"][c].get(k), 2) for c in ty]
    trends = {"labels": [fy_label(c) for c in ty], "sales": T("sales"), "op_profit": T("op_profit"), "np": T("np"),
              "opm": T("ebitda_margin"), "roce": T("roce"), "roe": T("roe"), "cfo": T("cfo"), "fcf": T("fcf"),
              "borrowings": T("borrowings"), "net_worth": T("net_worth"), "eps": T("eps"), "payout": T("payout")}

    return {
        "app": APP_NAME, "symbol": sym, "name": raw.get("name") or sym, "url": raw["url"],
        "basis": raw.get("basis", ""), "fetched_at": raw.get("fetched_at"), "cache": raw.get("cache"),
        "cache_note": raw.get("cache_note", ""), "about": raw.get("about", ""), "key_points": raw.get("key_points", ""),
        "sector_path": raw.get("sector_path", []), "links": build_links(raw, sym),
        "snapshot": snap, "years": y, "year_labels": [fy_label(c) for c in y], "is_financial": model["is_financial"],
        "period_notes": model["period_notes"], "statements": statements, "ratio_groups": ratio_groups,
        "ttm": model["ttm"], "trends": trends, "quarters": model["quarters"], "ranges": raw.get("ranges", []),
        "pros": raw.get("pros", []), "cons": raw.get("cons", []), "shareholding": model["shareholding"],
        "insights": ins, "green_flags": green, "red_flags": red, "scorecard": score,
        "overall": round(sum(s["score"] for s in score) / len(score), 1) if score else None,
        "peers": raw.get("peers", []), "peer_stats": pst, "developments": developments(raw),
        "playbook": {k: v for k, v in pb.items() if k != "match"},
    }


def build_links(raw, sym):
    L = raw.get("links", {})
    nse = L.get("nse") or (sym if not sym.isdigit() else None)
    out = {"Screener": SCREENER + raw["url"],
           "Moneycontrol": "https://www.google.com/search?q=" + quote_plus(f"moneycontrol {raw.get('name', sym)} share price"),
           "Annual reports (BSE)": f"https://www.bseindia.com/stock-share-price/x/y/{L['bse']}/financials-annual-reports/" if L.get("bse") else None,
           "NSE": f"https://www.nseindia.com/get-quotes/equity?symbol={quote_plus(nse)}" if nse else None,
           "Company website": L.get("website")}
    return {k: v for k, v in out.items() if v}


def moneycontrol_link(name):
    try:
        r = http_get("https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query="
                     + quote_plus(short_name(name)) + "&type=1&format=json", timeout=8)
        js = r.json()
        if js and isinstance(js, list) and js[0].get("link_src"): return js[0]["link_src"]
    except Exception:
        pass
    return None


def news_bundle(name, industry_query):
    sn = short_name(name)
    dev = google_news(f'"{sn}" (AGM OR EGM OR expansion OR acquisition OR capacity OR plant OR order OR dividend)', 12)
    company = google_news(f'"{sn}" share', 10)
    seen = set(); merged = []
    for it in dev + company:
        if it["title"] in seen: continue
        seen.add(it["title"]); merged.append(it)
    merged.sort(key=lambda x: -x["ts"])
    industry = google_news(industry_query, 14) if industry_query else []
    ind_counts = {"Tailwind": 0, "Headwind": 0, "Neutral": 0}
    for it in industry: ind_counts[it["sentiment"]] += 1
    total = sum(ind_counts.values()) or 1
    pulse = round(50 + 50 * (ind_counts["Tailwind"] - ind_counts["Headwind"]) / total)
    return {"company": merged[:16], "industry": industry, "industry_counts": ind_counts, "industry_pulse": pulse,
            "moneycontrol": moneycontrol_link(name)}


COMPARE_METRICS = [
    ("Revenue", "sales", "cr", "high"), ("Operating profit (EBITDA)", "op_profit", "cr", "high"), ("Net profit", "np", "cr", "high"),
    ("Revenue growth (YoY)", "sales_g", "%", "high"), ("PAT growth (YoY)", "np_g", "%", "high"),
    ("Operating margin", "ebitda_margin", "%", "high"), ("PAT margin", "pat_margin", "%", "high"),
    ("ROCE", "roce", "%", "high"), ("ROE", "roe", "%", "high"), ("Debt / Equity", "de", "x", "low"),
    ("Interest coverage", "icr", "x", "high"), ("Asset turnover", "asset_turnover", "x", "high"),
    ("CFO / PAT", "cfo_pat", "x", "high"), ("Working capital days", "wc_days", "d", "low"),
    ("Debtor days", "debtor_days", "d", "low"), ("Dividend payout", "payout", "%", "neutral"),
]


def compare(url_a, url_b):
    A, B = analyse_company(url_a), analyse_company(url_b)
    ma = build_model(get_company_raw(url_a)); mb = build_model(get_company_raw(url_b))
    la = ma["data"][ma["years"][-1]] if ma["years"] else {}; lb = mb["data"][mb["years"][-1]] if mb["years"] else {}
    rows = []
    for label, k, unit, better in COMPARE_METRICS:
        a, b = rnd(la.get(k), 2), rnd(lb.get(k), 2)
        if a is None and b is None: continue
        win = None
        if a is not None and b is not None and better != "neutral" and a != b:
            win = "a" if ((a > b) == (better == "high")) else "b"
        rows.append({"label": label, "unit": unit, "a": rnd(a, 2), "b": rnd(b, 2), "winner": win})
    n = lambda M: len(M["years"]) - 1
    def cg(M, k):
        y = M["years"]; return rnd(cagr(M["data"][y[0]].get(k), M["data"][y[-1]].get(k), n(M)), 1) if len(y) > 1 else None
    for pos, (label, k) in enumerate((("Revenue CAGR (audited window)", "sales"), ("PAT CAGR (audited window)", "np"))):
        a, b = cg(ma, k), cg(mb, k)
        rows.insert(3 + pos, {"label": label, "unit": "%", "a": a, "b": b,
                        "winner": None if a is None or b is None or a == b else ("a" if a > b else "b")})
    val = []
    for label, k, better in (("Market cap", "mcap", "neutral"), ("P/E", "pe", "low"), ("P/B", "pb", "low"),
                             ("EV / EBITDA", "ev_ebitda", "low"), ("Dividend yield", "div_yield", "high")):
        a, b = A["snapshot"].get(k), B["snapshot"].get(k)
        win = None
        if a is not None and b is not None and better != "neutral" and a != b:
            win = "a" if ((a > b) == (better == "high")) else "b"
        val.append({"label": label, "a": a, "b": b, "winner": win, "unit": "cr" if k == "mcap" else "%" if k == "div_yield" else "x"})
    k = min(len(A["years"]), len(B["years"]))
    chart = {"labels": [f"Y-{k - 1 - i}" if i < k - 1 else "Latest" for i in range(k)],
             "labels_a": A["year_labels"][-k:], "labels_b": B["year_labels"][-k:],
             "sales_a": [r["values"] for r in A["statements"]["pl"] if r["key"] == "sales"][0][-k:] if k else [],
             "sales_b": [r["values"] for r in B["statements"]["pl"] if r["key"] == "sales"][0][-k:] if k else [],
             "np_a": [r["values"] for r in A["statements"]["pl"] if r["key"] == "np"][0][-k:] if k else [],
             "np_b": [r["values"] for r in B["statements"]["pl"] if r["key"] == "np"][0][-k:] if k else []}
    wins_a = sum(1 for r in rows + val if r["winner"] == "a"); wins_b = sum(1 for r in rows + val if r["winner"] == "b")
    return {"a": {"name": A["name"], "symbol": A["symbol"], "year": A["year_labels"][-1] if A["year_labels"] else "", "overall": A["overall"], "scorecard": A["scorecard"]},
            "b": {"name": B["name"], "symbol": B["symbol"], "year": B["year_labels"][-1] if B["year_labels"] else "", "overall": B["overall"], "scorecard": B["scorecard"]},
            "rows": rows, "valuation": val, "chart": chart, "wins": {"a": wins_a, "b": wins_b}}

# ---------------------------------------------------------------------
#  Annual-report deep scan (PDF text mining)
# ---------------------------------------------------------------------
SCAN_CATS = [
    ("Auditor's opinion & Key Audit Matters", "shield",
     {"key audit matter": 3, "qualified opinion": 4, "emphasis of matter": 4, "adverse opinion": 5, "disclaimer of opinion": 5,
      "material uncertainty": 4, "going concern": 2, "basis for qualified": 5, "except for the effects": 3, "caro": 1}),
    ("Capex, capacity & upcoming projects", "factory",
     {"capacity": 2, "commissioned": 3, "commissioning": 3, "expansion": 2, "greenfield": 3, "brownfield": 3,
      "capital expenditure": 2, "capex": 2, "new plant": 3, "grinding unit": 3, "clinker": 1, "mtpa": 3,
      "under construction": 2, "debottleneck": 3, "capital work-in-progress": 1, "project": 1, "upcoming": 2}),
    ("Strategy, outlook & guidance", "compass",
     {"outlook": 3, "going forward": 2, "strategy": 1, "we expect": 3, "we aim": 2, "target": 1, "vision": 1,
      "guidance": 3, "fy27": 2, "fy26": 1, "by 2028": 2, "by 2030": 2, "roadmap": 2}),
    ("Risks & concerns (MD&A)", "alert",
     {"risks and concerns": 4, "risk": 1, "threat": 2, "headwind": 2, "volatility": 1, "uncertain": 1, "challenge": 1, "competition": 1}),
    ("Contingent liabilities & commitments", "scale",
     {"contingent liabilit": 4, "claims against the company not acknowledged": 5, "capital commitment": 3,
      "guarantees": 1, "disputed": 2, "demand": 1, "show cause": 2, "penalty": 2}),
    ("Related party transactions", "link",
     {"related party": 3, "holding company": 2, "fellow subsidiar": 2, "arm's length": 2, "promoter group": 2, "key managerial": 1}),
    ("Dividend, capital & fund raising", "coins",
     {"dividend": 2, "preferential": 3, "warrant": 3, "buyback": 3, "allotment": 2, "rights issue": 3, "qip": 3, "bonus": 2}),
    ("M&A, subsidiaries & restructuring", "merge",
     {"acquisition": 3, "acquired": 2, "amalgamation": 3, "merger": 3, "scheme of arrangement": 3, "demerger": 3,
      "subsidiary": 1, "stake": 1, "open offer": 3}),
    ("ESG & sustainability", "leaf",
     {"renewable": 2, "waste heat": 3, "whrs": 3, "carbon": 1, "emission": 1, "net zero": 3, "green power": 3, "water positive": 3, "sbti": 3}),
]
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z₹(\"'])")
_NUMBERY = re.compile(r"(₹|rs\.?|crore|cr\b|mtpa|million|billion|%|\b\d{2,}[\d,.]*\b)", re.I)


def pdf_pages(data, max_pages=600):
    pages = []
    try:
        import fitz  # PyMuPDF (fast, optional)
        doc = fitz.open(stream=data, filetype="pdf")
        for i, p in enumerate(doc):
            if i >= max_pages: break
            pages.append(p.get_text())
        return pages
    except ImportError:
        pass
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    for i, p in enumerate(rd.pages):
        if i >= max_pages: break
        try: pages.append(p.extract_text() or "")
        except Exception: pages.append("")
    return pages


def scan_annual_report(data, label="Uploaded report"):
    t0 = time.time()
    if not data[:5].startswith(b"%PDF"):
        raise ValueError("The file is not a PDF (annual report link may require a browser download).")
    pages = pdf_pages(data)
    buckets = {c[0]: [] for c in SCAN_CATS}
    seen = set()
    for pno, txt in enumerate(pages, 1):
        if not txt: continue
        t = re.sub(r"\s+", " ", txt)
        for s in _SENT_SPLIT.split(t):
            s = s.strip()
            if not (60 <= len(s) <= 480): continue
            low = s.lower()
            sig = low[:70]
            for cname, icon, kws in SCAN_CATS:
                score = 0; hits = []
                for k, w in kws.items():
                    if k in low: score += w; hits.append(k)
                if score < 2: continue
                if _NUMBERY.search(s): score += 1.5
                if len(s) > 350: score -= 1
                if score < 3: continue
                buckets[cname].append({"text": s, "page": pno, "score": round(score, 1), "hits": hits})
    result = []
    for cname, icon, _ in SCAN_CATS:
        items = sorted(buckets[cname], key=lambda x: -x["score"])
        picked, sigs = [], set()
        for it in items:
            sg = it["text"].lower()[:70]
            if sg in sigs: continue
            sigs.add(sg); picked.append(it)
            if len(picked) >= 7: break
        result.append({"category": cname, "icon": icon, "items": picked, "total_hits": len(items)})
    # capacity numbers spotted
    caps, csig = [], set()
    cap_re = re.compile(r"\d{1,3}(?:\.\d+)?\s*(?:MTPA|mtpa|million tonnes? per annum|MW\b|GW\b)")
    for pno, txt in enumerate(pages, 1):
        for s in _SENT_SPLIT.split(re.sub(r"\s+", " ", txt or "")):
            if cap_re.search(s) and 30 <= len(s) <= 420 and s[:60] not in csig:
                csig.add(s[:60]); caps.append(f"{clean(s)} (p. {pno})")
        if len(caps) >= 8: break
    return {"label": label, "pages": len(pages), "seconds": round(time.time() - t0, 1), "categories": result,
            "capacity_mentions": caps}


def scan_from_url(pdf_url):
    key = "scan:" + pdf_url
    cached, fresh = cache_get(key, 30 * 86400)
    if cached: return cached
    hdr = dict(BROWSER_HEADERS)
    hdr["Accept"] = "application/pdf,*/*"
    if "bseindia" in pdf_url: hdr["Referer"] = "https://www.bseindia.com/"
    if "nseindia" in pdf_url: hdr["Referer"] = "https://www.nseindia.com/"
    r = S().get(pdf_url, headers=hdr, timeout=120, allow_redirects=True)
    r.raise_for_status()
    res = scan_annual_report(r.content, label=pdf_url.split("/")[-1])
    cache_put(key, res)
    return res

# ---------------------------------------------------------------------
#  HTTP server
# ---------------------------------------------------------------------
PAGES = {}           # path -> (content_type, bytes)  — filled by launcher


def _json(handler, obj, code=200):
    body = json.dumps(obj, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self):
        u = urlparse(self.path); qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in PAGES:
                ct, body = PAGES[u.path]
                self.send_response(200); self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if u.path == "/api/search":
                return _json(self, search_companies(qs.get("q", "")))
            if u.path == "/api/company":
                return _json(self, analyse_company(qs.get("url", ""), force=qs.get("force") == "1"))
            if u.path == "/api/news":
                return _json(self, news_bundle(qs.get("name", ""), qs.get("industry", "")))
            if u.path == "/api/compare":
                return _json(self, compare(qs["a"], qs["b"]))
            if u.path == "/api/scan":
                return _json(self, scan_from_url(qs["pdf"]))
            if u.path == "/api/health":
                return _json(self, {"ok": True, "app": APP_NAME, "version": APP_VERSION})
            self.send_error(404)
        except Exception as e:
            log.error("GET %s failed: %s", self.path, traceback.format_exc())
            _json(self, {"error": str(e) or e.__class__.__name__}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/scan-upload":
                n = int(self.headers.get("Content-Length", 0))
                if n > 150 * 1024 * 1024: return _json(self, {"error": "File too large (max 150 MB)"}, 413)
                data = self.rfile.read(n)
                name = parse_qs(u.query).get("name", ["Uploaded report"])[0]
                return _json(self, scan_annual_report(data, label=name))
            self.send_error(404)
        except Exception as e:
            log.error("POST failed: %s", traceback.format_exc())
            _json(self, {"error": str(e)}, 500)


def start_server(host, ports):
    for p in ports:
        try:
            srv = ThreadingHTTPServer((host, p), Handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            threading.Thread(target=load_master, daemon=True).start()
            return srv, p
        except OSError:
            continue
    raise RuntimeError("No free port available")


# =====================================================================
#  Launcher helpers (control window, icon, PWA assets)
# =====================================================================
import webbrowser, socket

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#0E1B33"/>
<g transform="translate(256 256) scale(6.4)" fill="none" stroke="#D9822B" stroke-width="2.4">
<g id="p"><path d="M0-26 C7-20 7-12 0-8 C-7-12 -7-20 0-26Z"/></g>
<use href="#p" transform="rotate(45)"/><use href="#p" transform="rotate(90)"/><use href="#p" transform="rotate(135)"/>
<use href="#p" transform="rotate(180)"/><use href="#p" transform="rotate(225)"/><use href="#p" transform="rotate(270)"/><use href="#p" transform="rotate(315)"/>
<path d="M-11 0 Q0-9 11 0 Q0 9-11 0Z" fill="#F3B263" stroke="none"/><circle r="3.6" fill="#0E1B33" stroke="none"/>
</g></svg>"""

NAVY, SAFFRON, GOLD, IVORY = "#0E1B33", "#D9822B", "#F3B263", "#F6F3EC"


def fatal(msg):
    log.error(msg)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw(); messagebox.showerror(APP_NAME, msg); r.destroy()
    except Exception:
        print(msg)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def draw_logo(canvas, cx, cy, r):
    """Mandala-eye logo drawn with tkinter primitives."""
    import math
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=NAVY, outline=GOLD, width=1)
    for k in range(8):
        a = math.radians(k * 45)
        pts = []
        for t in range(0, 361, 20):
            tt = math.radians(t)
            # petal: ellipse centred on radius 0.6r, length .32r, width .13r
            px, py = 0.13 * r * math.sin(tt), -0.6 * r + 0.32 * r * math.cos(tt)
            pts += [cx + px * math.cos(a) - py * math.sin(a), cy + px * math.sin(a) + py * math.cos(a)]
        canvas.create_polygon(pts, outline=SAFFRON, fill="", width=2, smooth=True)
    canvas.create_oval(cx - .36 * r, cy - .2 * r, cx + .36 * r, cy + .2 * r, fill=GOLD, outline="")
    canvas.create_oval(cx - .11 * r, cy - .11 * r, cx + .11 * r, cy + .11 * r, fill=NAVY, outline="")


def control_window(title_line, url, srv, extra=None, size="460x300"):
    """Small branded window that keeps the local server alive; closing it stops the app."""
    try:
        import tkinter as tk
    except ImportError:
        print(f"{APP_NAME} running at {url}  (Ctrl+C to stop)")
        try:
            while True: time.sleep(3600)
        except KeyboardInterrupt:
            return
    root = tk.Tk()
    root.title(f"{APP_NAME} · {APP_DEVANAGARI}")
    root.geometry(size); root.configure(bg=NAVY); root.resizable(False, False)
    top = tk.Frame(root, bg=NAVY); top.pack(fill="x", padx=22, pady=(18, 6))
    cv = tk.Canvas(top, width=58, height=58, bg=NAVY, highlightthickness=0); cv.pack(side="left")
    draw_logo(cv, 29, 29, 27)
    tf = tk.Frame(top, bg=NAVY); tf.pack(side="left", padx=12)
    tk.Label(tf, text=APP_NAME, fg="white", bg=NAVY, font=("Georgia", 20, "bold")).pack(anchor="w")
    tk.Label(tf, text=f"{APP_DEVANAGARI}  ·  {title_line}", fg=GOLD, bg=NAVY, font=("Nirmala UI", 11)).pack(anchor="w")
    body = tk.Frame(root, bg=NAVY); body.pack(fill="both", expand=True, padx=22)
    if extra: extra(root, body)
    tk.Label(body, text="● Running", fg="#5BD39A", bg=NAVY, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
    lk = tk.Label(body, text=url, fg="white", bg=NAVY, font=("Consolas", 11), cursor="hand2"); lk.pack(anchor="w")
    lk.bind("<Button-1>", lambda e: webbrowser.open(url))
    btns = tk.Frame(root, bg=NAVY); btns.pack(fill="x", padx=22, pady=16)

    def mk(text, cmd, primary=False):
        b = tk.Button(btns, text=text, command=cmd, bg=SAFFRON if primary else "#22355C", fg="white",
                      activebackground="#c4711e", activeforeground="white", relief="flat",
                      font=("Segoe UI", 10, "bold"), padx=14, pady=7, cursor="hand2", bd=0)
        b.pack(side="left", padx=(0, 8)); return b

    def stop():
        try: srv.shutdown()
        except Exception: pass
        root.destroy()
    root._mk = mk
    root._stop = stop
    root.protocol("WM_DELETE_WINDOW", stop)
    return root, mk, stop


WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ArthaDrishti · अर्थदृष्टि — Investment Analysis</title>
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650&family=Inter:wght@400;500;600;700&family=Tiro+Devanagari+Hindi&display=swap" rel="stylesheet">
<style>
:root{--navy:#0E1B33;--navy2:#172A4D;--ink:#1B2333;--muted:#5F6B7E;--ivory:#F6F3EC;--card:#fff;--line:#E6E0D3;--line2:#EFEAE0;
--saffron:#D9822B;--saffron2:#F3B263;--gold:#B8892D;--green:#1E8A5A;--red:#C2412D;--blue:#2F5DA8;--teal:#1C7C86;
--serif:'Fraunces',Georgia,'Times New Roman',serif;--sans:'Inter','Segoe UI',system-ui,-apple-system,sans-serif;--deva:'Tiro Devanagari Hindi','Nirmala UI','Mangal',serif;
--sh:0 1px 2px rgba(14,27,51,.05),0 6px 24px -8px rgba(14,27,51,.12);--r:16px}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font-family:var(--sans);color:var(--ink);background:var(--ivory);font-size:14.5px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
h1,h2,h3{font-family:var(--serif);font-weight:650;letter-spacing:-.01em;margin:0}
button{font-family:inherit;cursor:pointer}
.hidden{display:none!important}
/* ---------- top bar ---------- */
.topbar{position:sticky;top:0;z-index:50;height:64px;background:var(--navy);display:flex;align-items:center;gap:20px;padding:0 24px;box-shadow:0 2px 18px rgba(0,0,0,.18)}
.brand{display:flex;align-items:center;gap:10px;color:#fff;cursor:pointer;flex-shrink:0}
.brand svg{width:36px;height:36px}
.brand b{font-family:var(--serif);font-size:20px;font-weight:650;letter-spacing:.01em}
.brand small{font-family:var(--deva);color:var(--saffron2);font-size:14px;display:block;line-height:1;margin-top:2px}
.tb-search{flex:1;max-width:560px;position:relative}
.tb-search input{width:100%;height:40px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.08);color:#fff;padding:0 16px 0 40px;font-size:14px;outline:none;transition:.2s}
.tb-search input::placeholder{color:rgba(255,255,255,.55)}
.tb-search input:focus{background:#fff;color:var(--ink);border-color:#fff}
.tb-search .si{position:absolute;left:14px;top:11px;width:18px;height:18px;opacity:.6;color:#fff}
.tb-search input:focus+.si{color:var(--muted)}
.tb-actions{margin-left:auto;display:flex;gap:8px}
.btn{height:38px;padding:0 16px;border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--ink);font-weight:600;font-size:13px;display:inline-flex;align-items:center;gap:7px;transition:.15s}
.btn:hover{border-color:var(--saffron);color:var(--saffron)}
.btn.dark{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.18);color:#fff}
.btn.dark:hover{background:var(--saffron);border-color:var(--saffron);color:#fff}
.btn.primary{background:var(--saffron);border-color:var(--saffron);color:#fff}.btn.primary:hover{background:#c4711e;color:#fff}
.btn svg{width:16px;height:16px}
/* ---------- autocomplete ---------- */
.ac{position:absolute;left:0;right:0;top:calc(100% + 8px);background:#fff;border-radius:14px;box-shadow:0 18px 50px -12px rgba(14,27,51,.35);overflow:hidden;display:none;z-index:80;border:1px solid var(--line)}
.ac.open{display:block;animation:pop .14s ease-out}
.ac-item{display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;color:var(--ink)}
.ac-item+.ac-item{border-top:1px solid var(--line2)}
.ac-item.active,.ac-item:hover{background:#FBF3E8}
.ac-ic{width:30px;height:30px;border-radius:9px;background:var(--navy);color:var(--saffron2);display:grid;place-items:center;font-weight:700;font-family:var(--serif);flex-shrink:0}
.ac-name{flex:1;font-weight:500}.ac-name mark{background:none;color:var(--saffron);font-weight:700}
.ac-sym{font-size:11.5px;color:var(--muted);background:var(--ivory);padding:3px 8px;border-radius:6px;font-weight:600;letter-spacing:.03em}
.ac-empty{padding:14px;color:var(--muted);font-size:13px}
@keyframes pop{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
/* ---------- home ---------- */
#home{min-height:calc(100vh - 64px);display:flex;flex-direction:column}
.hero{position:relative;background:radial-gradient(1200px 500px at 85% -10%,#24406f 0%,transparent 60%),linear-gradient(160deg,#0E1B33 0%,#13254A 70%,#0E1B33 100%);color:#fff;padding:84px 24px 120px;overflow:hidden}
.hero .mandala{position:absolute;right:-140px;top:-120px;width:620px;height:620px;opacity:.16;animation:spin 140s linear infinite}
.hero .mandala.l{left:-220px;right:auto;top:auto;bottom:-300px;width:520px;height:520px;opacity:.08;animation-direction:reverse}
@keyframes spin{to{transform:rotate(360deg)}}
.hero-in{max-width:880px;margin:0 auto;position:relative;text-align:center}
.eyebrow{display:inline-flex;align-items:center;gap:8px;border:1px solid rgba(243,178,99,.35);color:var(--saffron2);padding:6px 14px;border-radius:999px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;font-weight:600}
.hero h1{font-size:64px;margin:22px 0 0;line-height:1.02}
.hero h1 span{color:var(--saffron2)}
.hero .deva{font-family:var(--deva);font-size:30px;color:rgba(255,255,255,.75);margin-top:6px}
.hero p.lead{font-size:17px;color:rgba(255,255,255,.72);max-width:640px;margin:18px auto 34px}
.big-search{position:relative;max-width:680px;margin:0 auto}
.big-search input{width:100%;height:64px;border-radius:18px;border:0;padding:0 150px 0 58px;font-size:17px;color:var(--ink);box-shadow:0 20px 60px -15px rgba(0,0,0,.5);outline:none}
.big-search input:focus{box-shadow:0 0 0 4px rgba(217,130,43,.35),0 20px 60px -15px rgba(0,0,0,.5)}
.big-search .si{position:absolute;left:20px;top:21px;width:22px;height:22px;color:var(--muted)}
.big-search .go{position:absolute;right:8px;top:8px;height:48px;padding:0 22px;border-radius:12px;border:0;background:var(--saffron);color:#fff;font-weight:700;font-size:14px}
.big-search .go:hover{background:#c4711e}
.big-search .ac{text-align:left}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:22px}
.chip{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);color:#fff;border-radius:999px;padding:7px 14px;font-size:13px;transition:.15s}
.chip:hover{background:var(--saffron);border-color:var(--saffron)}
.features{max-width:1120px;margin:-70px auto 40px;padding:0 24px;display:grid;grid-template-columns:repeat(3,1fr);gap:18px;position:relative}
.feat{background:#fff;border-radius:var(--r);padding:22px;box-shadow:var(--sh);border:1px solid var(--line2)}
.feat .fi{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:#FBF0E2;color:var(--saffron);margin-bottom:12px}
.feat .fi svg{width:22px;height:22px}
.feat h3{font-size:17px;margin-bottom:4px}.feat p{margin:0;color:var(--muted);font-size:13.5px}
.home-foot{text-align:center;color:var(--muted);font-size:12.5px;padding:10px 24px 40px;margin-top:auto}
/* ---------- report layout ---------- */
#report{display:grid;grid-template-columns:232px 1fr;min-height:calc(100vh - 64px)}
.side{position:sticky;top:64px;height:calc(100vh - 64px);padding:22px 14px;border-right:1px solid var(--line);background:#FBF9F4;overflow:auto}
.side .co{padding:4px 10px 16px;border-bottom:1px solid var(--line);margin-bottom:12px}
.side .co b{font-family:var(--serif);font-size:16px;display:block;line-height:1.25}
.side .co span{font-size:12px;color:var(--muted)}
.nav a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;color:var(--muted);font-weight:500;font-size:13.5px;text-decoration:none;margin-bottom:2px;transition:.15s}
.nav a svg{width:17px;height:17px;flex-shrink:0}
.nav a:hover{background:#F1ECE1;color:var(--ink)}
.nav a.active{background:var(--navy);color:#fff}.nav a.active svg{color:var(--saffron2)}
.side .disc{font-size:11px;color:var(--muted);padding:16px 10px 0;line-height:1.45}
main{padding:28px 36px 80px;max-width:1260px;width:100%}
section.blk{margin-bottom:34px;scroll-margin-top:84px}
.blk-h{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:14px}
.blk-h h2{font-size:24px}
.blk-h .sub{color:var(--muted);font-size:13px;margin-top:3px;font-family:var(--sans)}
.kicker{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--saffron);font-weight:700;margin-bottom:4px}
.card{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);border:1px solid var(--line2);padding:20px}
.card h3{font-size:16px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.grid{display:grid;gap:18px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.g-snap{grid-template-columns:340px 1fr}
.empty{color:var(--muted);font-size:13px;padding:18px;text-align:center}
/* company hero */
.cohero{background:linear-gradient(135deg,#0E1B33,#1B3260);color:#fff;border-radius:20px;padding:28px 30px;position:relative;overflow:hidden;box-shadow:var(--sh)}
.cohero .mandala{position:absolute;right:-90px;top:-90px;width:330px;height:330px;opacity:.13}
.cohero h1{font-size:34px;position:relative}
.crumbs{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;position:relative}
.crumb{font-size:12px;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.1);color:rgba(255,255,255,.85)}
.badge{font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;letter-spacing:.04em;text-transform:uppercase}
.badge.basis{background:var(--saffron);color:#fff}.badge.live{background:#1E8A5A;color:#fff}.badge.stale{background:#C2412D;color:#fff}.badge.fresh{background:#2F5DA8;color:#fff}
.cohero .meta{display:flex;gap:10px;align-items:center;margin-top:12px;font-size:12px;color:rgba(255,255,255,.7);position:relative;flex-wrap:wrap}
.qlinks{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px;position:relative}
.qlinks a{font-size:12.5px;color:#fff;border:1px solid rgba(255,255,255,.2);padding:6px 12px;border-radius:999px;text-decoration:none}
.qlinks a:hover{background:rgba(255,255,255,.12)}
.basis-toggle{position:absolute;right:26px;top:26px;display:flex;background:rgba(255,255,255,.08);border-radius:999px;padding:3px;z-index:2}
.basis-toggle button{border:0;background:none;color:rgba(255,255,255,.7);font-size:12px;font-weight:600;padding:6px 12px;border-radius:999px}
.basis-toggle button.on{background:#fff;color:var(--navy)}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:16px}
.kpi{background:#fff;border-radius:14px;padding:14px 16px;border:1px solid var(--line2);box-shadow:var(--sh)}
.kpi .l{font-size:11.5px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:21px;font-weight:700;font-family:var(--serif);margin-top:3px;white-space:nowrap}
.kpi .s{font-size:11.5px;color:var(--muted)}
.about{margin-top:16px;font-size:13.5px;color:var(--muted)}
.about b{color:var(--ink)}
/* snapshot */
.score-wrap{display:flex;flex-direction:column;align-items:center}
.ring{width:130px;height:130px}.ring-bg{fill:none;stroke:#EFE9DD;stroke-width:10}.ring-fg{transition:stroke-dashoffset 1.2s ease}
.ring-v{font-family:var(--serif);font-size:28px;font-weight:650;fill:var(--ink)}.ring-l{font-size:9px;fill:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.radar{width:100%;max-width:310px}.rgrid{fill:none;stroke:#E8E1D2}.rlab{font-size:10.5px;fill:var(--muted);font-weight:600}.rval{font-size:11px;font-weight:700;fill:var(--ink)}
.rpoly{animation:fadein .9s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.score-note{font-size:11px;color:var(--muted);text-align:center;margin-top:4px}
.insights{list-style:none;margin:0;padding:0}
.insights li{display:flex;gap:12px;padding:10px 0;border-bottom:1px dashed var(--line);font-size:14px}
.insights li:last-child{border:0}
.dot{width:9px;height:9px;border-radius:50%;margin-top:7px;flex-shrink:0}
.dot.pos{background:var(--green)}.dot.neg{background:var(--red)}.dot.neu{background:var(--gold)}
.flags{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}
.flagbox{border-radius:14px;padding:14px 16px}
.flagbox.g{background:#EAF5EF;border:1px solid #CFE7DA}.flagbox.r{background:#FBEDEA;border:1px solid #F1D3CC}
.flagbox h4{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.06em}
.flagbox.g h4{color:var(--green)}.flagbox.r h4{color:var(--red)}
.flagbox ul{margin:0;padding-left:18px;font-size:13.5px}.flagbox li{margin:4px 0}
/* tables */
.tabs{display:inline-flex;background:#EFEAE0;border-radius:12px;padding:4px;gap:2px}
.tabs button{border:0;background:none;padding:7px 14px;border-radius:9px;font-weight:600;font-size:13px;color:var(--muted)}
.tabs button.on{background:#fff;color:var(--ink);box-shadow:0 1px 4px rgba(0,0,0,.08)}
table.fin{width:100%;border-collapse:collapse;font-size:13.5px}
table.fin th{text-align:right;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:700;padding:10px 12px;border-bottom:2px solid var(--line)}
table.fin th:first-child,table.fin td:first-child{text-align:left}
table.fin td{padding:10px 12px;border-bottom:1px solid var(--line2);text-align:right;font-variant-numeric:tabular-nums}
table.fin tr:hover td{background:#FCFAF5}
table.fin tr.em td{font-weight:700;background:#FBF6EC}
table.fin td.lbl{font-weight:500}
.chg{font-size:11.5px;font-weight:700;padding:2px 7px;border-radius:6px;white-space:nowrap}
.chg.good{color:var(--green);background:#E7F4EC}.chg.bad{color:var(--red);background:#FBECE8}.chg.flat{color:var(--muted);background:#F1EEE7}
.note{background:#FFF7E9;border:1px solid #F2DDB6;color:#8A5A12;border-radius:12px;padding:10px 14px;font-size:13px;margin-bottom:12px}
.note.err{background:#FBEDEA;border-color:#F1D3CC;color:var(--red)}
.unit{font-size:11.5px;color:var(--muted)}
/* ratios */
.rgroup h3 .pill{margin-left:auto}
.rrow{display:grid;grid-template-columns:1fr repeat(3,74px) 82px;align-items:center;gap:6px;padding:8px 0;border-bottom:1px solid var(--line2);font-size:13.5px}
.rrow:last-child{border:0}
.rrow.h{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-weight:700;border-bottom:1px solid var(--line)}
.rrow .v{text-align:right;font-variant-numeric:tabular-nums}
.rrow .v.last{font-weight:700}
.rrow .t{text-align:right}
.tip{position:relative;cursor:help;border-bottom:1px dotted #B9B2A3}
.tip:hover::after{content:attr(data-tip);position:absolute;left:0;bottom:calc(100% + 8px);background:var(--navy);color:#fff;font-size:12px;line-height:1.4;padding:8px 10px;border-radius:8px;width:250px;z-index:20;font-weight:400;box-shadow:0 8px 24px rgba(0,0,0,.25)}
/* charts */
.chart{width:100%;height:auto;display:block}
.grid{}.chart .grid{stroke:#EEE8DC;stroke-width:1}.chart .grid.zero{stroke:#C9C1B0}
.chart .ax{font-size:10.5px;fill:#8A8F99;font-family:var(--sans)}
.chart .bar{transform-origin:bottom;animation:grow .6s ease both}
@keyframes grow{from{opacity:0;transform:scaleY(.2)}to{opacity:1;transform:none}}
.chart .ln{stroke-dasharray:2000;stroke-dashoffset:2000;animation:draw 1.4s ease forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin-bottom:6px}
.legend.col{flex-direction:column;gap:6px}.legend b{color:var(--ink)}
.lg{display:inline-flex;align-items:center;gap:6px}.lg i{display:inline-block}.lg i.sq{width:10px;height:10px;border-radius:3px}.lg i.ln{width:16px;height:3px;border-radius:2px}
.donut-wrap{display:flex;align-items:center;gap:20px}.donut{width:150px;flex-shrink:0}
.ranges{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.range{background:#FBF9F4;border:1px solid var(--line2);border-radius:12px;padding:12px 14px}
.range b{font-size:12px;color:var(--muted);display:block;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}
.range div{display:flex;justify-content:space-between;font-size:13px;padding:2px 0}.range div span:last-child{font-weight:700}
.pc{list-style:none;padding:0;margin:0}.pc li{padding:7px 0 7px 26px;position:relative;font-size:13.5px;border-bottom:1px dashed var(--line)}.pc li:last-child{border:0}
.pc li::before{position:absolute;left:0;top:7px;width:18px;height:18px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:700;color:#fff}
.pc.pros li::before{content:'✓';background:var(--green)}.pc.cons li::before{content:'!';background:var(--red)}
/* peers */
.vs{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:stretch;margin-bottom:16px}
.vs .mid{align-self:center}
.vs .side-a,.vs .side-b{border-radius:16px;padding:18px 20px;color:#fff;position:relative;overflow:hidden}
.vs .side-a{background:linear-gradient(135deg,#0E1B33,#244079)}.vs .side-b{background:linear-gradient(135deg,#8A4E12,#D9822B);text-align:right}
.vs h3{font-size:20px;color:#fff;display:block;margin:0}
.vs .sc{font-size:12px;opacity:.8;margin-top:4px}.vs .wins{font-family:var(--serif);font-size:30px;margin-top:6px}
.vs .mid{font-family:var(--serif);font-size:22px;color:var(--muted);text-align:center}
.vs select{margin-top:8px;padding:6px 10px;border-radius:8px;border:0;font-weight:600;font-family:inherit;max-width:100%}
.pick{position:relative;max-width:420px}.pick input{width:100%;height:42px;border-radius:12px;border:1px solid var(--line);padding:0 14px 0 38px;font-size:14px;outline:none;background:#fff}
.pick input:focus{border-color:var(--saffron);box-shadow:0 0 0 3px rgba(217,130,43,.15)}.pick .si{position:absolute;left:12px;top:12px;width:18px;height:18px;color:var(--muted)}
.cmp td .bars{display:flex;align-items:center;gap:6px;justify-content:flex-end}
.cmp .win{color:var(--green);font-weight:700}.cmp .win::after{content:' ★';color:var(--gold)}
table.fin tr.me td{background:#FDF3E6;font-weight:700}
table.fin tr.med td{background:#F1EEE7;font-style:italic}
/* developments */
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.fchip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px;font-size:12.5px;font-weight:600;color:var(--muted)}
.fchip.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.fchip b{margin-left:4px;color:var(--saffron)}
.timeline{position:relative;padding-left:22px;max-height:640px;overflow:auto}
.timeline::before{content:'';position:absolute;left:6px;top:4px;bottom:4px;width:2px;background:var(--line)}
.tl{position:relative;padding:4px 0 14px}
.tl::before{content:'';position:absolute;left:-21px;top:9px;width:12px;height:12px;border-radius:50%;background:var(--c,#999);border:3px solid #fff;box-shadow:0 0 0 1px var(--line)}
.tl .cat{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--c)}
.tl .ttl{font-weight:600;font-size:13.5px;color:var(--ink);display:block;margin:2px 0}
.tl .det{font-size:12.5px;color:var(--muted)}
.tl .dt{font-size:11.5px;color:var(--muted);font-weight:600}
.news{list-style:none;padding:0;margin:0}
.news li{padding:10px 0;border-bottom:1px solid var(--line2);display:flex;gap:10px;align-items:flex-start}
.news li:last-child{border:0}
.news a{color:var(--ink);font-weight:500;font-size:13.5px}
.news .src{font-size:11.5px;color:var(--muted);margin-top:2px}
.sent{font-size:10.5px;font-weight:700;padding:3px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:.05em;flex-shrink:0;margin-top:2px;width:76px;text-align:center}
.sent.Tailwind{background:#E7F4EC;color:var(--green)}.sent.Headwind{background:#FBECE8;color:var(--red)}.sent.Neutral{background:#F1EEE7;color:var(--muted)}
.linklist a{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--line2);font-size:13px;color:var(--ink)}
.linklist a:last-child{border:0}.linklist a span{color:var(--muted);font-size:12px}
.pill{font-family:var(--sans);font-size:11px;padding:3px 9px;border-radius:999px;background:#F1EEE7;color:var(--muted);font-weight:600}
/* annual scan */
.ar-list{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.ar-btn{border:1px solid var(--line);background:#fff;border-radius:12px;padding:10px 14px;font-weight:600;font-size:13px;display:flex;align-items:center;gap:8px;color:var(--ink)}
.ar-btn:hover{border-color:var(--saffron);color:var(--saffron)}.ar-btn svg{width:18px;height:18px;color:var(--saffron)}
.drop{display:block;border:2px dashed #D8CFBD;border-radius:16px;padding:26px;text-align:center;color:var(--muted);background:#FCFAF5;transition:.15s;cursor:pointer}
.drop.over,.drop:hover{border-color:var(--saffron);background:#FDF4E8}
.drop b{color:var(--ink)}
.acc{border:1px solid var(--line2);border-radius:14px;margin-bottom:10px;background:#fff;overflow:hidden}
.acc summary{list-style:none;cursor:pointer;padding:14px 18px;display:flex;align-items:center;gap:12px;font-weight:600}
.acc summary::-webkit-details-marker{display:none}
.acc summary .cnt{margin-left:auto}
.acc summary::after{content:'›';font-size:20px;color:var(--muted);transition:.2s;margin-left:8px}
.acc[open] summary::after{transform:rotate(90deg)}
.acc .body{padding:0 18px 12px}
.quote{border-left:3px solid var(--saffron);background:#FCFAF5;padding:10px 14px;border-radius:0 10px 10px 0;margin:8px 0;font-size:13.5px}
.quote .pg{font-size:11px;color:var(--muted);font-weight:700;margin-top:4px}
.quote mark{background:#FBE7CC;padding:0 2px;border-radius:3px}
.spin{width:22px;height:22px;border:3px solid #EADFCB;border-top-color:var(--saffron);border-radius:50%;animation:spin .8s linear infinite;display:inline-block;vertical-align:middle}
/* industry */
.tw{list-style:none;padding:0;margin:0}.tw li{padding:8px 0 8px 22px;position:relative;font-size:13.5px;border-bottom:1px dashed var(--line)}.tw li:last-child{border:0}
.tw.up li::before{content:'↗';position:absolute;left:0;color:var(--green);font-weight:700}.tw.dn li::before{content:'↘';position:absolute;left:0;color:var(--red);font-weight:700}
.tw.kp li::before{content:'◆';position:absolute;left:2px;color:var(--saffron);font-size:10px;top:11px}.tw.au li::before{content:'§';position:absolute;left:2px;color:var(--blue);font-weight:700}
.gauge{width:220px;display:block;margin:0 auto}
.counts{display:flex;justify-content:center;gap:16px;font-size:12.5px;margin-top:6px}
.counts span b{font-size:16px;font-family:var(--serif)}
/* skeleton */
.sk{background:linear-gradient(90deg,#F0EBE0 0%,#F8F5EE 50%,#F0EBE0 100%);background-size:200% 100%;animation:sh 1.3s infinite;border-radius:10px;height:16px;margin:10px 0}
@keyframes sh{to{background-position:-200% 0}}
/* loader */
#loader{position:fixed;inset:0;background:rgba(14,27,51,.92);z-index:100;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;backdrop-filter:blur(4px)}
#loader .mandala{width:120px;height:120px;animation:spin 6s linear infinite}
#loader h3{margin-top:20px;font-size:22px}
#loader .steps{margin-top:16px;list-style:none;padding:0;font-size:14px;color:rgba(255,255,255,.55);min-width:320px}
#loader .steps li{padding:5px 0;transition:.3s}#loader .steps li.on{color:#fff}#loader .steps li.done{color:var(--saffron2)}
#loader .steps li::before{content:'○ ';}#loader .steps li.on::before{content:'◉ ';color:var(--saffron2)}#loader .steps li.done::before{content:'✓ '}
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--navy);color:#fff;padding:12px 18px;border-radius:12px;font-size:13.5px;box-shadow:0 10px 30px rgba(0,0,0,.25);z-index:120;display:none;max-width:560px}
footer.disc{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:16px;margin-top:20px}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.g3,.g4{grid-template-columns:1fr 1fr}.g-snap{grid-template-columns:1fr}.ranges{grid-template-columns:1fr 1fr}}
@media (max-width:860px){#report{grid-template-columns:1fr}.side{display:none}.g2,.g3,.g4,.features{grid-template-columns:1fr}.hero h1{font-size:44px}main{padding:20px}}
/* print */
@media print{.topbar,.side,.tb-actions,.btn,.tabs,.filters,.basis-toggle,#toast,.drop,.ar-list,.no-print{display:none!important}
#report{display:block}main{padding:0;max-width:none}body{background:#fff;font-size:12px}.card,.kpi{box-shadow:none;break-inside:avoid}
section.blk{break-inside:auto;page-break-inside:auto}.cohero{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.tabpane{display:block!important}.timeline{max-height:none}*{animation:none!important}.chart .ln{stroke-dashoffset:0}}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute">
  <defs>
    <g id="mandala">
      <g fill="none" stroke="#F3B263" stroke-width="1.2">
        <circle r="96"/><circle r="70"/><circle r="40"/><circle r="22"/>
        <g id="petal16"><path d="M0-96 C14-80 14-56 0-40 C-14-56 -14-80 0-96Z"/></g>
        <use href="#petal16" transform="rotate(22.5)"/><use href="#petal16" transform="rotate(45)"/><use href="#petal16" transform="rotate(67.5)"/>
        <use href="#petal16" transform="rotate(90)"/><use href="#petal16" transform="rotate(112.5)"/><use href="#petal16" transform="rotate(135)"/>
        <use href="#petal16" transform="rotate(157.5)"/><use href="#petal16" transform="rotate(180)"/><use href="#petal16" transform="rotate(202.5)"/>
        <use href="#petal16" transform="rotate(225)"/><use href="#petal16" transform="rotate(247.5)"/><use href="#petal16" transform="rotate(270)"/>
        <use href="#petal16" transform="rotate(292.5)"/><use href="#petal16" transform="rotate(315)"/><use href="#petal16" transform="rotate(337.5)"/>
        <g id="leaf8"><path d="M0-40 C10-34 10-26 0-22 C-10-26 -10-34 0-40Z"/></g>
        <use href="#leaf8" transform="rotate(45)"/><use href="#leaf8" transform="rotate(90)"/><use href="#leaf8" transform="rotate(135)"/>
        <use href="#leaf8" transform="rotate(180)"/><use href="#leaf8" transform="rotate(225)"/><use href="#leaf8" transform="rotate(270)"/><use href="#leaf8" transform="rotate(315)"/>
        <circle r="104" stroke-dasharray="2 6"/>
      </g>
    </g>
    <g id="logo">
      <circle r="30" fill="#0E1B33"/>
      <g fill="none" stroke="#D9822B" stroke-width="2.2">
        <g id="lp"><path d="M0-26 C7-20 7-12 0-8 C-7-12 -7-20 0-26Z"/></g>
        <use href="#lp" transform="rotate(45)"/><use href="#lp" transform="rotate(90)"/><use href="#lp" transform="rotate(135)"/>
        <use href="#lp" transform="rotate(180)"/><use href="#lp" transform="rotate(225)"/><use href="#lp" transform="rotate(270)"/><use href="#lp" transform="rotate(315)"/>
      </g>
      <path d="M-11 0 Q0-9 11 0 Q0 9-11 0Z" fill="#F3B263"/><circle r="3.6" fill="#0E1B33"/>
    </g>
    <symbol id="i-search" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm9 16-4.2-4.2"/></symbol>
    <symbol id="i-eye" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/></symbol>
    <symbol id="i-book" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Zm0 16a2 2 0 0 1 2-2h13"/></symbol>
    <symbol id="i-pct" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M19 5 5 19M7 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm10 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z"/></symbol>
    <symbol id="i-chart" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 3v18h18M7 15l4-4 3 3 5-6"/></symbol>
    <symbol id="i-users" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 9v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></symbol>
    <symbol id="i-pie" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" d="M21 12A9 9 0 1 1 12 3v9h9Z"/></symbol>
    <symbol id="i-bell" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9Zm4 13a2 2 0 0 0 4 0"/></symbol>
    <symbol id="i-scan" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M3 7V5a2 2 0 0 1 2-2h2m10 0h2a2 2 0 0 1 2 2v2m0 10v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 9h10M7 13h10M7 17h6"/></symbol>
    <symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path fill="none" stroke="currentColor" stroke-width="2" d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></symbol>
    <symbol id="i-print" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v7H6z"/></symbol>
    <symbol id="i-refresh" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/></symbol>
    <symbol id="i-file" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8M8 17h5"/></symbol>
  </defs>
</svg>

<header class="topbar">
  <div class="brand" onclick="goHome()"><svg viewBox="-32 -32 64 64"><use href="#logo"/></svg><div><b>ArthaDrishti</b><small>अर्थदृष्टि</small></div></div>
  <div class="tb-search hidden" id="tbSearchWrap">
    <input id="tbSearch" placeholder="Search another company…" autocomplete="off">
    <svg class="si"><use href="#i-search"/></svg>
    <div class="ac" id="tbAc"></div>
  </div>
  <div class="tb-actions hidden" id="tbActions">
    <button class="btn dark" onclick="refreshCo()" title="Fetch fresh data"><svg><use href="#i-refresh"/></svg>Refresh</button>
    <button class="btn dark" onclick="window.print()" title="Export to PDF"><svg><use href="#i-print"/></svg>Export PDF</button>
  </div>
</header>

<!-- ================= HOME ================= -->
<div id="home">
  <div class="hero">
    <svg class="mandala" viewBox="-110 -110 220 220"><use href="#mandala"/></svg>
    <svg class="mandala l" viewBox="-110 -110 220 220"><use href="#mandala"/></svg>
    <div class="hero-in">
      <span class="eyebrow">◈ Investment analysis for Chartered Accountants</span>
      <h1>Artha<span>Drishti</span></h1>
      <div class="deva">अर्थदृष्टि · the vision of wealth</div>
      <p class="lead">Three years of audited financials, ratios, peer face-offs, AGM/EGM disclosures, annual-report highlights and industry pulse, condensed into one decision-ready view.</p>
      <div class="big-search">
        <input id="heroSearch" placeholder="Type a company — e.g. Ambuja Cements, UltraTech, HDFC Bank…" autocomplete="off" autofocus>
        <svg class="si"><use href="#i-search"/></svg>
        <button class="go" onclick="document.getElementById('heroSearch').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))">Analyse →</button>
        <div class="ac" id="heroAc"></div>
      </div>
      <div class="chips" id="chips"></div>
    </div>
  </div>
  <div class="features">
    <div class="feat"><div class="fi"><svg><use href="#i-book"/></svg></div><h3>3-year audited statements</h3><p>P&L, balance sheet and cash flow side by side, with year-on-year movement highlighted.</p></div>
    <div class="feat"><div class="fi"><svg><use href="#i-pct"/></svg></div><h3>Ratio engine & red flags</h3><p>20+ ratios across growth, returns, leverage, working capital and cash quality, plus automatic green and red flags.</p></div>
    <div class="feat"><div class="fi"><svg><use href="#i-users"/></svg></div><h3>Peer face-off</h3><p>Head-to-head against any peer (Ambuja vs UltraTech, say), with the full peer universe and medians.</p></div>
    <div class="feat"><div class="fi"><svg><use href="#i-bell"/></svg></div><h3>AGM / EGM & developments</h3><p>Exchange disclosures sorted into AGM/EGM, capex, M&A, dividends, ratings and management changes.</p></div>
    <div class="feat"><div class="fi"><svg><use href="#i-scan"/></svg></div><h3>Annual report deep scan</h3><p>Pulls KAMs, contingent liabilities, capex plans, RPTs and outlook straight from the annual report PDF, with page references.</p></div>
    <div class="feat"><div class="fi"><svg><use href="#i-globe"/></svg></div><h3>Industry pulse</h3><p>Structural drivers, KPIs, audit focus areas and live headlines tagged as tailwinds or headwinds.</p></div>
  </div>
  <div class="home-foot">Data: Screener.in (audited annual figures), BSE/NSE disclosures, Google News · Analytical aid only — the investment decision rests with the professional.</div>
</div>

<!-- ================= REPORT ================= -->
<div id="report" class="hidden">
  <aside class="side">
    <div class="co"><b id="sideName">—</b><span id="sideSym"></span></div>
    <nav class="nav" id="nav">
      <a href="#s-overview" class="active"><svg><use href="#i-eye"/></svg>Overview</a>
      <a href="#s-snapshot"><svg><use href="#i-pie"/></svg>Decision snapshot</a>
      <a href="#s-financials"><svg><use href="#i-book"/></svg>Audited financials</a>
      <a href="#s-ratios"><svg><use href="#i-pct"/></svg>Ratio analysis</a>
      <a href="#s-trends"><svg><use href="#i-chart"/></svg>Trend analysis</a>
      <a href="#s-peers"><svg><use href="#i-users"/></svg>Peer analysis</a>
      <a href="#s-holding"><svg><use href="#i-pie"/></svg>Shareholding</a>
      <a href="#s-devs"><svg><use href="#i-bell"/></svg>AGM / EGM & news</a>
      <a href="#s-annual"><svg><use href="#i-scan"/></svg>Annual report scan</a>
      <a href="#s-industry"><svg><use href="#i-globe"/></svg>Industry analysis</a>
    </nav>
    <div class="disc">Scores and flags are rule-based analytical aids, not investment advice. Verify against the source filings before any decision.</div>
  </aside>
  <main id="main"></main>
</div>

<div id="loader" class="hidden">
  <svg class="mandala" viewBox="-110 -110 220 220"><use href="#mandala"/></svg>
  <h3 id="loaderTitle">Analysing…</h3>
  <ul class="steps" id="loaderSteps"></ul>
</div>
<div id="toast"></div>

<script>
/* ===== ArthaDrishti shared UI library: formatters, SVG charts, autocomplete ===== */
const AD = (() => {
  const C = {navy:'#0E1B33', saffron:'#D9822B', gold:'#B8892D', green:'#1E8A5A', red:'#C2412D', blue:'#2F5DA8',
             teal:'#1C7C86', grey:'#8A93A3', ink:'#1B2333', line:'#E6E0D3', plum:'#7A4E8C'};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const isNum = v => typeof v === 'number' && isFinite(v);
  const inr = (v, d=0) => isNum(v) ? v.toLocaleString('en-IN', {maximumFractionDigits:d, minimumFractionDigits:d}) : '—';
  const cr = v => isNum(v) ? '₹' + inr(v, Math.abs(v) < 100 ? 1 : 0) + ' Cr' : '—';
  function fmt(v, unit) {
    if (!isNum(v)) return '—';
    switch (unit) {
      case '%': return v.toFixed(1) + '%';
      case 'x': return v.toFixed(2) + 'x';
      case 'd': return Math.round(v) + ' d';
      case 'cr': return cr(v);
      case 'rs': return '₹' + v.toFixed(2);
      default: return inr(v, 2);
    }
  }
  const STMT_UNIT = {opm:'%', tax_pct:'%', payout:'%', eps:'rs'};
  const stmtFmt = (k, v) => STMT_UNIT[k] ? fmt(v, STMT_UNIT[k]) : (isNum(v) ? inr(v, Math.abs(v) < 100 ? 1 : 0) : '—');
  function delta(cur, prev, better='high') {
    if (!isNum(cur) || !isNum(prev) || prev === 0) return {txt:'', cls:'flat'};
    const ch = (cur - prev) / Math.abs(prev) * 100;
    const up = ch > 0.5, dn = ch < -0.5;
    let cls = 'flat';
    if (better === 'high') cls = up ? 'good' : dn ? 'bad' : 'flat';
    else if (better === 'low') cls = up ? 'bad' : dn ? 'good' : 'flat';
    return {txt: (up ? '▲ ' : dn ? '▼ ' : '● ') + Math.abs(ch).toFixed(Math.abs(ch) < 10 ? 1 : 0) + '%', cls};
  }
  const STMT_BETTER = {expenses:'low', interest:'low', dep:'neutral', borrowings:'low', other_liab:'neutral',
                       tax_pct:'neutral', total_liab:'neutral', other_assets:'neutral', cfi:'neutral', cff:'neutral', net_cf:'neutral', deposits:'high'};

  /* ---------- nice axis ---------- */
  function niceScale(min, max, ticks=5) {
    if (min === max) { max = min + 1; }
    const range = max - min, rough = range / ticks;
    const p = Math.pow(10, Math.floor(Math.log10(rough))), f = rough / p;
    const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const out = []; for (let v = lo; v <= hi + step/2; v += step) out.push(+v.toFixed(10));
    return {lo, hi, ticks: out};
  }
  const shortNum = v => { const a = Math.abs(v);
    return a >= 100000 ? (v/100000).toFixed(1) + 'L' : a >= 1000 ? (v/1000).toFixed(a >= 10000 ? 0 : 1) + 'k' : (+v.toFixed(1)).toString(); };

  /* ---------- combo chart: bars (left axis) + lines (right axis) ---------- */
  function combo(el, o) {
    const labels = o.labels || [], n = labels.length;
    if (!n) { el.innerHTML = '<div class="empty">No data</div>'; return; }
    const bars = (o.bars || []).filter(s => s.data && s.data.some(isNum));
    const lines = (o.lines || []).filter(s => s.data && s.data.some(isNum));
    if (!bars.length && !lines.length) { el.innerHTML = '<div class="empty">Not reported for this company</div>'; return; }
    const lineOnly = !bars.length;
    const W = o.w || 640, H = o.h || 270, pl = 52, pr = (!lineOnly && lines.length) ? 46 : 14, pt = 14, pb = 34;
    const bv = (lineOnly ? lines : bars).flatMap(s => s.data.filter(isNum));
    const L = niceScale(Math.min(0, ...bv), Math.max(0, ...bv, lineOnly ? 1 : 0));
    const lv = lines.flatMap(s => s.data.filter(isNum));
    const R = (!lineOnly && lv.length) ? niceScale(Math.min(0, ...lv), Math.max(...lv, 1)) : null;
    const lu = lineOnly ? (o.unitR || '') : '';
    const iw = W - pl - pr, ih = H - pt - pb, gw = iw / n;
    const y = v => pt + ih - (v - L.lo) / (L.hi - L.lo) * ih;
    const yr = v => pt + ih - (v - R.lo) / (R.hi - R.lo) * ih;
    let s = `<svg viewBox="0 0 ${W} ${H}" class="chart" preserveAspectRatio="xMidYMid meet">`;
    L.ticks.forEach(t => { s += `<line x1="${pl}" x2="${W-pr}" y1="${y(t)}" y2="${y(t)}" class="grid${t===0?' zero':''}"/>` +
      `<text x="${pl-8}" y="${y(t)+4}" class="ax" text-anchor="end">${shortNum(t)}${lu}</text>`; });
    if (R) R.ticks.forEach(t => { s += `<text x="${W-pr+8}" y="${yr(t)+4}" class="ax">${shortNum(t)}${o.unitR||''}</text>`; });
    const bw = Math.min(34, gw * 0.72 / Math.max(1, bars.length));
    labels.forEach((lb, i) => {
      const cx = pl + gw * i + gw / 2;
      if (n <= 14 || i % 2 === 0) s += `<text x="${cx}" y="${H-12}" class="ax" text-anchor="middle">${esc(lb)}</text>`;
      bars.forEach((b, j) => {
        const v = b.data[i]; if (!isNum(v)) return;
        const x = cx - (bars.length * bw) / 2 + j * bw + 1, y0 = y(Math.max(0, v)), h = Math.abs(y(v) - y(0));
        s += `<rect x="${x}" y="${y0}" width="${bw-2}" height="${Math.max(h, 0.5)}" rx="3" fill="${v<0?C.red:b.color}" class="bar" style="animation-delay:${i*40}ms"><title>${esc(b.name)} · ${esc(lb)}: ${inr(v, 1)}${b.unit||''}</title></rect>`;
      });
    });
    lines.forEach(ln => {
      const sc = R ? yr : y; let d = '', started = false;
      ln.data.forEach((v, i) => { if (!isNum(v)) { started = false; return; }
        const cx = pl + gw * i + gw / 2; d += (started ? 'L' : 'M') + cx + ' ' + sc(v) + ' '; started = true; });
      s += `<path d="${d}" fill="none" stroke="${ln.color}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round" class="ln"/>`;
      ln.data.forEach((v, i) => { if (!isNum(v)) return; const cx = pl + gw * i + gw / 2;
        s += `<circle cx="${cx}" cy="${sc(v)}" r="3.6" fill="#fff" stroke="${ln.color}" stroke-width="2"><title>${esc(ln.name)} · ${esc(labels[i])}: ${inr(v,1)}${o.unitR||''}</title></circle>`; });
    });
    s += '</svg>';
    const legend = [...bars.map(b => [b.name, b.color, 'sq']), ...lines.map(l => [l.name, l.color, 'ln'])]
      .map(([nm, c, t]) => `<span class="lg"><i class="${t}" style="background:${c}"></i>${esc(nm)}</span>`).join('');
    el.innerHTML = `<div class="legend">${legend}</div>` + s;
  }

  /* ---------- radar ---------- */
  function radar(el, axes, o={}) {
    const W = o.size || 320, cx = W/2, cy = W/2 + 4, r = W/2 - 56, n = axes.length;
    const pt = (i, v) => { const a = -Math.PI/2 + i * 2 * Math.PI / n; return [cx + Math.cos(a) * r * v/10, cy + Math.sin(a) * r * v/10]; };
    let s = `<svg viewBox="0 0 ${W} ${W+8}" class="chart radar">`;
    [2.5, 5, 7.5, 10].forEach(k => { s += `<polygon points="${axes.map((_, i) => pt(i, k).join(',')).join(' ')}" class="rgrid"/>`; });
    axes.forEach((a, i) => { const [x, y2] = pt(i, 10); s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y2}" class="rgrid"/>`;
      const [lx, ly] = pt(i, 12.6);
      s += `<text x="${lx}" y="${ly}" text-anchor="middle" class="rlab">${esc(a.axis)}</text><text x="${lx}" y="${ly+14}" text-anchor="middle" class="rval">${a.score}</text>`; });
    (o.series || [{data: axes.map(a => a.score), color: C.saffron}]).forEach(se => {
      s += `<polygon points="${se.data.map((v, i) => pt(i, v).join(',')).join(' ')}" fill="${se.color}" fill-opacity=".22" stroke="${se.color}" stroke-width="2.4" class="rpoly"/>`;
      se.data.forEach((v, i) => { const [x, y2] = pt(i, v); s += `<circle cx="${x}" cy="${y2}" r="3.5" fill="${se.color}"/>`; });
    });
    el.innerHTML = s + '</svg>';
  }

  /* ---------- score ring ---------- */
  function ring(el, v, label) {
    const r = 46, c = 2 * Math.PI * r, p = Math.max(0, Math.min(10, v || 0)) / 10;
    const col = v >= 7 ? C.green : v >= 5 ? C.gold : C.red;
    el.innerHTML = `<svg viewBox="0 0 120 120" class="ring"><circle cx="60" cy="60" r="${r}" class="ring-bg"/>
      <circle cx="60" cy="60" r="${r}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${c*(1-p)}" transform="rotate(-90 60 60)" class="ring-fg"/>
      <text x="60" y="58" text-anchor="middle" class="ring-v">${isNum(v) ? v.toFixed(1) : '—'}</text>
      <text x="60" y="76" text-anchor="middle" class="ring-l">${esc(label || 'out of 10')}</text></svg>`;
  }

  /* ---------- donut ---------- */
  function donut(el, parts) {
    const tot = parts.reduce((a, p) => a + (isNum(p.v) ? p.v : 0), 0) || 1, r = 52, c = 2 * Math.PI * r;
    let off = 0, s = `<svg viewBox="0 0 140 140" class="chart donut">`;
    parts.forEach(p => { if (!isNum(p.v) || p.v <= 0) return; const len = p.v / tot * c;
      s += `<circle cx="70" cy="70" r="${r}" fill="none" stroke="${p.c}" stroke-width="20" stroke-dasharray="${len} ${c-len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"><title>${esc(p.n)}: ${p.v.toFixed(2)}%</title></circle>`; off += len; });
    s += '</svg>';
    el.innerHTML = s + `<div class="legend col">${parts.filter(p => isNum(p.v)).map(p => `<span class="lg"><i class="sq" style="background:${p.c}"></i>${esc(p.n)} <b>${p.v.toFixed(2)}%</b></span>`).join('')}</div>`;
  }

  /* ---------- gauge (0-100) ---------- */
  function gauge(el, v, label) {
    const a = Math.PI * (1 - Math.max(0, Math.min(100, v)) / 100), x = 100 + 78 * Math.cos(a), y = 100 - 78 * Math.sin(a);
    const col = v >= 60 ? C.green : v >= 45 ? C.gold : C.red;
    el.innerHTML = `<svg viewBox="0 0 200 118" class="gauge">
      <path d="M22 100 A78 78 0 0 1 178 100" fill="none" stroke="#EDE7DA" stroke-width="16" stroke-linecap="round"/>
      <path d="M22 100 A78 78 0 0 1 ${x} ${y}" fill="none" stroke="${col}" stroke-width="16" stroke-linecap="round"/>
      <text x="100" y="92" text-anchor="middle" class="ring-v">${Math.round(v)}</text>
      <text x="100" y="112" text-anchor="middle" class="ring-l">${esc(label)}</text></svg>`;
  }

  /* ---------- sparkline ---------- */
  function spark(vals, color) {
    const v = vals.filter(isNum); if (v.length < 2) return '';
    const mn = Math.min(...v), mx = Math.max(...v), W = 70, H = 22;
    const pts = vals.map((x, i) => isNum(x) ? `${(i/(vals.length-1))*W},${H - 2 - ((x-mn)/((mx-mn)||1))*(H-4)}` : null).filter(Boolean);
    return `<svg viewBox="0 0 ${W} ${H}" class="spark"><polyline points="${pts.join(' ')}" fill="none" stroke="${color||C.saffron}" stroke-width="1.8" stroke-linecap="round"/></svg>`;
  }

  /* ---------- autocomplete ---------- */
  function autocomplete(input, box, onPick) {
    let t = null, ctl = null, items = [], idx = -1;
    const render = () => {
      if (!items.length) { box.innerHTML = input.value.trim().length > 1 ? `<div class="ac-empty">No match — press Enter to try “${esc(input.value.trim().toUpperCase())}” as an NSE symbol</div>` : ''; box.classList.toggle('open', input.value.trim().length > 1); return; }
      const q = input.value.trim().toLowerCase();
      const hl = s => { const i = s.toLowerCase().indexOf(q); return i < 0 ? esc(s) : esc(s.slice(0, i)) + '<mark>' + esc(s.slice(i, i + q.length)) + '</mark>' + esc(s.slice(i + q.length)); };
      box.innerHTML = items.map((it, i) => `<div class="ac-item${i===idx?' active':''}" data-i="${i}">
        <span class="ac-ic">${esc(it.name.replace(/^the /i,'').charAt(0))}</span><span class="ac-name">${hl(it.name)}</span><span class="ac-sym">${esc(it.symbol)}</span></div>`).join('');
      box.classList.add('open');
    };
    input.addEventListener('input', () => {
      clearTimeout(t); const q = input.value.trim(); idx = -1;
      if (q.length < 1) { items = []; box.classList.remove('open'); return; }
      t = setTimeout(async () => {
        if (ctl) ctl.abort(); ctl = new AbortController();
        try { const r = await fetch('/api/search?q=' + encodeURIComponent(q), {signal: ctl.signal}); items = await r.json(); render(); } catch (e) {}
      }, 120);
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { idx = Math.min(items.length - 1, idx + 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { idx = Math.max(0, idx - 1); render(); e.preventDefault(); }
      else if (e.key === 'Enter') { e.preventDefault();
        const it = items[idx >= 0 ? idx : 0];
        if (it) pick(it); else if (input.value.trim()) pick({symbol: input.value.trim().toUpperCase(), name: input.value.trim().toUpperCase(), url: '/company/' + input.value.trim().toUpperCase() + '/consolidated/'}); }
      else if (e.key === 'Escape') box.classList.remove('open');
    });
    box.addEventListener('mousedown', e => { const el = e.target.closest('.ac-item'); if (el) { e.preventDefault(); pick(items[+el.dataset.i]); } });
    input.addEventListener('blur', () => setTimeout(() => box.classList.remove('open'), 150));
    input.addEventListener('focus', () => { if (items.length) box.classList.add('open'); });
    function pick(it) { box.classList.remove('open'); input.value = it.name; input.blur(); onPick(it); }
  }

  async function getJSON(url, opts) {
    const r = await fetch(url, opts); let js;
    try { js = await r.json(); } catch (e) { throw new Error('Server returned an unreadable response'); }
    if (!r.ok || js.error) throw new Error(js.error || ('HTTP ' + r.status));
    return js;
  }
  function friendlyError(msg) {
    msg = String(msg || '');
    if (/403|429|Forbidden|Too Many/i.test(msg)) return 'Screener.in is rate-limiting requests right now. Wait a minute and press Retry.';
    if (/404|Not Found|No financial statements/i.test(msg)) return 'Could not find financial statements for this company. Check the name/symbol or try the standalone basis.';
    if (/Max retries|Connection|getaddrinfo|timed out|NameResolution/i.test(msg)) return 'No internet connection, or the data source is unreachable. Check your connection and retry.';
    return msg;
  }
  const DEV_COLORS = {gold: C.gold, green: C.green, blue: C.blue, saffron: C.saffron, navy: C.navy, teal: C.teal, red: C.red, grey: C.grey};

  return {C, esc, isNum, inr, cr, fmt, stmtFmt, delta, STMT_BETTER, combo, radar, ring, donut, gauge, spark,
          autocomplete, getJSON, friendlyError, DEV_COLORS};
})();

</script>
<script>
const {C, esc, isNum, inr, cr, fmt, stmtFmt, delta, STMT_BETTER} = AD;
let CO = null, CUR = null;
const $ = id => document.getElementById(id);

/* ---------- home ---------- */
const CHIPS = [['Ambuja Cements','AMBUJACEM'],['UltraTech Cement','ULTRACEMCO'],['Reliance','RELIANCE'],['HDFC Bank','HDFCBANK'],['TCS','TCS'],['Asian Paints','ASIANPAINT'],['Sun Pharma','SUNPHARMA'],['Maruti Suzuki','MARUTI']];
$('chips').innerHTML = CHIPS.map(([n, s]) => `<button class="chip" onclick="openCo({name:'${n}',symbol:'${s}',url:'/company/${s}/consolidated/'})">${n}</button>`).join('');
AD.autocomplete($('heroSearch'), $('heroAc'), openCo);
AD.autocomplete($('tbSearch'), $('tbAc'), openCo);

function goHome() { $('report').classList.add('hidden'); $('home').classList.remove('hidden'); $('tbSearchWrap').classList.add('hidden'); $('tbActions').classList.add('hidden'); history.replaceState(null, '', '/'); window.scrollTo(0, 0); }
function toast(msg, ms=3800) { const t = $('toast'); t.textContent = msg; t.style.display = 'block'; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms); }

const STEPS = ['Fetching audited annual statements', 'Computing 20+ financial ratios', 'Mapping the peer universe', 'Classifying AGM / EGM & exchange disclosures', 'Running the insight & red-flag engine'];
let stepTimer = null;
function showLoader(name) {
  $('loaderTitle').textContent = 'Analysing ' + name;
  $('loaderSteps').innerHTML = STEPS.map(s => `<li>${s}</li>`).join('');
  $('loader').classList.remove('hidden');
  let i = 0; const lis = [...$('loaderSteps').children]; lis[0].classList.add('on');
  stepTimer = setInterval(() => { if (i < lis.length - 1) { lis[i].className = 'done'; i++; lis[i].classList.add('on'); } }, 700);
}
function hideLoader() { clearInterval(stepTimer); $('loader').classList.add('hidden'); }

async function openCo(it, force=false) {
  CUR = it; showLoader(it.name || it.symbol);
  try {
    CO = await AD.getJSON('/api/company?url=' + encodeURIComponent(it.url) + (force ? '&force=1' : ''));
    hideLoader(); renderReport();
    history.replaceState(null, '', '#' + CO.symbol);
  } catch (e) {
    hideLoader();
    $('home').classList.add('hidden'); $('report').classList.remove('hidden');
    $('main').innerHTML = `<div class="card" style="max-width:640px;margin:60px auto;text-align:center"><h2>Could not load ${esc(it.name || it.symbol)}</h2>
      <p class="note err" style="margin-top:14px">${esc(AD.friendlyError(e.message))}</p>
      <button class="btn primary" onclick='openCo(${JSON.stringify(it)}, true)'>Retry</button> <button class="btn" onclick="goHome()">Back</button></div>`;
    $('tbSearchWrap').classList.remove('hidden');
  }
}
function refreshCo() { if (CUR) openCo(CUR, true); }
function switchBasis(b) {
  if (!CO) return; const base = '/company/' + CO.symbol + '/';
  openCo({name: CO.name, symbol: CO.symbol, url: b === 'c' ? base + 'consolidated/' : base}, true);
}

/* ---------- render report ---------- */
function renderReport() {
  $('home').classList.add('hidden'); $('report').classList.remove('hidden');
  $('tbSearchWrap').classList.remove('hidden'); $('tbActions').classList.remove('hidden'); $('tbSearch').value = '';
  $('sideName').textContent = CO.name; $('sideSym').textContent = CO.symbol + ' · ' + CO.basis;
  const s = CO.snapshot;
  const yl = CO.year_labels;
  $('main').innerHTML = `
  ${secOverview(s)}
  ${secSnapshot()}
  ${secFinancials()}
  ${secRatios()}
  ${secTrends()}
  <section class="blk" id="s-peers"><div class="blk-h"><div><div class="kicker">Relative strength</div><h2>Peer analysis</h2><div class="sub">Head-to-head on audited numbers, plus the full peer universe</div></div></div><div id="peerBox"><div class="card"><div class="sk"></div><div class="sk" style="width:70%"></div><div class="sk"></div></div></div></section>
  ${secHolding()}
  <section class="blk" id="s-devs"><div class="blk-h"><div><div class="kicker">Corporate developments</div><h2>AGM / EGM, disclosures & news</h2><div class="sub">Exchange filings auto-classified · news tagged by sentiment</div></div></div><div id="devBox"></div></section>
  ${secAnnual()}
  <section class="blk" id="s-industry"><div class="blk-h"><div><div class="kicker">Industry analysis</div><h2>${esc(CO.playbook.title)} industry — the whole picture</h2><div class="sub">Structural framework, audit lens, peer-set statistics and live industry headlines</div></div></div><div id="indBox"></div></section>
  <footer class="disc"><b>Sources & method.</b> Annual figures are audited numbers as compiled by Screener.in (${esc(CO.basis)} basis), fetched ${esc(CO.fetched_at || '')}. Disclosures link to BSE/NSE filings. News via Google News RSS, sentiment tagged with a finance lexicon. Ratios: ROCE = EBIT / (Net worth + Borrowings); FCF ≈ CFO + CFI; CAGR over the audited window shown. Scores are rule-based aids, not recommendations. ArthaDrishti v1.0.</footer>`;
  drawCharts(); renderDevs(null); renderIndustry(null); initSpy();
  loadPeers(); loadNews();
  window.scrollTo(0, 0);
}

function secOverview(s) {
  const tiles = [
    ['Market cap', cr(s.mcap), s.mcap_rank ? '' : ''], ['Current price', isNum(s.price) ? '₹' + inr(s.price, 2) : '—', isNum(s.off_high) ? s.off_high + '% from 52w high' : ''],
    ['P/E', fmt(s.pe, 'x'), CO.peer_stats.median_pe ? 'Peer median ' + CO.peer_stats.median_pe + 'x' : ''], ['P/B', fmt(s.pb, 'x'), 'Book value ₹' + inr(s.book_value, 0)],
    ['EV / EBITDA', fmt(s.ev_ebitda, 'x'), 'approx., EV = Mcap + debt'], ['ROCE', fmt(s.roce, '%'), CO.peer_stats.median_roce ? 'Peer median ' + CO.peer_stats.median_roce + '%' : ''],
    ['ROE', fmt(s.roe, '%'), ''], ['Dividend yield', fmt(s.div_yield, '%'), ''], ['52-week range', isNum(s.high) ? '₹' + inr(s.low, 0) + ' – ' + inr(s.high, 0) : '—', ''],
    ['Earnings yield', fmt(s.earnings_yield, '%'), 'Inverse of P/E']];
  const links = Object.entries(CO.links).map(([k, v]) => `<a href="${esc(v)}" target="_blank" rel="noopener" id="lnk-${k.replace(/\W/g,'')}">${esc(k)} ↗</a>`).join('');
  const isC = CO.basis === 'Consolidated';
  return `<section class="blk" id="s-overview">
  ${CO.cache === 'stale' ? `<div class="note err">${esc(CO.cache_note)}</div>` : ''}
  <div class="cohero"><svg class="mandala" viewBox="-110 -110 220 220"><use href="#mandala"/></svg>
    <div class="basis-toggle"><button class="${isC?'on':''}" onclick="switchBasis('c')">Consolidated</button><button class="${!isC?'on':''}" onclick="switchBasis('s')">Standalone</button></div>
    <div class="kicker" style="color:var(--saffron2);position:relative">${esc(CO.symbol)}</div>
    <h1>${esc(CO.name)}</h1>
    <div class="crumbs">${CO.sector_path.map(x => `<span class="crumb">${esc(x)}</span>`).join('')}</div>
    <div class="meta"><span class="badge basis">${esc(CO.basis)}</span><span class="badge ${esc(CO.cache)}">${CO.cache === 'live' ? 'Live data' : CO.cache === 'fresh' ? 'Cached today' : 'Offline copy'}</span><span>Updated ${esc(CO.fetched_at || '')}</span><span>Audited window: ${esc(CO.year_labels.join(' · '))}</span></div>
    <div class="qlinks">${links}</div>
  </div>
  <div class="kpis">${tiles.map(([l, v, sub]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(sub)}</div></div>`).join('')}</div>
  ${CO.about ? `<div class="about"><b>About.</b> ${esc(CO.about)}</div>` : ''}
  ${CO.key_points ? `<div class="about"><b>Key points.</b> ${esc(CO.key_points)}</div>` : ''}
  </section>`;
}

function secSnapshot() {
  return `<section class="blk" id="s-snapshot"><div class="blk-h"><div><div class="kicker">For the decision-maker</div><h2>Decision snapshot</h2><div class="sub">The audited window read in about two minutes</div></div></div>
  <div class="grid g-snap">
    <div class="card score-wrap"><h3 style="align-self:flex-start">ArthaDrishti scorecard</h3><div id="ring"></div><div id="radar" style="width:100%;display:flex;justify-content:center"></div><div class="score-note">Rule-based 0–10 scores · an aid, not a recommendation</div></div>
    <div class="card"><h3>Key takeaways</h3>
      <ul class="insights">${CO.insights.map(i => `<li><span class="dot ${i.tone}"></span><span>${esc(i.text)}</span></li>`).join('') || '<li>No insights generated.</li>'}</ul>
      <div class="flags">
        <div class="flagbox g"><h4>▲ Green flags</h4><ul>${CO.green_flags.map(f => `<li>${esc(f)}</li>`).join('') || '<li style="list-style:none;margin-left:-18px;color:var(--muted)">None triggered</li>'}</ul></div>
        <div class="flagbox r"><h4>▼ Red flags / watch-list</h4><ul>${CO.red_flags.map(f => `<li>${esc(f)}</li>`).join('') || '<li style="list-style:none;margin-left:-18px;color:var(--muted)">None triggered</li>'}</ul></div>
      </div>
    </div>
  </div></section>`;
}

function stmtTable(key) {
  const rows = CO.statements[key] || [], yl = CO.year_labels;
  const ttm = key === 'pl' && CO.ttm;
  const em = new Set(['op_profit', 'np', 'net_worth', 'total_assets', 'cfo', 'fcf']);
  let h = `<table class="fin"><thead><tr><th>₹ Crore</th>${yl.map(y => `<th>${y}</th>`).join('')}${ttm ? '<th>TTM</th>' : ''}<th>Latest YoY</th><th>Trend</th></tr></thead><tbody>`;
  rows.forEach(r => {
    const v = r.values, n = v.length;
    const better = STMT_BETTER[r.key] || 'high';
    const d = (r.key === 'opm' || r.key === 'tax_pct' || r.key === 'payout') ?
      (isNum(v[n-1]) && isNum(v[n-2]) ? {txt: ((v[n-1]-v[n-2])>=0?'▲ ':'▼ ') + Math.abs((v[n-1]-v[n-2])*100).toFixed(0) + ' bps', cls: better==='neutral'||r.key!=='opm' ? 'flat' : (v[n-1]>=v[n-2]?'good':'bad')} : {txt:'',cls:'flat'})
      : delta(v[n-1], v[n-2], better === 'neutral' ? 'none' : better);
    const tv = ttm ? (CO.ttm[r.key] ?? null) : undefined;
    h += `<tr class="${em.has(r.key) ? 'em' : ''}"><td class="lbl">${esc(r.label)}</td>${v.map(x => `<td>${stmtFmt(r.key, x)}</td>`).join('')}${ttm ? `<td>${tv === undefined || tv === null ? '—' : stmtFmt(r.key, tv)}</td>` : ''}<td>${d.txt ? `<span class="chg ${d.cls}">${d.txt}</span>` : ''}</td><td>${AD.spark(v, C.saffron)}</td></tr>`;
  });
  return h + '</tbody></table>';
}

function secFinancials() {
  return `<section class="blk" id="s-financials"><div class="blk-h"><div><div class="kicker">Audited annual statements</div><h2>Financials — last 3 financial years</h2><div class="sub">${esc(CO.basis)} · ₹ crore unless stated · YoY = latest year vs prior year</div></div>
    <div class="tabs" id="finTabs"><button class="on" data-t="pl">Profit & Loss</button><button data-t="bs">Balance Sheet</button><button data-t="cf">Cash Flow</button></div></div>
    ${CO.period_notes.map(n => `<div class="note">⚠ ${esc(n)}</div>`).join('')}
    <div class="card" style="padding:8px 8px 4px">
      <div class="tabpane" data-p="pl">${stmtTable('pl')}</div>
      <div class="tabpane hidden" data-p="bs"><h3 class="print-only" style="display:none">Balance sheet</h3>${stmtTable('bs')}</div>
      <div class="tabpane hidden" data-p="cf">${stmtTable('cf')}</div>
    </div></section>`;
}

function secRatios() {
  const yl = CO.year_labels;
  return `<section class="blk" id="s-ratios"><div class="blk-h"><div><div class="kicker">Ratio engine</div><h2>Ratio analysis</h2><div class="sub">Hover on a ratio to see how to read it · the trend chip compares the latest year with the first year of the window</div></div></div>
  <div class="grid g2">${CO.ratio_groups.map(g => `<div class="card rgroup"><h3>${esc(g.group)}</h3>
    <div class="rrow h"><span>Ratio</span>${yl.map(y => `<span class="v">${y}</span>`).join('')}<span class="t">Trend</span></div>
    ${g.rows.map(r => { const v = r.values, f = v.find(isNum), l = v[v.length-1];
      const d = r.unit === '%' || r.unit === 'd' || r.unit === 'x' ? (() => { if (!isNum(l) || !isNum(f) || v.indexOf(f) === v.length-1) return {txt:'',cls:'flat'};
        const diff = l - f, good = r.better === 'high' ? diff > 0 : r.better === 'low' ? diff < 0 : null;
        const t = r.unit === '%' ? Math.abs(diff).toFixed(1) + ' pp' : r.unit === 'd' ? Math.abs(Math.round(diff)) + ' d' : Math.abs(diff).toFixed(2) + 'x';
        return {txt: (diff >= 0 ? '▲ ' : '▼ ') + t, cls: good === null || Math.abs(diff) < 1e-9 ? 'flat' : good ? 'good' : 'bad'}; })() : delta(l, f, r.better);
      return `<div class="rrow"><span><span class="tip" data-tip="${esc(r.hint)}">${esc(r.label)}</span></span>${v.map((x, i) => `<span class="v${i===v.length-1?' last':''}">${fmt(x, r.unit)}</span>`).join('')}<span class="t">${d.txt ? `<span class="chg ${d.cls}">${d.txt}</span>` : ''}</span></div>`; }).join('')}
  </div>`).join('')}</div></section>`;
}

function secTrends() {
  const R = CO.ranges.slice(0, 4);
  return `<section class="blk" id="s-trends"><div class="blk-h"><div><div class="kicker">Screener-style trend analysis</div><h2>Long-term trends</h2><div class="sub">Up to 10 financial years · compounded growth · quarterly momentum</div></div></div>
  ${R.length ? `<div class="ranges" style="margin-bottom:18px">${R.map(r => `<div class="range"><b>${esc(r.title)}</b>${r.items.map(([k, v]) => `<div><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('')}</div>`).join('')}</div>` : ''}
  <div class="grid g2">
    <div class="card"><h3>Revenue, EBITDA & operating margin</h3><div id="ch-rev"></div></div>
    <div class="card"><h3>Net profit vs cash from operations</h3><div id="ch-cash"></div></div>
    <div class="card"><h3>Return ratios (ROCE & ROE)</h3><div id="ch-ret"></div></div>
    <div class="card"><h3>Borrowings vs net worth</h3><div id="ch-lev"></div></div>
    <div class="card"><h3>Quarterly momentum (last 8 quarters)</h3><div id="ch-q"></div></div>
    <div class="card"><h3>EPS & dividend payout</h3><div id="ch-eps"></div></div>
  </div>
  ${(CO.pros.length || CO.cons.length) ? `<div class="grid g2" style="margin-top:18px"><div class="card"><h3>Strengths noted by Screener</h3><ul class="pc pros">${CO.pros.map(p => `<li>${esc(p)}</li>`).join('') || '<li>—</li>'}</ul></div>
    <div class="card"><h3>Weaknesses noted by Screener</h3><ul class="pc cons">${CO.cons.map(p => `<li>${esc(p)}</li>`).join('') || '<li>—</li>'}</ul></div></div>` : ''}
  </section>`;
}

function secHolding() {
  const sh = CO.shareholding;
  if (!sh.cols || !sh.cols.length) return `<section class="blk" id="s-holding"><div class="blk-h"><div><div class="kicker">Ownership</div><h2>Shareholding pattern</h2></div></div><div class="card empty">Shareholding data unavailable</div></section>`;
  return `<section class="blk" id="s-holding"><div class="blk-h"><div><div class="kicker">Ownership</div><h2>Shareholding pattern</h2><div class="sub">Promoter, institutional and public holding over recent quarters</div></div></div>
  <div class="grid g2"><div class="card"><h3>Latest quarter (${esc(sh.cols[sh.cols.length-1])})</h3><div class="donut-wrap" id="ch-donut"></div></div>
  <div class="card"><h3>Trend by quarter</h3><div id="ch-sh"></div></div></div></section>`;
}

function secAnnual() {
  const ars = (CO.developments.annual_reports || []).slice(0, 4);
  return `<section class="blk" id="s-annual"><div class="blk-h"><div><div class="kicker">Time-saver</div><h2>Annual report deep scan</h2><div class="sub">Reads the full audited annual report and pulls out what an investor must not miss, with page numbers</div></div></div>
  <div class="card">
    <div class="ar-list">${ars.map(a => `<button class="ar-btn" onclick='scanUrl(${JSON.stringify(a.url)}, ${JSON.stringify(a.title)})'><svg><use href="#i-file"/></svg>Scan ${esc(a.title)}</button>`).join('') || '<span class="pill">No annual report links found — upload the PDF below</span>'}</div>
    <label class="drop" id="drop"><input type="file" accept="application/pdf" id="arFile" hidden>
      <b>Drop an annual report PDF here</b> or click to browse<br><span style="font-size:12.5px">Use this if the exchange blocks the automatic download. Large reports (300+ pages) take about a minute.</span></label>
    <div id="scanOut" style="margin-top:16px"></div>
  </div></section>`;
}

/* ---------- charts ---------- */
function drawCharts() {
  const T = CO.trends;
  if (CO.scorecard.length) { AD.ring($('ring'), CO.overall, 'overall / 10'); AD.radar($('radar'), CO.scorecard); }
  AD.combo($('ch-rev'), {labels: T.labels, bars: [{name: 'Revenue', data: T.sales, color: C.navy}, {name: 'EBITDA', data: T.op_profit, color: C.saffron}], lines: [{name: 'OPM %', data: T.opm, color: C.green}], unitR: '%'});
  AD.combo($('ch-cash'), {labels: T.labels, bars: [{name: 'Net profit', data: T.np, color: C.blue}, {name: 'CFO', data: T.cfo, color: C.gold}]});
  AD.combo($('ch-ret'), {labels: T.labels, lines: [{name: 'ROCE %', data: T.roce, color: C.saffron}, {name: 'ROE %', data: T.roe, color: C.navy}], unitR: '%'});
  AD.combo($('ch-lev'), {labels: T.labels, bars: [{name: 'Net worth', data: T.net_worth, color: C.teal}, {name: 'Borrowings', data: T.borrowings, color: C.red}]});
  const Q = CO.quarters;
  AD.combo($('ch-q'), {labels: Q.labels.map(l => l.replace(/(\w{3}) 20(\d\d)/, '$1 $2')), bars: [{name: 'Sales', data: Q.sales, color: C.navy}, {name: 'Net profit', data: Q.np, color: C.saffron}], lines: [{name: 'OPM %', data: Q.opm, color: C.green}], unitR: '%'});
  AD.combo($('ch-eps'), {labels: T.labels, bars: [{name: 'EPS (₹)', data: T.eps, color: C.plum}], lines: [{name: 'Payout %', data: T.payout, color: C.gold}], unitR: '%'});
  const sh = CO.shareholding;
  if (sh.cols && sh.cols.length) {
    const last = k => (sh[k] || [])[sh[k].length - 1];
    AD.donut($('ch-donut'), [{n: 'Promoters', v: last('promoters'), c: C.navy}, {n: 'FIIs', v: last('fii'), c: C.saffron}, {n: 'DIIs', v: last('dii'), c: C.teal}, {n: 'Government', v: last('govt'), c: C.plum}, {n: 'Public', v: last('public'), c: C.grey}]);
    AD.combo($('ch-sh'), {labels: sh.cols.map(l => l.replace(/(\w{3}) 20(\d\d)/, '$1 $2')), lines: [{name: 'Promoters', data: sh.promoters, color: C.navy}, {name: 'FIIs', data: sh.fii, color: C.saffron}, {name: 'DIIs', data: sh.dii, color: C.teal}, {name: 'Public', data: sh.public, color: C.grey}], unitR: '%'});
  }
  document.querySelectorAll('#finTabs button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#finTabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.tabpane').forEach(p => p.classList.toggle('hidden', p.dataset.p !== b.dataset.t));
  });
  const drop = $('drop'), fi = $('arFile');
  fi.onchange = () => fi.files[0] && scanFile(fi.files[0]);
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) scanFile(f); });
}

/* ---------- peers ---------- */
async function loadPeers(peerUrl) {
  const box = $('peerBox'), ps = CO.peer_stats;
  const peers = CO.peers || [];
  const target = peerUrl || (ps.default_peer && ps.default_peer.url);
  const table = peerTable();
  if (!target) { box.innerHTML = `<div class="card"><h3>Pick a company to compare with</h3>${pickerHtml()}</div><div class="card" style="margin-top:18px">${table || '<div class="empty">Peer list unavailable from the data source. Use the picker above to compare with any company.</div>'}</div>`; bindPicker(); return; }
  box.innerHTML = `<div class="card"><div style="display:flex;align-items:center;gap:12px"><span class="spin"></span> Building head-to-head comparison…</div></div><div class="card" style="margin-top:18px">${table}</div>`;
  try {
    const cmp = await AD.getJSON('/api/compare?a=' + encodeURIComponent(CO.url) + '&b=' + encodeURIComponent(target));
    const opts = peers.filter(p => !p.url.includes('/' + CO.symbol + '/')).map(p => `<option value="${esc(p.url)}" ${p.url === target ? 'selected' : ''} style="color:#000">${esc(p.name)}</option>`).join('');
    const unitFmt = (v, u) => u === 'cr' ? cr(v) : fmt(v, u);
    box.innerHTML = `
    <div class="vs">
      <div class="side-a"><div class="sc">${esc(cmp.a.symbol)} · ${esc(cmp.a.year)} · score ${cmp.a.overall ?? '—'}/10</div><h3>${esc(cmp.a.name)}</h3><div class="wins">${cmp.wins.a} <span style="font-size:14px">metrics won</span></div></div>
      <div class="mid">vs</div>
      <div class="side-b"><div class="sc">${esc(cmp.b.symbol)} · ${esc(cmp.b.year)} · score ${cmp.b.overall ?? '—'}/10</div><h3>${esc(cmp.b.name)}</h3><div class="wins">${cmp.wins.b} <span style="font-size:14px">metrics won</span></div>
        <select class="no-print" onchange="loadPeers(this.value)">${opts}</select></div>
    </div>
    <div class="grid g2">
      <div class="card"><h3>Operating & financial metrics (latest audited year)</h3>
        <table class="fin cmp"><thead><tr><th>Metric</th><th>${esc(cmp.a.symbol)}</th><th>${esc(cmp.b.symbol)}</th></tr></thead><tbody>
        ${cmp.rows.map(r => `<tr><td class="lbl">${esc(r.label)}</td><td class="${r.winner==='a'?'win':''}">${unitFmt(r.a, r.unit)}</td><td class="${r.winner==='b'?'win':''}">${unitFmt(r.b, r.unit)}</td></tr>`).join('')}
        </tbody></table></div>
      <div>
        <div class="card"><h3>Valuation</h3><table class="fin cmp"><thead><tr><th>Metric</th><th>${esc(cmp.a.symbol)}</th><th>${esc(cmp.b.symbol)}</th></tr></thead><tbody>
          ${cmp.valuation.map(r => `<tr><td class="lbl">${esc(r.label)}</td><td class="${r.winner==='a'?'win':''}">${unitFmt(r.a, r.unit)}</td><td class="${r.winner==='b'?'win':''}">${unitFmt(r.b, r.unit)}</td></tr>`).join('')}</tbody></table></div>
        <div class="card" style="margin-top:18px"><h3>Revenue & PAT over the audited window</h3><div id="ch-cmp"></div><div class="unit">Years: ${esc(cmp.chart.labels_a.join(', '))} vs ${esc(cmp.chart.labels_b.join(', '))}</div></div>
        <div class="card" style="margin-top:18px"><h3>Scorecard overlay</h3><div id="ch-cmp-radar" style="display:flex;justify-content:center"></div>
          <div class="legend" style="justify-content:center"><span class="lg"><i class="sq" style="background:${C.navy}"></i>${esc(cmp.a.symbol)}</span><span class="lg"><i class="sq" style="background:${C.saffron}"></i>${esc(cmp.b.symbol)}</span></div></div>
      </div>
    </div>
    <div class="card no-print" style="margin-top:18px;display:flex;align-items:center;gap:16px;flex-wrap:wrap"><b style="font-family:var(--serif)">Compare with any other company</b>${pickerHtml()}</div>
    <div class="card" style="margin-top:18px">${table}</div>`;
    bindPicker();
    AD.combo($('ch-cmp'), {labels: cmp.chart.labels_a, bars: [{name: cmp.a.symbol + ' revenue', data: cmp.chart.sales_a, color: C.navy}, {name: cmp.b.symbol + ' revenue', data: cmp.chart.sales_b, color: C.saffron},
      {name: cmp.a.symbol + ' PAT', data: cmp.chart.np_a, color: '#6F87B8'}, {name: cmp.b.symbol + ' PAT', data: cmp.chart.np_b, color: C.saffron2 || '#F3B263'}]});
    if (cmp.a.scorecard.length && cmp.b.scorecard.length)
      AD.radar($('ch-cmp-radar'), cmp.a.scorecard, {series: [{data: cmp.a.scorecard.map(x => x.score), color: C.navy}, {data: cmp.b.scorecard.map(x => x.score), color: C.saffron}]});
  } catch (e) {
    box.innerHTML = `<div class="note err">Head-to-head failed: ${esc(AD.friendlyError(e.message))} <button class="btn" onclick="loadPeers('${esc(target)}')">Retry</button></div><div class="card">${table}</div>`;
  }
}
function pickerHtml() { return `<div class="pick" style="flex:1"><input id="pickIn" placeholder="Type a company, e.g. UltraTech, Shree Cement…" autocomplete="off"><svg class="si"><use href="#i-search"/></svg><div class="ac" id="pickAc"></div></div>`; }
function bindPicker() { const i = $('pickIn'); if (i) AD.autocomplete(i, $('pickAc'), it => loadPeers(it.url)); }
function peerTable() {
  const peers = CO.peers || [], ps = CO.peer_stats;
  if (!peers.length) return '';
  const cols = [['cmp', 'CMP ₹', v => inr(v, 1)], ['pe', 'P/E', v => fmt(v, 'x')], ['mcap', 'Mcap ₹ Cr', v => inr(v, 0)], ['div_yield', 'Div yld', v => fmt(v, '%')],
    ['np_qtr', 'NP qtr ₹ Cr', v => inr(v, 0)], ['qtr_profit_var', 'Qtr PAT var', v => fmt(v, '%')], ['sales_qtr', 'Sales qtr ₹ Cr', v => inr(v, 0)], ['qtr_sales_var', 'Qtr sales var', v => fmt(v, '%')], ['roce', 'ROCE', v => fmt(v, '%')]]
    .filter(c => peers.some(p => isNum(p[c[0]])));
  return `<h3>Peer universe <span class="pill" style="margin-left:auto">${peers.length} companies · rank by Mcap: ${ps.mcap_rank || '—'}</span></h3>
  <div style="overflow:auto"><table class="fin"><thead><tr><th>Company</th>${cols.map(c => `<th>${c[1]}</th>`).join('')}</tr></thead><tbody>
  ${peers.map(p => `<tr class="${p.url.includes('/' + CO.symbol + '/') ? 'me' : ''}"><td class="lbl"><a href="#" onclick='openCo({name:${JSON.stringify(p.name)},symbol:${JSON.stringify(p.url.split("/")[2] || p.name)},url:${JSON.stringify(p.url)}});return false'>${esc(p.name)}</a></td>${cols.map(c => `<td>${isNum(p[c[0]]) ? c[2](p[c[0]]) : '—'}</td>`).join('')}</tr>`).join('')}
  <tr class="med"><td>Peer median (ex-company)</td>${cols.map(c => `<td>${c[0]==='pe' ? fmt(ps.median_pe,'x') : c[0]==='roce' ? fmt(ps.median_roce,'%') : c[0]==='div_yield' ? fmt(ps.median_div_yield,'%') : c[0]==='qtr_sales_var' ? fmt(ps.median_qtr_sales_var,'%') : ''}</td>`).join('')}</tr>
  </tbody></table></div>`;
}

/* ---------- developments & news ---------- */
let NEWS = null, devFilter = 'All';
async function loadNews() {
  try {
    NEWS = await AD.getJSON('/api/news?name=' + encodeURIComponent(CO.name) + '&industry=' + encodeURIComponent(CO.playbook.search || (CO.sector_path.slice(-1)[0] || '') + ' industry India'));
    if (NEWS.moneycontrol) { const a = document.getElementById('lnk-Moneycontrol'); if (a) a.href = NEWS.moneycontrol; }
  } catch (e) { NEWS = {company: [], industry: [], industry_counts: {}, industry_pulse: 50, error: e.message}; }
  renderDevs(NEWS); renderIndustry(NEWS);
}
function renderDevs(news) {
  const D = CO.developments, cats = Object.entries(D.counts).sort((a, b) => b[1] - a[1]);
  const items = D.items.filter(i => devFilter === 'All' || i.cat === devFilter);
  const newsHtml = news === null ? '<div class="sk"></div><div class="sk" style="width:80%"></div><div class="sk"></div>' :
    (news.company.length ? `<ul class="news">${news.company.map(n => `<li><span class="sent ${n.sentiment}">${n.sentiment}</span><div><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a><div class="src">${esc(n.source)} · ${esc(n.date)}</div></div></li>`).join('')}</ul>` : `<div class="empty">No recent news found${news.error ? ' (' + esc(news.error) + ')' : ''}</div>`);
  $('devBox').innerHTML = `<div class="grid g2">
    <div class="card"><h3>Exchange disclosures <span class="pill" style="margin-left:auto">${D.items.length} recent</span></h3>
      <div class="filters">${[['All', D.items.length], ...cats].map(([c, n]) => `<button class="fchip ${devFilter === c ? 'on' : ''}" onclick="devFilter='${esc(c)}';renderDevs(NEWS)">${esc(c)}<b>${n}</b></button>`).join('')}</div>
      <div class="timeline">${items.map(i => `<div class="tl" style="--c:${AD.DEV_COLORS[i.color] || '#999'}"><span class="cat">${esc(i.cat)}</span> <span class="dt">${esc(i.date)}</span><a class="ttl" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a><div class="det">${esc(i.detail)}</div></div>`).join('') || '<div class="empty">No disclosures in this category</div>'}</div></div>
    <div>
      <div class="card"><h3>News on developments & the stock</h3>${newsHtml}</div>
      ${D.concalls.length ? `<div class="card" style="margin-top:18px"><h3>Earnings calls & presentations</h3><div class="linklist">${D.concalls.map(c => c.links.map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(c.date)} — ${esc(l.type)}<span>open ↗</span></a>`).join('')).join('')}</div></div>` : ''}
      ${D.credit_ratings.length ? `<div class="card" style="margin-top:18px"><h3>Credit ratings</h3><div class="linklist">${D.credit_ratings.map(c => `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}<span>↗</span></a>`).join('')}</div></div>` : ''}
    </div></div>`;
}
function renderIndustry(news) {
  const P = CO.playbook, ps = CO.peer_stats, s = CO.snapshot;
  const pulse = news ? `<div id="gauge"></div><div class="counts"><span style="color:var(--green)"><b>${news.industry_counts.Tailwind || 0}</b> tailwinds</span><span style="color:var(--red)"><b>${news.industry_counts.Headwind || 0}</b> headwinds</span><span style="color:var(--muted)"><b>${news.industry_counts.Neutral || 0}</b> neutral</span></div>` : '<div class="sk" style="height:110px"></div>';
  const head = news === null ? '<div class="sk"></div><div class="sk"></div><div class="sk" style="width:60%"></div>' :
    (news.industry.length ? `<ul class="news">${news.industry.map(n => `<li><span class="sent ${n.sentiment}">${n.sentiment}</span><div><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a><div class="src">${esc(n.source)} · ${esc(n.date)}</div></div></li>`).join('')}</ul>` : '<div class="empty">No industry headlines available</div>');
  const rel = (a, b, u) => isNum(a) && isNum(b) ? `<span class="chg ${a > b ? 'good' : 'bad'}">${a > b ? 'above' : 'below'} median</span>` : '';
  $('indBox').innerHTML = `
  <div class="grid g4" style="margin-bottom:18px">
    <div class="kpi"><div class="l">Peer-set median P/E</div><div class="v">${fmt(ps.median_pe, 'x')}</div><div class="s">Company: ${fmt(s.pe, 'x')}</div></div>
    <div class="kpi"><div class="l">Peer-set median ROCE</div><div class="v">${fmt(ps.median_roce, '%')}</div><div class="s">Company: ${fmt(s.roce, '%')} ${rel(s.roce, ps.median_roce)}</div></div>
    <div class="kpi"><div class="l">Median qtr sales growth</div><div class="v">${fmt(ps.median_qtr_sales_var, '%')}</div><div class="s">Latest quarter, peer set</div></div>
    <div class="kpi"><div class="l">Size rank in peer set</div><div class="v">#${ps.mcap_rank || '—'} <span style="font-size:13px;color:var(--muted)">of ${ps.count}</span></div><div class="s">By market capitalisation</div></div>
  </div>
  <div class="grid g3">
    <div class="card"><h3>Industry pulse (live headlines)</h3>${pulse}<div class="score-note">0 = all headwinds · 100 = all tailwinds</div></div>
    <div class="card"><h3>Structural tailwinds</h3><ul class="tw up">${P.tailwinds.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
    <div class="card"><h3>Structural headwinds</h3><ul class="tw dn">${P.headwinds.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
  </div>
  <div class="grid g3" style="margin-top:18px">
    <div class="card"><h3>Key demand & cost drivers</h3><ul class="tw kp">${P.drivers.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
    <div class="card"><h3>Industry KPIs to track</h3><ul class="tw kp">${P.kpis.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
    <div class="card"><h3>CA lens — audit areas to check</h3><ul class="tw au">${P.audit.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
  </div>
  <div class="card" style="margin-top:18px"><h3>What's happening in the industry <span class="pill" style="margin-left:auto">Google News · auto-tagged</span></h3>${head}</div>`;
  if (news) AD.gauge($('gauge'), news.industry_pulse, 'industry pulse');
}

/* ---------- annual report scan ---------- */
function scanWaiting(label) { $('scanOut').innerHTML = `<div class="note" style="display:flex;gap:12px;align-items:center"><span class="spin"></span><span>Reading <b>${esc(label)}</b>: extracting text, then mining KAMs, capex, contingent liabilities, RPTs and outlook. Large reports take 30–90 seconds…</span></div>`; }
async function scanUrl(url, label) {
  scanWaiting(label);
  try { renderScan(await AD.getJSON('/api/scan?pdf=' + encodeURIComponent(url))); }
  catch (e) { $('scanOut').innerHTML = `<div class="note err">Automatic download failed (${esc(e.message)}). The exchange may block scripted downloads: <a href="${esc(url)}" target="_blank" rel="noopener">open the PDF ↗</a>, save it, then drop it into the box above.</div>`; }
}
async function scanFile(f) {
  scanWaiting(f.name);
  try { renderScan(await AD.getJSON('/api/scan-upload?name=' + encodeURIComponent(f.name), {method: 'POST', body: f, headers: {'Content-Type': 'application/pdf'}})); }
  catch (e) { $('scanOut').innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
}
function hlText(t, hits) { let s = esc(t); (hits || []).sort((a, b) => b.length - a.length).forEach(h => { s = s.replace(new RegExp('(' + h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>'); }); return s; }
const SCAN_IC = {shield: '🛡', factory: '🏭', compass: '🧭', alert: '⚠', scale: '⚖', link: '🔗', coins: '💰', merge: '🔀', leaf: '🌿'};
function renderScan(r) {
  $('scanOut').innerHTML = `<div class="note" style="background:#EAF5EF;border-color:#CFE7DA;color:var(--green)">✓ Scanned <b>${r.pages}</b> pages of ${esc(r.label)} in ${r.seconds}s. Showing the highest-signal passages per theme.</div>
  ${r.capacity_mentions && r.capacity_mentions.length ? `<details class="acc" open><summary>📐 Capacity figures spotted <span class="pill cnt">${r.capacity_mentions.length}</span></summary><div class="body">${r.capacity_mentions.map(c => `<div class="quote">${esc(c)}</div>`).join('')}</div></details>` : ''}
  ${r.categories.map((c, i) => `<details class="acc" ${i < 2 ? 'open' : ''}><summary>${SCAN_IC[c.icon] || '•'} ${esc(c.category)} <span class="pill cnt">${c.items.length} of ${c.total_hits} matches</span></summary><div class="body">
    ${c.items.map(it => `<div class="quote">${hlText(it.text, it.hits)}<div class="pg">Page ${it.page}</div></div>`).join('') || '<div class="empty">Nothing significant found for this theme</div>'}</div></details>`).join('')}`;
}

/* ---------- scrollspy ---------- */
function initSpy() {
  const links = [...document.querySelectorAll('#nav a')];
  const obs = new IntersectionObserver(es => { es.forEach(e => { if (e.isIntersecting) links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + e.target.id)); }); }, {rootMargin: '-30% 0px -65% 0px'});
  document.querySelectorAll('section.blk').forEach(s => obs.observe(s));
  links.forEach(a => a.onclick = e => { e.preventDefault(); document.querySelector(a.getAttribute('href')).scrollIntoView({behavior: 'smooth'}); });
}

/* deep link: /#AMBUJACEM */
if (location.hash.length > 1) { const s = decodeURIComponent(location.hash.slice(1)); openCo({name: s, symbol: s, url: '/company/' + s + '/consolidated/'}); }
</script>
</body>
</html>
"""

# =====================================================================
#  ArthaDrishti — WEB edition launcher
#  Double-click this file. It starts a private local server and opens
#  the dashboard in your default browser. Close the small window to quit.
# =====================================================================

def main():
    if ensure_dependencies():
        still = _missing(REQUIRED)
        if still:
            return fatal("Could not install required packages: " + ", ".join(still) +
                         "\n\nOpen a command prompt and run:\n  pip install requests beautifulsoup4 pypdf")
    PAGES["/"] = ("text/html; charset=utf-8", WEB_HTML.encode("utf-8"))
    PAGES["/icon.svg"] = ("image/svg+xml", ICON_SVG.encode("utf-8"))
    srv, port = start_server("127.0.0.1", range(8765, 8790))
    url = f"http://127.0.0.1:{port}/"
    log.info("Web edition on %s", url)
    if "--headless" in sys.argv:
        print(url, flush=True)
        while True: time.sleep(3600)
    webbrowser.open(url)
    root, mk, stop = control_window("Web edition", url, srv)
    mk("Open dashboard", lambda: webbrowser.open(url), primary=True)
    mk("Stop & exit", stop)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        fatal("ArthaDrishti failed to start:\n\n" + traceback.format_exc()[-1500:])
