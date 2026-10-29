"""Prova dell'intero script senza rete: sostituisce le chiamate a FRED, Yahoo, multpl e yfinance con dati simulati.
Controlla che dati.json esca completo e coerente; NON prova i server reali."""
import datetime as dt, json, math, os, random, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pandas as pd
import aggiorna_dati as A
import yfinance as yf

random.seed(7)
OGGI = dt.date.today()
def mesi(da, a):
    y, m = da
    while (y, m) <= (a.year, a.month):
        yield dt.date(y, m, 1)
        m += 1
        if m == 13: y, m = y + 1, 1

def passeggiata(n, start, vol, drift=0.0):
    x, out = start, []
    for _ in range(n):
        x *= math.exp(random.gauss(drift, vol)); out.append(x)
    return out

def fake_fred(sid):
    base = {"CFNAIMA3": (0, .25), "SAHMREALTIME": (.3, .15), "IC4WSA": (300000, 15000), "USALOLITOAASTSAM": (100, .5),
            "DEULOLITOAASTSAM": (100, .5), "JPNLOLITOAASTSAM": (100, .5), "CHNLOLITOAASTSAM": (100, .5),
            "DRTSCILM": (5, 15), "DRTSCLCC": (5, 12), "BAA10Y": (2.5, .3), "AAA10Y": (1.5, .2), "NFCI": (-0.3, .2),
            "BUSLOANS": (1000, 30), "T10Y2Y": (.8, .3), "DGS10": (4, .2), "CPIAUCSL": (100, .3), "DAAA": (5.4, .1)}
    if sid not in base: raise RuntimeError("serie sconosciuta " + sid)
    centro, sd = base[sid]
    ds = list(mesi((1965, 1), OGGI))
    if sid == "BUSLOANS": vals = [centro * (1 + .004) ** i + random.gauss(0, sd) for i in range(len(ds))]
    elif sid == "CPIAUCSL": vals = [centro * (1 + .003) ** i for i in range(len(ds))]
    elif sid == "IC4WSA": vals = [max(150000, centro + random.gauss(0, sd) * 3) for _ in ds]
    else: vals = [centro + random.gauss(0, sd) for _ in ds]
    if sid == "DAAA": ds = [OGGI - dt.timedelta(days=k) for k in range(2000, 0, -1)]; vals = [5.4 + random.gauss(0, .05) for _ in ds]
    return list(zip(ds, vals))
A.fred = fake_fred
A.yahoo_mensile = lambda sym, dal=1990: list(zip(list(mesi((max(dal, 1990), 1), OGGI)),
                                             passeggiata(len(list(mesi((max(dal, 1990), 1), OGGI))), 100, .04, .006)))
A.cape_storia = lambda: [(d, 10 + (i % 300) * .1 + (30 if d.year > 2015 else 0)) for i, d in enumerate(mesi((1871, 1), OGGI))]

def giorni(anni):
    d, out = dt.date(OGGI.year - anni, 1, 2), []
    while d <= OGGI:
        if d.weekday() < 5: out.append(d)
        d += dt.timedelta(days=1)
    return out
PX = {}
_MEMO = {}
import zlib
def fake_storico(sym, anni=22, intervallo="1d"):
    if sym.startswith("BAD"): raise RuntimeError("sconosciuto")
    if sym in _MEMO and anni == 22: return _MEMO[sym]
    random.seed(zlib.crc32(sym.encode()))
    ds = giorni(anni)
    if sym.endswith("=X"): vals = [1.1 + .02 * math.sin(i / 200) for i in range(len(ds))]
    else:
        n = len(ds); vals = passeggiata(n, 50 + zlib.crc32(sym.encode()) % 50, .01, .0003)
        if sym == "SXR1.DE": vals = vals[:200] + [v * 1.0 for v in vals[200:]]
        if sym == "VNRA.DE": ds, vals = ds[-1800:], vals[-1800:]
    PX[sym] = vals[-1]
    righe = [(d, v, v * .98, 1000.0) for d, v in zip(ds, vals)]
    _MEMO[sym] = ({"currency": "EUR", "gmtoffset": 3600}, righe) if anni == 22 else None
    return {"currency": "EUR", "gmtoffset": 3600}, righe
A.yahoo_storico = fake_storico
def fake_chart(sym):
    if sym.endswith("=X"): return 1.1, "EUR", OGGI
    if sym not in PX: fake_storico(sym, 22)
    return PX[sym], "EUR", OGGI
A.yahoo_chart = fake_chart
A.yahoo_search = lambda isin: ["XYZ" + isin[:4] + ".DE"]
orig_chart = A.yahoo_chart
# l'ultimo prezzo dello storico e il prezzo di oggi devono combaciare: li facciamo derivare dalla stessa tabella
def fake_price_for(isin, override, cache):
    sym = override or cache.get(isin) or "T" + isin[2:6] + ".DE"
    p = fake_chart(sym)[0]
    cache[isin] = sym
    return p, sym, "EUR", OGGI
A.price_for = fake_price_for

# ---- yfinance simulato
class FakeTicker:
    def __init__(self, tk): self.tk = tk
    @property
    def info(self):
        return {"shortName": "Soc " + self.tk, "sector": "Industrials", "currency": "EUR", "financialCurrency": "EUR",
                "currentPrice": 50.0, "marketCap": 5e9, "trailingEps": 5.0, "trailingPE": 10.0, "bookValue": 40.0, "priceToBook": 1.25,
                "totalRevenue": 4e9, "fiftyTwoWeekHigh": 60.0, "twoHundredDayAverage": 52.0, "forwardPE": 9.0, "totalDebt": 1e9,
                "totalCash": 4e8, "ebitda": 8e8, "currentRatio": 1.8, "debtToEquity": 55.0, "freeCashflow": 3e8, "returnOnEquity": .12,
                "payoutRatio": .4}
    @property
    def financials(self):
        cols = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"])
        return pd.DataFrame({cols[i]: {"Net Income": 3e8 + i * 3e7, "Diluted EPS": 3.5 + i * .4, "EBIT": 5e8, "Interest Expense": 4e7}
                             for i in range(4)})
    @property
    def dividends(self):
        idx = pd.to_datetime([f"{y}-06-15" for y in range(2012, OGGI.year + 1)])
        return pd.Series(1.0, index=idx)
    def history(self, period="5d"): return pd.DataFrame({"Close": [1.1, 1.1]})
yf.Ticker = FakeTicker
class FakeSearch:
    def __init__(self, q, max_results=8): self.quotes = [{"symbol": "S" + q[2:6], "quoteType": "EQUITY", "exchange": "GER"}]
yf.Search = FakeSearch
A.time.sleep = lambda s: None

tmp = tempfile.mkdtemp()
out = os.path.join(tmp, "dati", "dati.json")
rc = A.main(["--config", os.path.join(HERE, "..", "config.json"), "--out", out])
d = json.load(open(out, encoding="utf-8"))
errori = []
def chk(c, m):
    if not c: errori.append(m)
chk(rc == 0, "codice di uscita")
for sez in ("pendolo", "mercato", "prezzi", "etf", "graham"):
    chk(d["fonti"].get(sez, {}).get("ok"), f"sezione {sez} non riuscita: {d['fonti'].get(sez)}")
p = d["pendolo"]
chk(0 <= p["punteggio"] <= 100 and 0 <= p["riferimento"] <= 100, "punteggio fuori scala")
chk(len(p["storia"]) == 24, "storia pendolo")
chk("ottimismo" in p, "ottimismo mancante")
m = d["mercato"]; chk(m["mediaMobileMesi"] == 10 and isinstance(m["sottoMedia"], bool), "mercato")
cfg = json.load(open(os.path.join(HERE, "..", "config.json"), encoding="utf-8"))
for s in cfg["strumenti"]: chk(s["isin"] in d["prezzi"], "prezzo mancante " + s["isin"])
for e in cfg["bilanciamento"]["etf"] + cfg["bilanciamento"]["speculativi"]:
    x = d["etf"].get(e["isin"]); chk(x is not None, "storico mancante " + e["isin"])
    if x:
        print(f"  {e['nome'][:34]:<34} {x['stato']:<14} anni {x['anni']:>5} ribasso {x.get('ribasso', 0):+.3f} pct {x.get('percentile', 0):.2f} soglie {x.get('soglieRibasso')}")
        if x["stato"] == "OK": chk(len(x["soglieRibasso"]) == 3 and x["soglieRibasso"][0] >= x["soglieRibasso"][1] >= x["soglieRibasso"][2], "soglie non ordinate")
for a in cfg["bilanciamento"]["azioni"]:
    g = d["graham"].get(a["isin"]); chk(g and g["punteggio"] is not None, "graham mancante " + a["isin"])
chk(d["aaa"]["rendimento"] > 0, "AAA")
# seconda esecuzione: solo prezzi, il resto deve restare identico
d1 = json.dumps({k: d[k] for k in ("pendolo", "etf", "graham")}, sort_keys=True)
A.AVVISI.clear()
rc = A.main(["--config", os.path.join(HERE, "..", "config.json"), "--out", out, "--sezioni", "prezzi"])
d2 = json.load(open(out, encoding="utf-8"))
chk(d1 == json.dumps({k: d2[k] for k in ("pendolo", "etf", "graham")}, sort_keys=True), "le altre sezioni sono cambiate")
chk(d2["fonti"]["pendolo"]["ok"], "stato pendolo perso")
# sezione che fallisce: tengo i dati vecchi e segnalo
A.fred = lambda sid: (_ for _ in ()).throw(RuntimeError("manutenzione"))
A.AVVISI.clear()
rc = A.main(["--config", os.path.join(HERE, "..", "config.json"), "--out", out, "--sezioni", "pendolo"])
d3 = json.load(open(out, encoding="utf-8")) if rc == 0 else d2
chk(rc == 1, "con FRED giu' e una sola sezione deve uscire con 1 e non scrivere")
chk(json.load(open(out, encoding="utf-8"))["pendolo"] == d2["pendolo"], "pendolo vecchio non conservato")
print("\nERRORI:", errori if errori else "nessuno")
sys.exit(1 if errori else 0)
