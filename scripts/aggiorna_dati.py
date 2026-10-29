#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggiorna_dati.py - scarica i dati di mercato e scrive dati/dati.json per l'app Pendolo

Fa, senza Excel, quello che oggi fanno 05_pendolo.py, 02_mercato.py, aggiorna_cruscotto.py,
B2_prezzi_etf.py e B3_graham_azioni.py. Le regole sono le stesse: le funzioni del modello
(punteggio, percentili, pulizia dei prezzi, dati Graham) sono copiate da quegli script; il
punteggio Graham ricalcola le formule del foglio Graham di Bilanciamento.xlsx con i parametri
di config.json.

Cosa legge:  config.json (parametri, paniere ETF, elenco delle azioni e degli strumenti)
Cosa scrive: dati/dati.json (dati di mercato) e dati/cache_ticker.json (ticker trovati dagli ISIN)

Sezioni (--sezioni, separate da virgola; default: tutte):
  pendolo   punteggio 0-100, ottimismo nei prezzi, punteggio di riferimento (FRED, Yahoo, multpl)
  mercato   indice MSCI World e freno: prezzo contro la media mobile (Yahoo)
  prezzi    ultimo prezzo in euro di ETF, azioni e oro (Yahoo)
  etf       storico degli ETF: massimo a 12 mesi, ribasso, soglie delle fasce (Yahoo)
  graham    bilanci e punteggio Graham delle azioni (yfinance, FRED)

Se una fonte non risponde, la sezione resta quella dell'ultima volta (con la sua data) e il motivo
finisce in "avvisi": l'app mostra quanto sono vecchi i dati.

Uso:
  python scripts/aggiorna_dati.py                     tutto
  python scripts/aggiorna_dati.py --sezioni prezzi    solo i prezzi
  python scripts/aggiorna_dati.py --solo-test         scarica e stampa, ma non scrive
  python scripts/aggiorna_dati.py --graham-ogni 6     Graham solo se piu' vecchio di 6 giorni
"""
import argparse
import bisect
import collections
import csv
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
AVVISI = []


def avviso(testo):
    AVVISI.append(testo)
    print("  ! " + testo)


# ================================================================ rete
def fetch_text(url, tries=3, pause=1.5, headers=UA_BROWSER, timeout=40):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(pause * (k + 1))
    raise RuntimeError(str(last))


# ================================================================ 1. PENDOLO  (da 05_pendolo.py, versione 18.1)
# (nome, id FRED, direzione, ritardo di pubblicazione in mesi, peso, area)
CRESCITA = [
    ("CFNAI 3 mesi",        "CFNAIMA3",         +1, 1, 0.35, "USA"),
    ("Regola di Sahm",      "SAHMREALTIME",     -1, 1, 0.30, "USA"),
    ("Sussidi 4 settimane", "IC4WSA",           -1, 0, 0.20, "USA"),
    ("CLI Stati Uniti",     "USALOLITOAASTSAM", +1, 2, 0.15, "USA"),
    ("CLI Germania",        "DEULOLITOAASTSAM", +1, 2, 1.00, "Eurozona"),
    ("CLI Giappone",        "JPNLOLITOAASTSAM", +1, 2, 1.00, "Giappone"),
    ("CLI Cina",            "CHNLOLITOAASTSAM", +1, 2, 1.00, "Cina/EM"),
]
CREDITO = [
    ("SLOOS prestiti imprese", "DRTSCILM", -1, 1, 3.0, False),
    ("SLOOS carte di credito", "DRTSCLCC", -1, 1, 1.0, False),
    ("Spread Moody's Baa",     "BAA10Y",   -1, 0, 3.0, False),
    ("Spread Moody's Aaa",     "AAA10Y",   -1, 0, 2.0, False),
    ("Chicago Fed NFCI",       "NFCI",     -1, 0, 2.0, False),
    ("Prestiti imprese 12m",   "BUSLOANS", +1, 1, 1.5, True),
    ("Curva 10 anni - 2 anni", "T10Y2Y",   +1, 0, 1.5, False),
]
AREA_W = {"USA": 0.45, "Eurozona": 0.25, "Giappone": 0.10, "Cina/EM": 0.20}
PESO_CRESCITA, PESO_CREDITO = 0.5, 0.5
PESO_CRED_TOT = sum(x[4] for x in CREDITO)
MIN_ANNI_STORIA = 10
MIN_OSSERVAZIONI = 20
MAX_RITARDO_DATO = 3
MESI_EN = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_cache = {}


def fred(sid):
    """Serie FRED. NIENTE User-Agent finto: con quello FRED chiude la connessione."""
    if sid in _cache:
        return _cache[sid]
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1960-01-01"
    ultimo = None
    for k in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                testo = r.read().decode("utf-8", errors="replace")
            break
        except Exception as e:  # noqa
            ultimo = e
            time.sleep(2 * (k + 1))
    else:
        raise RuntimeError(f"{sid}: {ultimo}")
    out = []
    for rec in csv.reader(io.StringIO(testo)):
        if len(rec) < 2 or not re.match(r"^\d{4}-\d{2}-\d{2}$", rec[0]):
            continue
        try:
            out.append((dt.date.fromisoformat(rec[0]), float(rec[1])))
        except ValueError:
            continue
    if not out:
        raise RuntimeError(f"{sid}: nessun dato")
    out.sort()
    _cache[sid] = out
    print(f"   {sid:<22} {len(out):>6} osservazioni  dal {out[0][0]:%m/%Y} al {out[-1][0]:%m/%Y}")
    return out


def _yahoo_blocco_mensile(sym, da, a_):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
           + f"?period1={da}&period2={a_}&interval=1mo")
    js = json.loads(fetch_text(url, tries=3))
    res = js["chart"]["result"][0]
    out = []
    for ts, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0].get("close", [])):
        if c is not None:
            out.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc).date(), float(c)))
    return out


def yahoo_mensile(sym, dal_anno=1990):
    """Chiusure mensili da Yahoo, a blocchi di 8 anni."""
    if sym in _cache:
        return _cache[sym]
    visti, errori = {}, []
    anno, oggi = dal_anno, dt.date.today()
    while anno <= oggi.year:
        da = int(dt.datetime(anno, 1, 1).timestamp())
        a_ = int(dt.datetime(min(anno + 8, oggi.year + 1), 1, 1).timestamp())
        try:
            for d, v in _yahoo_blocco_mensile(sym, da, a_):
                visti[d] = v
        except Exception as e:  # noqa
            errori.append(f"{anno}: {e}")
        anno += 8
        time.sleep(0.4)
    out = sorted(visti.items())
    if not out:
        raise RuntimeError("nessun dato (" + "; ".join(errori[:3]) + ")")
    print(f"   {sym:<22} {len(out):>6} osservazioni  dal {out[0][0]:%m/%Y} al {out[-1][0]:%m/%Y}"
          + (f"   blocchi falliti: {len(errori)}" if errori else ""))
    _cache[sym] = out
    return out


def cape_storia():
    """Storia mensile del CAPE di Shiller da multpl.com (dal 1871)."""
    if "CAPE" in _cache:
        return _cache["CAPE"]
    html = fetch_text("https://www.multpl.com/shiller-pe/table/by-month", tries=3, timeout=60)
    testo = re.sub(r"<[^>]+>", " ", html)
    testo = re.sub(r"&#?[A-Za-z0-9]+;", " ", testo)
    visti = {}
    for mese, gg, aa, val in re.findall(
            r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s*(\d{4})\s+([0-9]{1,3}\.[0-9]{1,2})\b", testo):
        m3 = mese[:3]
        if m3 in MESI_EN:
            visti[(int(aa), MESI_EN[m3])] = float(val)
    out = [(dt.date(aa, mm, 1), v) for (aa, mm), v in visti.items() if 3 < v < 100]
    if len(out) < 600:
        raise RuntimeError(f"solo {len(out)} righe di CAPE trovate")
    out.sort()
    _cache["CAPE"] = out
    print(f"   {'CAPE Shiller':<22} {len(out):>6} osservazioni  dal {out[0][0]:%m/%Y} al {out[-1][0]:%m/%Y}")
    return out


def mensile(serie, ultimo_del_mese=True):
    out = {}
    for d, v in serie:
        k = (d.year, d.month)
        if ultimo_del_mese or k not in out:
            out[k] = v
    return out


def mese_meno(k, n):
    tot = k[0] * 12 + (k[1] - 1) - n
    return (tot // 12, tot % 12 + 1)


def mese_disponibile(serie_mensile, kv, max_ritardo=MAX_RITARDO_DATO):
    for n in range(max_ritardo + 1):
        kk = mese_meno(kv, n)
        if kk in serie_mensile:
            return kk
    return None


def percentile(valori, x):
    """Quota dei valori passati strettamente sotto x."""
    return None if not valori else sum(1 for v in valori if v < x) / len(valori)


def punteggio_da_perc(p, direzione):
    return 1 + 4 * (p if direzione > 0 else 1 - p)


def abbastanza_storia(serie_mensile, kv, storia):
    if len(storia) < MIN_OSSERVAZIONI:
        return False
    primo = min(serie_mensile)
    return (kv[0] - primo[0]) * 12 + (kv[1] - primo[1]) >= MIN_ANNI_STORIA * 12


def yoy(serie):
    d = dict(serie)
    out = []
    for data, v in serie:
        try:
            prec = d[dt.date(data.year - 1, data.month, data.day)]
        except KeyError:
            continue
        if prec:
            out.append((data, (v / prec - 1) * 100))
    return out


def calcola_punteggi(dati, azioni, da, fino_a=None):
    """Una riga per mese dal gennaio di `da`: punteggio, crescita, credito, copertura."""
    mesi = sorted(k for k in azioni if k[0] >= da and (fino_a is None or k <= fino_a))
    storie = {sid: sorted(s.items()) for sid, s in dati.items()}
    righe = []
    for k in mesi:
        dettaglio = {}
        per_area = {}
        for nome, sid, direzione, lag, peso, area in CRESCITA:
            s = dati.get(sid)
            if not s:
                continue
            kv = mese_disponibile(s, mese_meno(k, lag))
            if kv is None:
                continue
            storia = [v for kk, v in storie[sid] if kk <= kv]
            if not abbastanza_storia(s, kv, storia):
                continue
            p = percentile(storia[:-1], s[kv])
            sc = punteggio_da_perc(p, direzione)
            per_area.setdefault(area, []).append((peso, sc))
            dettaglio[sid] = (s[kv], kv, p, sc)
        g_num = g_den = 0.0
        for area, voci in per_area.items():
            pn = sum(p * v for p, v in voci)
            pd = sum(p for p, _ in voci)
            if pd:
                g_num += AREA_W[area] * (pn / pd)
                g_den += AREA_W[area]
        gscore = g_num / g_den if g_den else None
        c_num = c_den = 0.0
        for nome, sid, direzione, lag, peso, var in CREDITO:
            s = dati.get(sid)
            if not s:
                continue
            kv = mese_disponibile(s, mese_meno(k, lag))
            if kv is None:
                continue
            storia = [v for kk, v in storie[sid] if kk <= kv]
            if not abbastanza_storia(s, kv, storia):
                continue
            p = percentile(storia[:-1], s[kv])
            sc = punteggio_da_perc(p, direzione)
            c_num += peso * sc
            c_den += peso
            dettaglio[sid] = (s[kv], kv, p, sc)
        cscore = c_num / c_den if c_den else None
        if gscore is None or cscore is None:
            continue
        pos = 25 * (PESO_CRESCITA * gscore + PESO_CREDITO * cscore - 1)
        righe.append({"k": k, "pos": max(0.0, min(100.0, pos)),
                      "g": 25 * (gscore - 1), "c": 25 * (cscore - 1),
                      "prezzo": azioni[k], "cop_cred": c_den / PESO_CRED_TOT,
                      "dettaglio": dettaglio})
    for r in righe[:-1]:
        r.pop("dettaglio", None)
    return righe


def excess_cape_yield(cape, nom, cpi):
    out = {}
    for k in sorted(cape):
        k10 = mese_meno(k, 120)
        if k not in nom or k not in cpi or k10 not in cpi or cape[k] <= 0 or cpi[k10] <= 0:
            continue
        infl = ((cpi[k] / cpi[k10]) ** (1 / 10) - 1) * 100
        out[k] = 100.0 / cape[k] - (nom[k] - infl)
    return out


def calcola_ottimismo(cape, ecy, da):
    out = {}
    cape_ord = sorted(cape.items())
    ecy_ord = sorted(ecy.items())
    for k in sorted(set(cape) & set(ecy)):
        if k[0] < da:
            continue
        sc = [v for kk, v in cape_ord if kk <= k]
        se = [v for kk, v in ecy_ord if kk <= k]
        if not (abbastanza_storia(cape, k, sc) and abbastanza_storia(ecy, k, se)):
            continue
        p_cape = percentile(sc[:-1], cape[k])
        p_ecy_alto = 1 - percentile(se[:-1], ecy[k])
        out[k] = (100 * (p_cape + p_ecy_alto) / 2, cape[k], p_cape, ecy[k], p_ecy_alto)
    return out


def punteggi_riferimento(righe, zona):
    """Punteggio che decide l'allocazione, mese per mese: fuori dalla zona neutra e' il punteggio
    del mese; dentro, l'ultimo punteggio fuori dalla zona (se non ce n'e', quello del mese).
    Lavora sul punteggio a due decimali, lo stesso che finisce in dati.json."""
    lo, hi = zona
    out, ultimo_fuori = [], None
    for r in righe:
        p = round(r["pos"], 2)
        if p <= lo or p >= hi or lo >= hi:
            ultimo_fuori = p
        out.append(ultimo_fuori if ultimo_fuori is not None else p)
    return out


def sezione_pendolo(cfg, prec):
    print("\n== PENDOLO (FRED, Yahoo, multpl) ==")
    dati, mancanti = {}, []
    for nome, sid, *_ in CRESCITA:
        try:
            dati[sid] = mensile(fred(sid))
        except Exception as e:  # noqa
            mancanti.append(sid)
            print(f"   {sid:<22} NON RIUSCITO: {e}")
    for nome, sid, direzione, lag, peso, var in CREDITO:
        try:
            s = fred(sid)
            dati[sid] = mensile(yoy(s) if var else s)
        except Exception as e:  # noqa
            mancanti.append(sid)
            print(f"   {sid:<22} NON RIUSCITO: {e}")
    if mancanti:
        raise RuntimeError("mancano " + ", ".join(mancanti) + ": un punteggio senza questi indicatori "
                           "non e' quello verificato")
    azioni = mensile(yahoo_mensile("^GSPC", 1990))
    tassi = {}
    for sid in ("DGS10", "CPIAUCSL"):
        try:
            tassi[sid] = mensile(fred(sid))
        except Exception as e:  # noqa
            tassi[sid] = {}
            print(f"   {sid:<22} NON RIUSCITO: {e}")
    cape = {}
    try:
        cape = mensile(cape_storia())
    except Exception as e:  # noqa
        print(f"   CAPE NON RIUSCITO: {e}")
    righe = calcola_punteggi(dati, azioni, 1998)
    if len(righe) < 120:
        raise RuntimeError(f"solo {len(righe)} mesi con punteggio calcolabile: troppo pochi")
    ult = righe[-1]
    zona = cfg["strategia"]["zonaNeutra"]
    rif = punteggi_riferimento(righe, zona)
    k_rif = None
    for i in range(len(righe) - 1, -1, -1):
        p = round(righe[i]["pos"], 2)
        if p <= zona[0] or p >= zona[1] or zona[0] >= zona[1]:
            k_rif = righe[i]["k"]
            break
    out = {"punteggio": round(ult["pos"], 2), "mese": f"{ult['k'][0]}-{ult['k'][1]:02d}-01",
           "riferimento": rif[-1],
           "riferimentoMese": f"{k_rif[0]}-{k_rif[1]:02d}-01" if k_rif else None,
           "crescita": round(ult["g"], 2), "credito": round(ult["c"], 2),
           "coperturaCredito": round(ult["cop_cred"], 4), "aggiornato": dt.date.today().isoformat()}
    ecy = excess_cape_yield(cape, tassi["DGS10"], tassi["CPIAUCSL"]) if (cape and tassi["DGS10"] and tassi["CPIAUCSL"]) else {}
    ott = calcola_ottimismo(cape, ecy, 1998) if (cape and ecy) else {}
    if ott:
        k = max(ott)
        o, cp, p_cape, e, p_ecy = ott[k]
        out.update({"ottimismo": round(o, 2), "meseOttimismo": f"{k[0]}-{k[1]:02d}-01",
                    "cape": round(cp, 2), "ecy": round(e, 3)})
    else:
        avviso("ottimismo nei prezzi non aggiornato (CAPE o tassi non disponibili)")
        for k in ("ottimismo", "meseOttimismo", "cape", "ecy"):
            if prec.get(k) is not None:
                out[k] = prec[k]
    # ultimi 24 mesi di punteggi, per il grafico di storia
    out["storia"] = [[f"{r['k'][0]}-{r['k'][1]:02d}", round(r["pos"], 2)] for r in righe[-24:]]
    print(f"  Punteggio {out['punteggio']} (dati di {ult['k'][1]:02d}/{ult['k'][0]}), riferimento {out['riferimento']}, "
          f"crescita {out['crescita']}, credito {out['credito']}" + (f", ottimismo {out['ottimismo']}" if 'ottimismo' in out else ""))
    return out


# ================================================================ 2. MERCATO (da 02_mercato.py)
def sezione_mercato(cfg, prec):
    print("\n== MERCATO E FRENO (Yahoo) ==")
    m = cfg["mercato"]
    n_mm = int(cfg["strategia"].get("mediaMobileMesi", 10))
    prove = [m["ticker"]] + [x for x in m.get("alternativi", []) if x != m["ticker"]]
    oggi = dt.date.today()
    serie, usato = [], None
    for tk in prove:
        try:
            s = yahoo_mensile(tk, oggi.year - 12)
        except Exception as e:  # noqa
            print(f"   {tk}: non riuscito: {e}")
            continue
        completi = [x for x in s if (x[0].year, x[0].month) != (oggi.year, oggi.month)]
        if len(completi) >= n_mm + 1:
            serie, usato = completi, tk
            break
    if not serie:
        raise RuntimeError("nessuna borsa ha risposto per l'indice " + ", ".join(prove))
    prezzi = [v for _, v in serie]
    ultimo = prezzi[-1]
    mm = sum(prezzi[-n_mm:]) / n_mm
    consec = 0
    for i in range(len(prezzi) - 1, n_mm - 2, -1):
        if prezzi[i] < sum(prezzi[i - n_mm + 1:i + 1]) / n_mm:
            consec += 1
        else:
            break
    d = serie[-1][0]
    out = {"ticker": usato, "mese": f"{d.year}-{d.month:02d}-01", "prezzo": round(ultimo, 4),
           "mediaMobile": round(mm, 4), "scostamento": round(ultimo / mm - 1, 6), "sottoMedia": ultimo < mm,
           "mesiConsecutiviSotto": consec, "mediaMobileMesi": n_mm, "aggiornato": oggi.isoformat()}
    print(f"  {usato}: {ultimo:.2f} contro media {n_mm} mesi {mm:.2f} ({out['scostamento'] * 100:+.1f}%): "
          f"{'SOTTO la media, freno attivo' if out['sottoMedia'] else 'sopra la media'}")
    return out


# ================================================================ 3. PREZZI (da aggiorna_cruscotto.py)
PREF_SUFFIX = [".DE", ".MI", ".PA", ".AS", ".F", ".SG", ".SW", ".L"]
_fx_chart = {}


def yahoo_chart(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol) + "?range=5d&interval=1d"
    meta = json.loads(fetch_text(url, timeout=25))["chart"]["result"][0]["meta"]
    t = meta.get("regularMarketTime")
    d = (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(seconds=meta.get("gmtoffset") or 0)).date() if t else None
    return float(meta["regularMarketPrice"]), str(meta.get("currency", "")), d


def to_eur(price, cur):
    if cur == "EUR":
        return price
    if cur in ("GBp", "GBX"):
        price, cur = price / 100.0, "GBP"
    if cur not in _fx_chart:
        _fx_chart[cur] = yahoo_chart(f"{cur}EUR=X")[0]
    return price * _fx_chart[cur]


def yahoo_search(isin):
    url = "https://query2.finance.yahoo.com/v1/finance/search?q=" + urllib.parse.quote(isin) + "&quotesCount=10&newsCount=0"
    quotes = json.loads(fetch_text(url)).get("quotes", [])
    syms = [q["symbol"] for q in quotes if q.get("symbol") and q.get("quoteType") in ("ETF", "EQUITY", "MUTUALFUND")]

    def rank(s):
        for i, suf in enumerate(PREF_SUFFIX):
            if s.upper().endswith(suf):
                return i
        return 99
    return sorted(syms, key=rank)


def price_for(isin, override, cache):
    """(prezzo in EUR, simbolo, valuta, data) oppure RuntimeError."""
    cands = []
    for s in (override, cache.get(isin)):
        if s and s not in cands:
            cands.append(s)
    tried_search = False
    errors = []
    while True:
        for sym in cands:
            try:
                p, cur, d = yahoo_chart(sym)
                eur = to_eur(p, cur)
                cache[isin] = sym
                return eur, sym, cur, d
            except Exception as e:  # noqa
                errors.append(f"{sym}: {e}")
        if tried_search:
            raise RuntimeError("; ".join(errors[-3:]) or "nessun titolo trovato")
        tried_search = True
        try:
            cands = [s for s in yahoo_search(isin) if s not in cands]
        except Exception as e:  # noqa
            raise RuntimeError(f"ricerca ISIN fallita: {e}")
        if not cands:
            raise RuntimeError("ISIN non trovato su Yahoo Finance")
        time.sleep(0.4)


def sezione_prezzi(cfg, prec, cache):
    print("\n== PREZZI (Yahoo) ==")
    out = dict(prec)
    n_ok = 0
    for s in cfg["strumenti"]:
        isin = s["isin"]
        try:
            eur, sym, cur, d = price_for(isin, s.get("ticker"), cache)
            out[isin] = {"prezzo": round(eur, 4), "ticker": sym, "valuta": cur,
                         "data": d.isoformat() if d else dt.date.today().isoformat()}
            n_ok += 1
            print(f"  {s['nome'][:38]:<38} {sym:<11} {eur:>10.4f} EUR")
        except Exception as e:  # noqa
            avviso(f"prezzo di {s['nome']} ({isin}) non aggiornato: {e}")
        time.sleep(0.4)
    if n_ok == 0:
        raise RuntimeError("nessun prezzo scaricato")
    return out


# ================================================================ 4. STORICO ETF (da B2_prezzi_etf.py)
FINESTRA = 252
SALTO_ANOMALO = 0.25
SALTO_SENZA_SCAMBI = 0.08
SALTO_INIZIALE = 0.15
RIENTRO_SEDUTE = 5
RIENTRO_QUOTA = 0.25
_fx_cache = {}


def _chart_blocco(symbol, p1, p2, interval="1d"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol)
           + f"?period1={p1}&period2={p2}&interval={interval}&includeAdjustedClose=true&events=div%2Csplit")
    res = json.loads(fetch_text(url, tries=2))["chart"]["result"][0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    q = (res.get("indicators") or {}).get("quote") or [{}]
    close = q[0].get("close") or []
    volume = q[0].get("volume") or []
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    righe = []
    for i, t in enumerate(ts):
        c = close[i] if i < len(close) else None
        a = adj[i] if i < len(adj) else None
        v = volume[i] if i < len(volume) else None
        if c is None and a is None:
            continue
        off = meta.get("gmtoffset") or 0
        d = (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(seconds=off)).date()
        righe.append((d, None if c is None else float(c), None if a is None else float(a),
                      None if v is None else float(v)))
    return meta, righe


def yahoo_storico(symbol, anni=22, intervallo="1d"):
    """Storico giornaliero a blocchi di 8 anni. (meta, [(data, close, adjclose, volume)])."""
    oggi = dt.date.today()
    inizio = dt.date(oggi.year - anni, 1, 1)
    dati, meta = {}, {}
    a = inizio
    errori = []
    while a < oggi:
        b = min(dt.date(a.year + 8, a.month, 1), oggi)
        p1 = int(dt.datetime(a.year, a.month, a.day, tzinfo=dt.timezone.utc).timestamp())
        p2 = int(dt.datetime(b.year, b.month, b.day, tzinfo=dt.timezone.utc).timestamp()) + 2 * 86400
        try:
            m, righe = _chart_blocco(symbol, p1, p2, intervallo)
            meta = m or meta
            for riga in righe:
                dati[riga[0]] = riga
        except Exception as e:  # noqa
            errori.append(str(e))
        a = b
        time.sleep(0.3)
    if not dati:
        raise RuntimeError("nessun dato da Yahoo" + (f" ({errori[-1]})" if errori else ""))
    return meta, [dati[k] for k in sorted(dati)]


def aggiungi_mesi(d, m):
    y, mm = divmod(d.month - 1 + m, 12)
    y += d.year
    mm += 1
    ultimo = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mm - 1]
    return dt.date(y, mm, min(d.day, ultimo))


def serie_cambio(cur):
    if cur not in _fx_cache:
        _, righe = yahoo_storico(f"{cur}EUR=X")
        _fx_cache[cur] = [(r[0], r[1]) for r in righe if r[1]]
    return _fx_cache[cur]


def in_euro(meta, righe, distribuzione):
    cur = meta.get("currency") or "EUR"
    adj = str(distribuzione or "").lower().startswith("dist")
    pts, raw = [], []
    for riga in righe:
        d, c, a = riga[0], riga[1], riga[2]
        vol = riga[3] if len(riga) > 3 else None
        v = a if (adj and a is not None) else c
        if v is not None and v > 0:
            pts.append((d, float(v), vol))
        if c is not None and c > 0:
            raw.append((d, float(c)))
    nome_serie = "adjclose" if adj else "close"
    div = 1.0
    if cur in ("GBp", "GBX"):
        div, cur = 100.0, "GBP"
    pts = [(d, v / div, vol) for d, v, vol in pts]
    raw = [(d, v / div) for d, v in raw]
    if cur != "EUR":
        fx = serie_cambio(cur)
        if not fx:
            raise RuntimeError(f"cambio {cur}/EUR non disponibile")
        date_fx = [d for d, _ in fx]

        def cambio(d):
            i = bisect.bisect_right(date_fx, d) - 1
            return fx[i][1] if i >= 0 else None
        pts = [(d, v * cambio(d), vol) for d, v, vol in pts if cambio(d)]
        raw = [(d, v * cambio(d)) for d, v in raw if cambio(d)]
        nome_serie += f" convertita da {cur}"
    return pts, (raw[-1][1] if raw else None), nome_serie


def pulisci_serie(pts, dal=None):
    """Toglie dallo storico gli errori tipici di Yahoo (vedi B2_prezzi_etf.py)."""
    esito = {"tolti": [], "taglio": None, "dubbio": None, "dal": None}
    if dal:
        prima = len(pts)
        pts = [p for p in pts if p[0] >= dal]
        if len(pts) < prima:
            esito["dal"] = dal
    n = len(pts)
    if n < 2:
        return [(d, v) for d, v, _ in pts], esito
    date = [p[0] for p in pts]
    px = [p[1] for p in pts]
    senza_scambi = [p[2] is not None and p[2] == 0 for p in pts]
    tieni = [True] * n
    ultimo, i = 0, 1
    while i < n:
        x = px[i] / px[ultimo] - 1
        iniziale = i < FINESTRA
        soglia = SALTO_SENZA_SCAMBI if senza_scambi[i] else (SALTO_INIZIALE if iniziale else SALTO_ANOMALO)
        if abs(x) <= soglia:
            ultimo = i
            i += 1
            continue
        lim = abs(x) * RIENTRO_QUOTA
        rientro = next((k for k in range(i + 1, min(n, i + 1 + RIENTRO_SEDUTE)) if abs(px[k] / px[ultimo] - 1) <= lim),
                       None)
        if rientro is not None:
            for k in range(i, rientro):
                tieni[k] = False
                esito["tolti"].append((date[k], px[k] / px[ultimo] - 1))
            i = rientro
            continue
        if n - 1 - i < RIENTRO_SEDUTE:
            esito["dubbio"] = (date[i], x, "recente")
            ultimo = i
            i += 1
            continue
        if iniziale and abs(x) > SALTO_INIZIALE:
            for k in range(0, i):
                tieni[k] = False
            esito["taglio"] = (date[i], x)
            esito["tolti"] = [t for t in esito["tolti"] if t[0] > date[i]]
            ultimo = i
            i += 1
            continue
        if abs(x) > SALTO_ANOMALO and esito["dubbio"] is None:
            esito["dubbio"] = (date[i], x, "persistente")
        ultimo = i
        i += 1
    return [(d, v) for (d, v, _), t in zip(pts, tieni) if t], esito


def descrivi_pulizia(esito):
    parti = []
    if esito.get("dal"):
        parti.append(f"storico dal {esito['dal']:%d/%m/%Y} (config)")
    if esito.get("taglio"):
        d, x = esito["taglio"]
        parti.append(f"storico usato dal {d:%d/%m/%Y}: quel giorno un salto del {x:+.0%} che non rientra")
    if esito.get("tolti"):
        t = esito["tolti"]
        elenco = ", ".join(f"{d:%d/%m/%Y} {x:+.0%}" for d, x in t[:5]) + (", ..." if len(t) > 5 else "")
        parti.append(f"tolti {len(t)} prezzi isolati sbagliati ({elenco})")
    return "; ".join(parti)


def indicatori_numerici(pts, soglie):
    date = [d for d, _ in pts]
    px = [v for _, v in pts]
    n = len(px)
    out = {"ultima": date[-1], "n": n, "ultimo": px[-1], "anni": (date[-1] - date[0]).days / 365.25}
    dq = collections.deque()
    dd = []
    for i, p in enumerate(px):
        while dq and px[dq[-1]] <= p:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - FINESTRA:
            dq.popleft()
        if i >= FINESTRA - 1:
            dd.append((date[i], p / px[dq[0]] - 1))
    if dd:
        cur = dd[-1][1]
        out["max12"] = px[dq[0]]
        out["dd"] = cur
        out["pct"] = sum(1 for _, x in dd if x > cur + 1e-12) / len(dd)
        peggio = min(dd, key=lambda t: t[1])
        out["dd_min"] = peggio[1]
        valori = sorted(x for _, x in dd)
        out["soglie_dd"] = [valori[min(len(valori) - 1, max(0, int((1 - p) * len(valori))))] for p in soglie]
    return out


def stato_e_messaggio(out, esito, oggi, anni_min, giorni_vecchio):
    pulizia = descrivi_pulizia(esito)
    if esito.get("dubbio"):
        d, x, motivo = esito["dubbio"]
        stato = "DATI ANOMALI"
        if motivo == "recente":
            msg = f"salto del {x:+.0%} il {d:%d/%m/%Y}: troppo recente per sapere se e' un prezzo sbagliato"
        else:
            msg = (f"salto del {x:+.0%} il {d:%d/%m/%Y} che non rientra: controlla il ticker; se lo storico "
                   f"precedente e' sbagliato scrivi in config.json da che data usarlo (storicoDal)")
    elif (oggi - out["ultima"]).days > giorni_vecchio:
        stato, msg = "NON AGGIORNATO", f"ultimo prezzo del {out['ultima']:%d/%m/%Y}"
    elif out.get("dd") is None or out["anni"] < anni_min:
        stato = "STORICO BREVE"
        msg = f"{out['anni']:.1f} anni di storia: il ribasso non si giudica (minimo {anni_min:g})"
    else:
        stato, msg = "OK", ""
    if pulizia:
        msg = (msg + "; " if msg else "") + "dati ripuliti: " + pulizia
    return {"stato": stato, "msg": msg}


def _scarica_etf_verificato(e, cache, rif, toll):
    """(ticker, meta, serie EUR, nome serie, verifica, ultima chiusura EUR) oppure RuntimeError.
    Come B2: l'ultimo prezzo deve tornare con quello di riferimento (stesso strumento, prezzo
    di oggi) entro `toll`; se non torna si provano le altre quotazioni dello stesso ISIN. Mai un
    ticker presunto: se nessuno torna, l'ETF resta senza dati e l'app non lo compra."""
    isin = e["isin"]
    tentativi = []
    for t in (e.get("ticker"), cache.get(isin)):
        if t and t not in tentativi:
            tentativi.append(t)
    errori = []

    def prova(sym):
        meta, righe = yahoo_storico(sym)
        pts, ultimo_raw, ns = in_euro(meta, righe, e.get("distribuzione"))
        if len(pts) < 30 or not ultimo_raw:
            raise RuntimeError(f"{sym}: solo {len(pts)} prezzi")
        if rif:
            scarto = ultimo_raw / rif - 1
            if abs(scarto) > toll:
                raise RuntimeError(f"{sym}: ultimo prezzo {ultimo_raw:.2f} EUR contro {rif:.2f} EUR del prezzo di oggi "
                                   f"({scarto:+.1%}): non e' lo stesso strumento o il prezzo e' vecchio")
            ver = f"verificato col prezzo di oggi (scarto {scarto:+.2%})"
        else:
            ver = "ticker di config.json; prezzo di confronto non disponibile"
        return meta, pts, ns, ver, ultimo_raw

    for sym in tentativi:
        try:
            return (sym,) + prova(sym)
        except Exception as ex:  # noqa
            errori.append(str(ex))
    if not rif:
        raise RuntimeError("; ".join(errori) or "ticker mancante")
    try:
        cand = [s for s in yahoo_search(isin) if s not in tentativi]
    except Exception as ex:  # noqa
        cand = []
        errori.append(f"ricerca ISIN fallita: {ex}")
    for sym in cand[:5]:
        try:
            meta, pts, ns, ver, ult = prova(sym)
            avviso(f"{e['nome']}: il ticker di config.json non torna, uso {sym} (verificato sul prezzo)")
            return sym, meta, pts, ns, ver, ult
        except Exception as ex:  # noqa
            errori.append(str(ex))
        time.sleep(0.3)
    raise RuntimeError("; ".join(errori[-3:]))


def sezione_etf(cfg, prec, cache, prezzi):
    print("\n== STORICO ETF (Yahoo, in euro) ==")
    par = cfg["bilanciamento"]["parametri"]
    anni_min, vecchio = par["anniStoriaMin"], par["giorniPrezziVecchi"]
    toll = par.get("tolleranzaPrezzo", 0.03)
    soglie = tuple(f["percentile"] for f in par["fasce"])
    oggi = dt.date.today()
    out = dict(prec)
    n_ok = 0
    for e in cfg["bilanciamento"]["etf"] + cfg["bilanciamento"]["speculativi"]:
        isin = e["isin"]
        rif = None
        px = (prezzi or {}).get(isin)
        if px and px.get("data") and (oggi - dt.date.fromisoformat(px["data"])).days <= max(4, int(vecchio)):
            rif = px["prezzo"]
        try:
            sym, meta, pts, ns, ver, ultimo_raw = _scarica_etf_verificato(e, cache, rif, toll)
        except Exception as ex:  # noqa
            avviso(f"storico di {e['nome']} non aggiornato: {str(ex)[:220]}")
            continue
        cache[isin] = sym
        dal = dt.date.fromisoformat(e["storicoDal"]) if e.get("storicoDal") else None
        puliti, esito = pulisci_serie(pts, dal)
        if len(puliti) < 30:
            avviso(f"{e['nome']}: dopo la pulizia restano solo {len(puliti)} prezzi")
            continue
        ind = indicatori_numerici(puliti, soglie)
        ind["ultimo"] = ultimo_raw
        ind.update(stato_e_messaggio(ind, esito, oggi, anni_min, vecchio))
        s = {"ticker": sym, "ultimoPrezzo": round(ind["ultimo"], 4), "ultimaData": ind["ultima"].isoformat(),
             "anni": round(ind["anni"], 2), "stato": ind["stato"], "messaggio": ind["msg"] or None,
             "verifica": ver, "aggiornato": oggi.isoformat()}
        if ind.get("dd") is not None:
            s.update({"max12": round(ind["max12"], 4), "ribasso": round(ind["dd"], 6), "percentile": round(ind["pct"], 6),
                      "ribassoMax": round(ind["dd_min"], 6)})
            if ind["stato"] == "OK":
                s["soglieRibasso"] = [round(x, 6) for x in ind["soglie_dd"]]
        out[isin] = s
        n_ok += 1
        print(f"  {e['nome'][:36]:<36} {sym:<9} {ind['anni']:4.1f} anni  ult. {ind['ultimo']:>9.2f} EUR  "
              f"ribasso 12m {ind.get('dd', 0):+.1%}  {ind['stato']}")
        if ind["stato"] == "DATI ANOMALI":
            avviso(f"{e['nome']}: {ind['msg']}")
        time.sleep(0.4)
    if n_ok == 0:
        raise RuntimeError("nessun ETF aggiornato")
    return out


# ================================================================ 5. GRAHAM (da B3_graham_azioni.py + formule del foglio Graham)
MINOR = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}
TOLLERANZA = 0.25
ATTESE_RATE_LIMIT = (20, 60, 120)


def num(x):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


class Fetcher:
    def __init__(self, yf):
        self.yf, self._fx = yf, {}

    def fx(self, a, b):
        if a == b:
            return 1.0
        k = (a, b)
        if k not in self._fx:
            h = self.yf.Ticker(f"{a}{b}=X").history(period="5d")["Close"].dropna()
            self._fx[k] = float(h.iloc[-1]) if len(h) else None
        return self._fx[k]

    def resolve(self, isin, manual):
        if manual:
            return manual
        res = self.yf.Search(isin, max_results=8).quotes
        for q in res:
            if q.get("quoteType") == "EQUITY" and q.get("exchange") not in ("PNK", "OQB", "OQX", "OTC", "OTCM", "PINK"):
                return q["symbol"]
        for q in res:
            if q.get("quoteType") == "EQUITY":
                return q["symbol"]
        if res:
            return res[0]["symbol"]
        raise ValueError("ISIN non trovato su Yahoo (scrivi il ticker in config.json)")

    def company(self, isin, manual):
        out = {}
        tk = self.resolve(isin, manual)
        t = self.yf.Ticker(tk)
        info = t.info or {}
        out["tick"] = tk
        out["name"] = info.get("shortName") or info.get("longName")
        sector = info.get("sector")
        out["sector"] = sector
        fin_sector = sector == "Financial Services"
        cur = info.get("currency")
        fcur = info.get("financialCurrency") or cur
        price = num(info.get("currentPrice") or info.get("regularMarketPrice"))
        mcap = num(info.get("marketCap"))
        div = 1
        if cur in MINOR:
            cur, div = MINOR[cur]
        if fcur in MINOR:
            fcur = MINOR[fcur][0]
        if price is not None:
            price /= div
        out["price"], out["cur"] = price, cur
        f2p = self.fx(fcur, cur) if cur and fcur else 1.0
        p2e = self.fx(cur, "EUR") if cur else None
        f2e = self.fx(fcur, "EUR") if fcur else None
        out["p2e"] = p2e
        conv = lambda v: None if v is None or f2p is None else v * f2p  # noqa: E731
        avvisi = []

        def per_azione(valore, rapporto_yahoo, etichetta):
            if valore is None:
                return None
            if price is None or not rapporto_yahoo or rapporto_yahoo <= 0 or valore <= 0:
                return conv(valore)
            ipotesi = [m for m in dict.fromkeys([f2p, 1.0, 1.0 / div, (f2p or 1.0) / div]) if m]
            for m in ipotesi:
                if abs(price / (valore * m) / rapporto_yahoo - 1) <= TOLLERANZA:
                    if m != f2p:
                        avvisi.append(f"{etichetta} corretto per valuta")
                    return valore * m
            avvisi.append(f"VERIFICA VALUTA: {etichetta} non torna con Yahoo "
                          f"({price / conv(valore):.1f} contro {rapporto_yahoo:.1f})" if conv(valore) else f"VERIFICA {etichetta}")
            return conv(valore)

        out["eps_ttm"] = per_azione(num(info.get("trailingEps")), num(info.get("trailingPE")), "P/E")
        out["bvps"] = per_azione(num(info.get("bookValue")), num(info.get("priceToBook")), "P/B")
        rev = num(info.get("totalRevenue"))
        out["rev"] = rev * f2e / 1e6 if rev is not None and f2e else None
        out["mcap"] = mcap * p2e / 1e6 if mcap is not None and p2e else None
        p_raw = num(info.get("currentPrice") or info.get("regularMarketPrice"))
        hi52, ma200 = num(info.get("fiftyTwoWeekHigh")), num(info.get("twoHundredDayAverage"))
        if p_raw and hi52:
            out["dd52"] = p_raw / hi52 - 1
        if p_raw and ma200:
            out["ma200"] = p_raw / ma200 - 1
        tpe, fpe = num(info.get("trailingPE")), num(info.get("forwardPE"))
        if tpe and fpe and tpe > 0 and fpe > 0:
            out["fwd_var"] = max(-0.99, min(9.99, tpe / fpe - 1))
        if not fin_sector:
            debito, cassa, ebitda = num(info.get("totalDebt")), num(info.get("totalCash")), num(info.get("ebitda"))
            if debito is not None and ebitda is not None:
                netto = debito - (cassa or 0)
                if ebitda > 0:
                    out["nd_ebitda"] = max(-99.0, min(99.0, netto / ebitda))
                else:
                    out["nd_ebitda"] = 0.0 if netto <= 0 else 99.0
            out["cr"] = num(info.get("currentRatio"))
            de = num(info.get("debtToEquity"))
            out["de"] = de / 100 if de is not None else None
            fcf = conv(num(info.get("freeCashflow")))
            out["fcf"] = fcf / mcap if fcf is not None and mcap else None
        out["roe"] = num(info.get("returnOnEquity"))
        pay = num(info.get("payoutRatio"))
        out["pay"] = pay
        fs = t.financials

        def series(name):
            if fs is None or name not in fs.index:
                return []
            s = fs.loc[name].dropna().sort_index()
            return [float(v) for v in s.values]
        ni, eps = series("Net Income"), series("Diluted EPS") or series("Basic EPS")
        out["posy"], out["yn"] = (sum(1 for v in ni if v > 0), len(ni)) if ni else (None, None)
        if eps:
            last3 = [v * f2p for v in eps[-3:]] if f2p else None
            out["eps_avg"] = sum(last3) / len(last3) if last3 else None
            if len(eps) >= 2 and eps[0] > 0 and eps[-1] > 0:
                out["cagr"] = (eps[-1] / eps[0]) ** (1 / (len(eps) - 1)) - 1
            ea, et = out.get("eps_avg"), out.get("eps_ttm")
            if ea and et and ea > 0 and et > 0 and max(ea / et, et / ea) > 3:
                avvisi.append("VERIFICA VALUTA: EPS medio e EPS 12 mesi molto diversi")
        if not fin_sector:
            ebit, intr = series("EBIT"), series("Interest Expense")
            if ebit:
                i = abs(intr[-1]) if intr else 0
                out["ic"] = 99.0 if i == 0 else max(-99.0, min(99.0, ebit[-1] / i))
        dv = t.dividends
        years = sorted({d.year for d in dv.index}) if dv is not None and len(dv) else []
        now = dt.date.today().year
        y = now if now in years else now - 1
        n = 0
        while y in years:
            n += 1
            y -= 1
        out["divy"] = n
        if price and dv is not None and len(dv):
            last = dv.index[-1]
            ttm = float(dv[dv.index > last - dt.timedelta(days=365)].sum()) / div
            out["dy"] = ttm / price
        else:
            out["dy"] = 0.0
        out["status"] = "OK - " + "; ".join(avvisi) if avvisi else "OK"
        return out


def e_rate_limit(e):
    t = f"{type(e).__name__} {e}".lower()
    return "ratelimit" in t or "rate limit" in t or "too many requests" in t or "429" in t


def con_tentativi(fn, *args):
    for i, attesa in enumerate(ATTESE_RATE_LIMIT + (None,)):
        try:
            return fn(*args)
        except Exception as e:  # noqa
            if attesa is None or not e_rate_limit(e):
                raise
            print(f"   Yahoo chiede di rallentare: aspetto {attesa} s (tentativo {i + 2}/{len(ATTESE_RATE_LIMIT) + 1})")
            time.sleep(attesa)


def aaa_fred():
    """Ultimo rendimento delle obbligazioni AAA (FRED, serie DAAA)."""
    s = fred("DAAA")
    d, v = s[-1]
    return v, d.isoformat()


# ---- punteggio: le formule del foglio Graham (colonne D-J, AF-AY) con i parametri di config.json
def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isnan(x)


def graham_calcola(d, gp, aaa):
    """d: dati grezzi di una societa' (nomi come le colonne dello script). Restituisce i risultati del foglio."""
    P = gp
    G = d.get("price")
    fattore = P["aaaRiferimento"] / aaa if P.get("formulaRivista", 1) == 1 else 1.0
    eps_avg, eps_ttm, bvps = d.get("eps_avg"), d.get("eps_ttm"), d.get("bvps")
    pe = ("n.s." if not eps_avg > 0 else G / eps_avg) if (_isnum(G) and _isnum(eps_avg)) else ""
    pb = ("n.s." if not bvps > 0 else G / bvps) if (_isnum(G) and _isnum(bvps)) else ""
    if pe == "n.s." or pb == "n.s.":
        pepb = "n.s."
    elif _isnum(pe) and _isnum(pb):
        pepb = pe * pb
    else:
        pepb = ""
    posy, yn = d.get("posy"), d.get("yn")
    shr = (posy / yn if yn > 0 else "") if (_isnum(posy) and _isnum(yn)) else ""
    cagr = d.get("cagr")
    g = min(P["gMax"], max(P["gMin"], cagr * 100 if _isnum(cagr) else 0))
    epsb = eps_avg if _isnum(eps_avg) else (eps_ttm if _isnum(eps_ttm) else "")
    if not _isnum(epsb):
        H = ""
    elif epsb <= 0:
        H = "n.s."
    else:
        H = epsb * (8.5 + 2 * g) * fattore
    if H == "n.s.":
        I = "n.s."
    elif _isnum(H) and _isnum(G):
        I = (H - G) / H if H > 0 else "n.s."
    else:
        I = ""

    def crit(v, c0, c1):
        if v == "" or v is None:
            return ""
        if v == "n.s.":
            return 0.0
        if not _isnum(v):
            return ""
        return max(0.0, min(1.0, (v - c0) / (c1 - c0)))
    valori = {"rev": d.get("rev"), "cr": d.get("cr"), "nd_ebitda": d.get("nd_ebitda"), "shr": shr, "divy": d.get("divy"),
              "cagr": cagr, "pe": pe, "pb": pb, "pepb": pepb, "mos": I, "roe": d.get("roe"), "ic": d.get("ic"),
              "fcf": d.get("fcf")}
    punti = {}
    for c in P["criteri"]:
        k = c["chiave"]
        if k == "pay":
            x = d.get("pay")
            punti[k] = "" if (not _isnum(x) or x <= 0) else max(0.0, min(1.0, (x - c["soglia0"]) / (c["soglia100"] - c["soglia0"])))
        else:
            punti[k] = crit(valori.get(k), c["soglia0"], c["soglia100"])
    pesi = {c["chiave"]: c["peso"] for c in P["criteri"]}
    w_num = sum(pesi[k] for k, v in punti.items() if _isnum(v))
    w_tot = sum(pesi.values())
    score = (sum(pesi[k] * v for k, v in punti.items() if _isnum(v)) / w_num * 100) if w_num else None
    cover = w_num / w_tot if w_tot else None
    if score is None:
        verdetto = "In attesa dati"
    elif cover < P["coperturaMin"]:
        verdetto = "Dati insufficienti"
    elif score >= P["sogliaCandidata"]:
        verdetto = "Candidata"
    elif score >= P["sogliaInteressante"]:
        verdetto = "Interessante"
    elif score >= P["sogliaNeutra"]:
        verdetto = "Neutra"
    else:
        verdetto = "Scartare"
    al = []
    if _isnum(eps_ttm) and eps_ttm <= 0:
        al.append("Utili negativi.")
    if _isnum(posy) and _isnum(yn) and posy < yn:
        al.append("Anni in perdita.")
    if _isnum(yn) and yn < 3:
        al.append("Storico breve.")
    if d.get("sector") == "Financial Services":
        al.append("Finanziaria: current ratio/debito non applicabili.")
    if _isnum(I) and I < 0:
        al.append("Prezzo sopra il valore Graham.")
    dd52, ma200 = d.get("dd52"), d.get("ma200")
    if _isnum(dd52) and dd52 <= P["allertaCalo52"] and _isnum(ma200) and ma200 <= -P["allertaSottoMedia200"]:
        al.append("In forte calo.")
    fv = d.get("fwd_var")
    if _isnum(fv) and fv <= P["allertaUtiliAttesi"]:
        al.append("Utili attesi in calo (picco del ciclo?).")
    return {"punteggio": score, "verdetto": verdetto, "copertura": cover, "valore": H, "margine": I,
            "allerte": " ".join(al), "g": g, "fattore": fattore}


def sezione_graham(cfg, prec, forza, ogni_giorni):
    print("\n== GRAHAM (yfinance, FRED) ==")
    gp = cfg["graham"]
    oggi = dt.date.today()
    out = dict(prec.get("azioni", {}))
    vecchi = [dt.date.fromisoformat(v["aggiornato"]) for v in out.values() if v.get("aggiornato")]
    if not forza and vecchi and len(out) >= len(cfg["bilanciamento"]["azioni"]) and (oggi - min(vecchi)).days < ogni_giorni:
        print(f"  dati Graham di {(oggi - min(vecchi)).days} giorni fa: non li rifaccio (si rinfrescano dopo {ogni_giorni})")
        return prec
    try:
        import yfinance as yf
    except ModuleNotFoundError:
        raise RuntimeError("manca yfinance (pip install yfinance)")
    aaa = prec.get("aaa") or {"rendimento": gp["aaaDefault"], "data": None}
    try:
        v, d = aaa_fred()
        aaa = {"rendimento": v, "data": d}
        print(f"  Rendimento AAA: {v}% al {d}")
    except Exception as e:  # noqa
        avviso(f"rendimento AAA non aggiornato ({e}): uso {aaa['rendimento']}%")
    F = Fetcher(yf)
    n_ok, bloccati = 0, 0
    for a in cfg["bilanciamento"]["azioni"]:
        isin = a["isin"]
        try:
            raw = con_tentativi(F.company, isin, a.get("ticker"))
            ris = graham_calcola(raw, gp, aaa["rendimento"])
            p2e = raw.get("p2e")
            out[isin] = {
                "nome": raw.get("name") or a["nome"], "ticker": raw["tick"], "punteggio": ris["punteggio"],
                "verdetto": ris["verdetto"], "copertura": ris["copertura"],
                "valoreLocale": ris["valore"] if _isnum(ris["valore"]) else None,
                "prezzoLocale": raw.get("price"), "valuta": raw.get("cur"),
                "cambioLocale": (1.0 / p2e) if p2e else None,
                "margine": ris["margine"] if _isnum(ris["margine"]) else None,
                "allerte": ris["allerte"] or None, "aggiornato": oggi.isoformat(), "esito": raw.get("status", "OK")}
            n_ok += 1
            bloccati = 0
            sc = ris["punteggio"]
            print(f"  {isin}  {raw['tick']:<10} {a['nome'][:24]:<24} punteggio "
                  f"{(format(sc, '.1f') if sc is not None else '-'):>5}  {ris['verdetto']}")
        except Exception as e:  # noqa
            avviso(f"Graham di {a['nome']} ({isin}) non aggiornato: {e}")
            bloccati = bloccati + 1 if e_rate_limit(e) else 0
            if bloccati >= 3:
                avviso("Yahoo continua a bloccare le richieste: mi fermo e tengo i dati precedenti")
                break
        time.sleep(1)
    if n_ok == 0:
        raise RuntimeError("nessuna azione aggiornata")
    return {"azioni": out, "aaa": aaa}


# ================================================================ programma
def carica_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa
        return default


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggiorna dati/dati.json")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dati", "dati.json"))
    ap.add_argument("--sezioni", default="pendolo,mercato,prezzi,etf,graham")
    ap.add_argument("--solo-test", action="store_true", help="non scrive niente")
    ap.add_argument("--graham-ogni", type=int, default=0, help="giorni minimi fra due aggiornamenti Graham (0 = sempre)")
    ap.add_argument("--forza-graham", action="store_true")
    a = ap.parse_args(argv)
    sezioni = [s.strip() for s in a.sezioni.split(",") if s.strip()]
    cfg = carica_json(a.config, None)
    if not cfg:
        sys.exit(f"config.json non trovato o non valido: {a.config}")
    prec = carica_json(a.out, {})
    cache_path = os.path.join(os.path.dirname(a.out), "cache_ticker.json")
    cache = carica_json(cache_path, {})
    dati = {k: prec[k] for k in ("pendolo", "mercato", "prezzi", "etf", "graham", "aaa") if k in prec}
    oggi = dt.datetime.now(dt.timezone.utc)
    esiti = dict(prec.get("fonti", {}))
    for nome in sezioni:
        try:
            if nome == "pendolo":
                dati["pendolo"] = sezione_pendolo(cfg, prec.get("pendolo", {}))
            elif nome == "mercato":
                dati["mercato"] = sezione_mercato(cfg, prec.get("mercato", {}))
            elif nome == "prezzi":
                dati["prezzi"] = sezione_prezzi(cfg, prec.get("prezzi", {}), cache)
            elif nome == "etf":
                dati["etf"] = sezione_etf(cfg, prec.get("etf", {}), cache, dati.get("prezzi"))
            elif nome == "graham":
                r = sezione_graham(cfg, {"azioni": prec.get("graham", {}), "aaa": prec.get("aaa")},
                                   a.forza_graham, a.graham_ogni)
                dati["graham"], dati["aaa"] = r["azioni"], r["aaa"]
            else:
                print(f"sezione sconosciuta: {nome}")
                continue
            esiti[nome] = {"ok": True, "il": oggi.isoformat(timespec="seconds")}
        except Exception as e:  # noqa
            avviso(f"sezione {nome} non aggiornata: {e}")
            esiti[nome] = {"ok": False, "il": esiti.get(nome, {}).get("il"), "errore": str(e)[:200]}
    out = {"versione": 1, "generato": oggi.isoformat(timespec="seconds"), "fonti": esiti, "avvisi": AVVISI}
    out.update(dati)
    print(f"\nSezioni riuscite: {', '.join(k for k in sezioni if esiti.get(k, {}).get('ok')) or 'nessuna'}")
    if a.solo_test:
        print("--solo-test: non scrivo niente.")
        return 0
    if not any(esiti.get(k, {}).get("ok") for k in sezioni):
        print("Nessuna sezione aggiornata: non cambio dati.json.")
        return 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"Scritto {a.out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
