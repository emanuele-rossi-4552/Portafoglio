/* Motore di calcolo dell'app: stesse regole di Portafoglio.xlsx (Cruscotto, Parametri) e
   Bilanciamento.xlsx (Calcolo, ETF, Azioni). Funzioni pure: stato in ingresso, risultati in uscita. */
(function (root) {
  'use strict';

  var CLASSI = ['Azionario', 'Obbligazionario', 'Oro', 'Liquidità'];
  var BIG = 9e15;

  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function num(x, d) { return isNum(x) ? x : (d === undefined ? null : d); }
  function clamp(x, a, b) { return Math.min(b, Math.max(a, x)); }
  function eur0(x) { return Math.round(x).toLocaleString('it-IT'); }
  function pct0(x) { return (x * 100).toFixed(0) + '%'; }
  function fx(x, d) { return Number(x).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function floorTo(x, step) { step = Math.max(1, step || 1); return Math.floor(x / step + 1e-9) * step; }
  function ceilTo(x, step) { step = Math.max(1, step || 1); return Math.ceil(x / step - 1e-9) * step; }
  function giorniTra(isoA, dataB) {
    if (!isoA) return null;
    var a = new Date(isoA.length <= 10 ? isoA + 'T00:00:00' : isoA);
    var b = new Date(dataB.getFullYear(), dataB.getMonth(), dataB.getDate());
    var a0 = new Date(a.getFullYear(), a.getMonth(), a.getDate());
    return Math.round((b - a0) / 86400000);
  }
  function meseChiave(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }

  /* ------------------------------------------------------------ posizioni */
  function valorePosizione(p) {
    var q = num(p.qta, 0), px = num(p.prezzo, 0);
    return p.tipo === 'Obbligazione' ? q * px / 100 : q * px;
  }

  /* ------------------------------------------------------------ curva */
  function dalleCurva(curva, x) {
    var n = curva.length, g, h;
    if (x <= curva[0].p) { g = 0; h = 0; }
    else if (x >= curva[n - 1].p) { g = n - 2; h = 1; }
    else {
      g = 0;
      for (var i = 0; i < n; i++) if (curva[i].p <= x) g = i;
      h = (x - curva[g].p) / (curva[g + 1].p - curva[g].p);
    }
    var lerp = function (k) { return curva[g][k] + (curva[g + 1][k] - curva[g][k]) * h; };
    var az = lerp('az'), ob = lerp('ob'), oro = lerp('oro');
    return { az: az, ob: ob, oro: oro, liq: 1 - az - ob - oro, segmento: g + 1, frazione: h };
  }

  /* ------------------------------------------------------------ Portafoglio */
  /* st: {snap, posizioni, pendolo:{punteggio, riferimento}, mercato:{sottoMedia}}
     opt: {punteggio} per provare un altro punteggio */
  function calcolaPortafoglio(st, opt) {
    opt = opt || {};
    var S = st.snap.portafoglio.strategia;
    var val = { 'Azionario': 0, 'Obbligazionario': 0, 'Oro': 0, 'Liquidità': 0 };
    var costoTot = 0, valTot = 0;
    st.posizioni.forEach(function (p) {
      if (p.archiviata) return;
      var v = valorePosizione(p);
      if (val[p.classe] !== undefined) val[p.classe] += v;
      valTot += v; costoTot += num(p.costo, 0);
    });
    var tot = CLASSI.reduce(function (s, c) { return s + val[c]; }, 0);
    var low = S.zonaNeutra[0], high = S.zonaNeutra[1];
    var oggiP = opt.punteggio != null ? clamp(opt.punteggio, 0, 100) : num(st.pendolo.punteggio);
    var out = { valori: val, totale: tot, costoTotale: costoTot, punteggioOggi: oggiP, ok: oggiP != null && tot > 0 };
    var pesi = {};
    CLASSI.forEach(function (c) { pesi[c] = tot > 0 ? val[c] / tot : 0; });
    out.pesi = pesi;
    if (oggiP == null || tot <= 0) { out.righe = []; return out; }

    var fuori = (oggiP <= low || oggiP >= high || low >= high);
    var rif, rifNota;
    if (opt.punteggio != null) { rif = oggiP; rifNota = 'punteggio di prova: la zona neutra non si applica'; }
    else if (fuori) { rif = oggiP; rifNota = 'fuori dalla zona neutra ' + low + '-' + high + ': vale il punteggio di oggi'; }
    else { rif = num(st.pendolo.riferimento, oggiP); rifNota = 'dentro la zona neutra ' + low + '-' + high + ': vale l’ultimo punteggio fuori dalla zona'; }
    out.punteggioRif = rif; out.riferimentoNota = rifNota; out.fuoriZona = fuori;

    // 1. curva
    var c = dalleCurva(S.curva, rif);
    var passo = { curva: { Azionario: c.az, Obbligazionario: c.ob, Oro: c.oro, 'Liquidità': c.liq } };
    // 2. pavimento della liquidità
    var liq57 = Math.max(S.pavimentoLiquidita, c.liq);
    var az57 = c.az - (liq57 - c.liq);
    // 3. freno
    var az58 = az57, frenoAttivo = false;
    var sotto = st.mercato && st.mercato.sottoMedia === true;
    if (S.frenoAttivoParametri && sotto && az57 > pesi.Azionario) { az58 = pesi.Azionario; frenoAttivo = true; }
    var liq58 = liq57 + (az57 - az58);
    // 4. tetto in euro sulla cassa
    var liq59 = S.tettoCassaEuro > 0 && tot > 0 ? Math.min(liq58, S.tettoCassaEuro / tot) : liq58;
    var ob59 = c.ob + (liq58 - liq59);
    var ob = { Azionario: az58, Obbligazionario: ob59, Oro: c.oro, 'Liquidità': liq59 };
    passo.pavimento = { Azionario: az57, Obbligazionario: c.ob, Oro: c.oro, 'Liquidità': liq57 };
    passo.freno = { Azionario: az58, Obbligazionario: c.ob, Oro: c.oro, 'Liquidità': liq58 };
    passo.tetto = ob;
    out.passi = passo; out.obiettivi = ob;
    out.freno = {
      parametroAttivo: !!S.frenoAttivoParametri, sottoMedia: st.mercato ? st.mercato.sottoMedia : null,
      scostamento: st.mercato ? st.mercato.scostamento : null, attivo: frenoAttivo
    };
    out.tettoCassaAttivo = liq59 < liq58 - 1e-12;

    // 5. fasce, segnali, importi
    var righe = [];
    var somma3 = 0;
    CLASSI.forEach(function (cl) {
      var D = ob[cl], tol = S.tolleranze[cl];
      var mn = Math.max(0, D - tol), mx = Math.min(1, D + tol);
      var W = pesi[cl];
      var G = W < mn ? W - mn : (W > mx ? W - mx : 0);
      var sign = G === 0 ? 'IN FASCIA' : ((G < 0 ? 'SOTTO ' : 'SOPRA ') +
        (Math.abs(G) >= S.scostForte ? '(forte)' : (Math.abs(G) >= S.scostLieve ? '(medio)' : '(lieve)')));
      var I = 0;
      if (cl !== 'Liquidità') { I = G === 0 ? 0 : D * tot - val[cl]; somma3 += I; }
      righe.push({ classe: cl, valore: val[cl], peso: W, obiettivo: D, min: mn, max: mx, scostamento: G, segnale: sign, daMuovere: I });
    });
    var liqRiga = righe[3]; liqRiga.daMuovere = -somma3;
    righe.forEach(function (r) {
      if (r.classe === 'Liquidità') {
        r.azione = Math.abs(r.daMuovere) < 1 ? 'ferma' : (r.daMuovere < 0 ? 'scende comprando le altre classi' : 'sale vendendo le altre classi');
      } else if (r.scostamento === 0) r.azione = 'ferma: dentro la fascia';
      else if (Math.abs(r.daMuovere) < S.ordineMinimo) r.azione = 'aspetta il mese prossimo: sotto l’ordine minimo';
      else r.azione = (r.daMuovere > 0 ? 'COMPRA ' : 'VENDI ') + eur0(Math.abs(r.daMuovere)) + ' €';
    });
    out.righe = righe;
    out.buffer = righe[0].daMuovere;
    out.rendita = null;
    return out;
  }

  /* ------------------------------------------------------------ percentile del ribasso */
  function percentileRibasso(dd, s) {
    if (dd >= 0) return 0;
    var pts = [[0, 0]];
    if (isNum(s.ribassoMax)) pts.push([s.ribassoMax, 1]);
    (s.soglieRibasso || []).forEach(function (x, i) { if (isNum(x)) pts.push([x, [0.75, 0.9, 0.975][i]]); });
    if (isNum(s.ribasso) && isNum(s.percentile)) pts.push([s.ribasso, s.percentile]);
    pts.sort(function (a, b) { return a[0] - b[0]; });
    // pct non cala al calare del ribasso (dd piu' negativo -> pct piu' alto)
    for (var i = pts.length - 2; i >= 0; i--) pts[i][1] = Math.max(pts[i][1], pts[i + 1][1]);
    if (dd <= pts[0][0]) return pts[0][1];
    for (var k = 0; k < pts.length - 1; k++) {
      var a = pts[k], b = pts[k + 1];
      if (dd >= a[0] && dd <= b[0]) {
        if (b[0] === a[0]) return Math.max(a[1], b[1]);
        return a[1] + (b[1] - a[1]) * (dd - a[0]) / (b[0] - a[0]);
      }
    }
    return 0;
  }

  /* ------------------------------------------------------------ Bilanciamento */
  /* st aggiunge: operazioni [{ts, isin, verso, importo}], oggi (Date) */
  function calcolaBilanciamento(st, pf, opt) {
    opt = opt || {};
    var B = st.snap.bilanciamento, PA = B.parametri, G = PA.graham;
    var oggi = st.oggi || new Date();
    var arrot = Math.max(1, PA.arrotondamento || 1);
    var res = { avvisi: [] };

    // --- posizioni raggruppate per ISIN
    var perIsin = {};
    st.posizioni.forEach(function (p) {
      if (p.archiviata || !p.isin) return;
      if (p.classe !== 'Azionario') return;
      var o = perIsin[p.isin] || (perIsin[p.isin] = { valore: 0, costo: 0, qta: 0, prezzo: null, tipi: {}, nome: p.nome });
      o.valore += valorePosizione(p); o.costo += num(p.costo, 0); o.qta += num(p.qta, 0);
      o.prezzo = num(p.prezzo, o.prezzo); o.tipi[p.tipo] = true;
    });
    function datiEtf(isin) { var o = perIsin[isin]; return o && o.tipi.ETF ? o : null; }
    function datiAz(isin) { var o = perIsin[isin]; return o && o.tipi.Azione ? o : null; }

    // --- acquisti e vendite del mese
    var chiaveMese = meseChiave(oggi);
    var compMese = {}, vendMese = {};
    if (st.snap.fonti && st.snap.fonti.meseDati === chiaveMese) {
      Object.keys(B.compratoMese || {}).forEach(function (k) { compMese[k] = B.compratoMese[k]; });
      Object.keys(B.vendutoMese || {}).forEach(function (k) { vendMese[k] = B.vendutoMese[k]; });
    }
    var tSnap = isNum(st.tOps) ? st.tOps : (st.snap.generato ? new Date(st.snap.generato).getTime() : 0);
    (st.operazioni || []).forEach(function (o) {
      if (o.annullata) return;
      var d = new Date(o.ts);
      if (meseChiave(d) !== chiaveMese || d.getTime() <= tSnap) return;
      var tgt = o.verso === 'COMPRA' ? compMese : vendMese;
      tgt[o.isin] = (tgt[o.isin] || 0) + o.importo;
    });
    var B55 = 0;
    st.posizioni.forEach(function () { });
    Object.keys(compMese).forEach(function (k) { if (perIsin[k]) B55 += compMese[k]; });

    // --- Calcolo
    var B5 = pf.valori.Azionario, B6 = pf.buffer, B9 = B6, B10 = B5 + B6, B11 = pf.totale;
    var B12 = PA.baseLimiti === 'AZIONARIO AUTORIZZATO' ? B10 : B11;
    var B13 = isNum(PA.ordineMinimo) ? PA.ordineMinimo : (isNum(st.snap.portafoglio.strategia.ordineMinimo) ? st.snap.portafoglio.strategia.ordineMinimo : 500);
    var B14 = isNum(PA.aliquota) ? PA.aliquota : 0.26;
    var B16 = PA.quotaMinEtf, B17 = PA.tettoAzioni;

    var etfDef = B.etf.slice(0, 8), specDef = B.speculativi.slice(0, 2);
    var etfV = etfDef.map(function (e) { var o = datiEtf(e.isin); return o ? o.valore : 0; });
    var specV = specDef.map(function (e) { var o = datiEtf(e.isin); return o ? o.valore : 0; });
    var azDef = B.azioni.slice(0, 12);
    var azV = azDef.map(function (a) { var o = datiAz(a.isin); return o ? o.valore : 0; });
    var B18 = etfV.reduce(function (a, b) { return a + b; }, 0);
    var B19 = specV.reduce(function (a, b) { return a + b; }, 0);
    var B20 = azV.reduce(function (a, b) { return a + b; }, 0);
    var B21 = Math.max(0, Math.round((B5 - B18 - B19 - B20) * 100) / 100);
    var B22 = B20, B23 = B17 * B10;
    var B29 = B12 * PA.pesoMax, B30 = B12 * PA.pesoMedio, B31 = B12 * PA.pesoMin, B32 = isNum(G.margineMin) ? G.margineMin : 0.3;

    // validita' dei dati
    var etaSnap = st.snap.generato ? giorniTra(st.snap.generato, oggi) : 999;
    var sommaPesi = etfDef.reduce(function (s, e) { return s + e.peso; }, 0);
    var B38 = (etaSnap <= 35 && Math.abs(sommaPesi - 1) <= 0.0005 && etfDef.length > 0) ? 1 : 0;
    var motivoBlocco = B38 ? '' : (etaSnap > 35 ? 'Dati importati dal PC vecchi di ' + etaSnap + ' giorni: importane di nuovi.' : 'Paniere ETF non valido: i pesi non sommano 100%.');

    var B24 = PA.parteTettoNonInvestita === 'ETF CORE' ? null : B16 * B10; // sotto si completa con Azioni K22

    // --- AZIONI (primo passo: obiettivo, vendite livello 1)
    var az = azDef.map(function (a, i) {
      var o = datiAz(a.isin) || { valore: 0, costo: 0, qta: 0, prezzo: null };
      var I = azV[i];
      var prezzoEur = o.prezzo;
      var valoreStimatoEur = a.valoreStimatoEur;
      var cambio = isNum(a.cambioLocale) && a.cambioLocale > 0 ? a.cambioLocale : null;
      var margine = (cambio && isNum(a.valoreLocale) && a.valoreLocale > 0 && isNum(prezzoEur) && prezzoEur > 0) ? 1 - prezzoEur * cambio / a.valoreLocale : null;
      var gg = giorniTra(a.aggiornato, oggi);
      var stato;
      if (!isNum(a.punteggio)) stato = 'MANCANTI';
      else if (a.verdetto === 'Dati insufficienti' || a.verdetto === 'In attesa dati' || !a.verdetto) stato = 'INSUFFICIENTI';
      else if (a.esito && String(a.esito).slice(0, 6) === 'ERRORE') stato = 'ERRORE';
      else if (gg == null) stato = 'SENZA DATA';
      else if (gg > G.giorniValidi) stato = 'NON AGGIORNATI';
      else stato = 'OK';
      var regola = (G.verdetti && G.verdetti[a.verdetto]) || null;
      var AW = (stato === 'OK' && isNum(a.punteggio) && isNum(a.punteggioRiferimento) && a.punteggioRiferimento > 0) ? a.punteggio - a.punteggioRiferimento : null;
      var AC = stato === 'OK' && regola && regola.aumenti ? 'SI' : 'NO';
      var AX;
      if (AW == null) AX = 1;
      else if (Math.abs(AW) < G.variazioneMin) AX = 1;
      else if (AW < 0) AX = a.punteggio / a.punteggioRiferimento;
      else AX = AC === 'SI' ? Math.min(G.aumentoMax, a.punteggio / a.punteggioRiferimento) : 1;
      var AB;
      if (stato !== 'OK') AB = 1;
      else {
        var f = regola && isNum(regola.fattore) ? regola.fattore : 1;
        AB = f * AX;
      }
      var Jref = isNum(a.riferimento) ? a.riferimento : o.costo;
      var AD = Math.min(Jref, B29) * AB;
      var K = AD < B31 ? 0 : Math.min(AD, B29);
      var AE = 0;
      if (B38 && I > 0) {
        if (K === 0) AE = I;
        else if (AB < 1) AE = (I - K >= B13) ? Math.min(I, ceilTo(I - K, arrot)) : 0;
        else AE = (I - B29 >= B13) ? Math.min(I, ceilTo(I - B29, arrot)) : 0;
      }
      return {
        isin: a.isin, nome: a.nome, def: a, valore: I, costo: o.costo, qta: o.qta, prezzo: prezzoEur,
        punteggio: a.punteggio, verdetto: a.verdetto, valoreStimatoEur: valoreStimatoEur, margine: margine,
        stato: stato, AW: AW, AC: AC, AX: AX, AB: AB, AD: AD, K: K, AE: AE, F: I - AE, rigaExcel: 10 + i,
        riferimento: Jref, allerte: a.allerte
      };
    });
    var B42 = az.reduce(function (s, r) { return s + r.AE; }, 0);

    // --- speculative: vendita appena proficua
    var spec = specDef.map(function (e, j) {
      var o = datiEtf(e.isin) || { valore: 0, costo: 0, qta: 0, prezzo: null };
      var F = specV[j], U = o.costo;
      var BE = F > 0 ? (F - U) - Math.max(0, F - U) * B14 - PA.commissione - F * PA.spreadEtf : null;
      var AR = (B38 && F > 0 && BE != null && BE > PA.guadagnoMinSpeculative) ? F : 0;
      var BF = null;
      if (F > 0 && isNum(o.prezzo) && o.prezzo > 0 && o.qta > 0) {
        BF = (PA.guadagnoMinSpeculative + PA.commissione + U * (1 - B14)) / ((F / o.prezzo) * (1 - B14 - PA.spreadEtf));
      }
      return { def: e, isin: e.isin, nome: e.nome, F: F, U: U, V: F - U, BE: BE, AR: AR, BF: BF, prezzo: o.prezzo, qta: o.qta, rigaExcel: 17 + j };
    });
    var B43 = spec.reduce(function (s, r) { return s + r.AR; }, 0);

    // --- livello 2 (azioni sopra il tetto)
    var B44 = B38 ? Math.max(0, B22 - B42 - B23) : 0;
    az.forEach(function (r, i) {
      r.AG = r.F > 0 ? (isNum(r.punteggio) ? r.punteggio : 1000) * 1e6 - r.F + r.rigaExcel / 1000 : BIG;
    });
    az.forEach(function (r) {
      r.AH = (B44 <= 0 || r.AG >= BIG) ? 0 : az.filter(function (x) { return x.AG < r.AG; }).length + 1;
    });
    az.forEach(function (r) {
      if (r.AH === 0) { r.AI = 0; return; }
      var prima = az.reduce(function (s, x) { return s + (x.AH > 0 && x.AH < r.AH ? x.F : 0); }, 0);
      var rest = B44 - prima;
      if (rest <= 0) { r.AI = 0; return; }
      var base = Math.min(r.F, Math.max(Math.min(B13, r.F), rest));
      if (r.F - base < B31) r.AI = r.F;
      else r.AI = Math.min(r.F, Math.max(Math.min(B13, r.F), ceilTo(base, arrot)));
    });
    var B45 = az.reduce(function (s, r) { return s + r.AI; }, 0);
    az.forEach(function (r) { r.AJ = Math.max(0, r.AE + r.AI); });
    var B41 = Math.max(0, -B9);
    var B46 = B38 ? Math.max(0, B41 - B42 - B43 - B45) : 0;

    // --- rinforzi azioni
    var B52 = B22 - B42 - B45, B53 = Math.max(0, B23 - B52);
    var B56 = isNum(PA.limiteMensile) ? Math.max(0, PA.limiteMensile - B55) : Math.max(0, B9);
    az.forEach(function (r) {
      var AT = isNum(r.margine) ? r.margine : -9; r.AT = AT;
      r.AL = (B38 && B9 > 0 && r.AJ === 0 && r.AC === 'SI' && isNum(r.margine) && AT >= B32 && r.K - r.valore >= B13) ? r.K - r.valore : 0;
    });
    az.forEach(function (r, i) {
      r.AM = r.AL === 0 ? 0 : az.filter(function (x) { return x.AL > 0 && x.AT > r.AT; }).length +
        az.filter(function (x, j) { return x.AL > 0 && x.AT === r.AT && j < i; }).length + 1;
    });
    az.forEach(function (r) {
      if (r.AM === 0) { r.AN = 0; return; }
      var prima = az.reduce(function (s, x) { return s + (x.AM > 0 && x.AM < r.AM ? x.AL : 0); }, 0);
      var disp = Math.min(B53, Math.max(0, B9), B56) - prima;
      var q = floorTo(Math.max(0, Math.min(r.AL, disp)), arrot);
      r.AN = q >= B13 ? q : 0;
    });
    var B54 = az.reduce(function (s, r) { return s + r.AN; }, 0);
    az.forEach(function (r) {
      r.N = r.AN - r.AJ;
      var paese = (r.isin || '').slice(0, 2);
      var tx = (PA.tassaTransazioni && PA.tassaTransazioni[paese]) || 0;
      r.costoTx = r.AN > 0 ? r.AN * tx : 0;
      r.costoComm = r.N !== 0 ? PA.commissione : 0;
      r.costoSpread = Math.abs(r.N) * PA.spreadAzioni;
      r.costi = r.costoTx + r.costoComm + r.costoSpread;
      var AR = (r.AJ > 0 && r.valore > 0) ? r.AJ - r.AJ * r.costo / r.valore : 0;
      r.plus = AR; r.imposta = Math.max(0, AR) * B14; r.minus = Math.max(0, -AR);
      r.guadagnoLatente = r.valore - r.costo;
    });

    // --- ETF core
    var N = etfDef.length;
    var ETF = etfDef.map(function (e, i) {
      var o = datiEtf(e.isin) || { valore: 0, costo: 0, qta: 0, prezzo: null };
      var s = e.storico || null;
      var price = isNum(o.prezzo) && o.qta > 0 ? o.prezzo : (s ? s.ultimoPrezzo : null);
      return { def: e, isin: e.isin, nome: e.nome, F: etfV[i], U: o.costo, qta: o.qta, prezzo: price, s: s, peso: e.peso, riga: 9 + i, inEsaurimento: !!e.sostituitoDa };
    });
    var isinCore = {};
    ETF.forEach(function (r) { isinCore[r.isin] = true; });
    // obiettivo
    ETF.forEach(function (r) {
      var cont = ETF.reduce(function (s, x) { return s + (x.def.sostituitoDa === r.isin ? x.F : 0); }, 0);
      r.contenuti = cont;
    });
    var B24v = B24 === null ? null : B24;
    if (B24v === null) {
      var Ksum = az.reduce(function (s, r) { return s + r.K; }, 0);
      B24v = Math.max(B16 * B10, B10 - Ksum - B19 - B21);
    }
    ETF.forEach(function (r) {
      if (r.inEsaurimento) {
        var rep = r.def.sostituitoDa;
        if (!isinCore[rep]) r.G = r.F;
        else {
          var sumF = ETF.reduce(function (s, x) { return s + (x.def.sostituitoDa === rep ? x.F : 0); }, 0);
          var Dp = ETF.reduce(function (s, x) { return s + (x.isin === rep ? x.peso : 0); }, 0);
          r.G = sumF > 0 ? r.F * Math.min(1, Dp * B24v / sumF) : 0;
        }
      } else r.G = Math.max(0, r.peso * B24v - r.contenuti);
      r.H = r.G - r.F; r.I = r.G > 0 ? r.H / r.G : 0;
      r.Y = compMese[r.isin] || 0;
      r.X = r.H; // ordini gia' inviati: 0 (le operazioni si registrano subito)
    });

    // stato dei dati e fasce
    function statoDati(r) {
      var s = r.s;
      if (!s) return 'DATI MANCANTI';
      if (s.stato !== 'OK' && s.stato !== 'STORICO BREVE') return s.stato || 'DATI MANCANTI';
      return s.stato;
    }
    var etaPrezzi = null;
    ETF.forEach(function (r) {
      r.O = statoDati(r);
      var s = r.s;
      r.etaStorico = s ? giorniTra(s.ultimaData, oggi) : null;
      r.max12 = s && isNum(s.max12) ? Math.max(s.max12, r.prezzo || 0) : null;
      r.dd = (r.max12 && isNum(r.prezzo)) ? Math.min(0, r.prezzo / r.max12 - 1) : null;
      r.N_ = (r.dd != null && s) ? percentileRibasso(r.dd, s) : null;
      var sg = s && s.soglieRibasso ? s.soglieRibasso : [];
      r.livelli = (r.max12 && sg.length === 3 && sg.every(isNum)) ? sg.map(function (x) { return r.max12 * (1 + x); }) : null;
      var fa = PA.fasce;
      var AH = 0;
      if (r.O === 'OK' && r.dd != null && r.livelli && r.X >= B13) {
        if (r.prezzo <= r.livelli[2]) AH = 3; else if (r.prezzo <= r.livelli[1]) AH = 2; else if (r.prezzo <= r.livelli[0]) AH = 1;
      }
      r.AH = AH;
      if (r.etaStorico != null && r.etaStorico > PA.giorniPrezziVecchi && s) res.avvisi.push('Soglie di ribasso di ' + r.nome + ' calcolate ' + r.etaStorico + ' giorni fa.');
    });
    // modo acquisti
    var B50 = (B38 && B9 >= 0 && (PA.ribilanciamento === 'SEMPRE' || (PA.ribilanciamento === 'SOLO BUFFER NULLO' && B6 === 0))) ? 1 : 0;
    ETF.forEach(function (r) {
      r.AQ = (B50 === 1 && r.F > r.G * (1 + PA.bandaSovrappeso) && r.F - r.G >= B13) ? floorTo(r.F - r.G, arrot) : 0;
    });
    var B51 = ETF.reduce(function (s, r) { return s + r.AQ; }, 0);
    var B59 = !B38 ? 'NESSUNO' : (B9 > 0 ? 'BUFFER' : ((B50 === 1 && B51 > 0) ? 'RIBILANCIAMENTO' : 'NESSUNO'));
    var B57 = (B38 && B9 > 0) ? Math.max(0, Math.min(B9, B56) - B54) : 0;
    var B58 = B57 > 0 ? Math.max(0, Math.min(B57, PA.quotaBase * (Math.max(0, B9) + B55) - B55)) : 0;
    var B60 = B59 === 'BUFFER' ? B57 + (B50 === 1 ? B51 : 0) : (B59 === 'RIBILANCIAMENTO' ? B51 : 0);
    ETF.forEach(function (r) {
      var okDati = r.O === 'OK' || r.O === 'STORICO BREVE';
      r.AG = (!r.inEsaurimento && B38 === 1 && B59 !== 'NESSUNO' && okDati && r.X >= B13) ? 1 : 0;
      var AI = 0;
      if (r.AG && r.AH > 0) {
        var frac = PA.fasce[r.AH - 1].quota;
        var v = frac * (r.X + r.Y) - r.Y;
        if (v <= 0) AI = 0;
        else if (r.Y > 0) AI = v >= B13 ? Math.min(r.X, v) : 0;
        else AI = Math.min(r.X, Math.max(B13, v));
      }
      r.AI = AI;
    });
    ETF.forEach(function (r, i) {
      r.AJ = (r.AG === 1 && r.AH === 0)
        ? ETF.filter(function (x) { return x.AG === 1 && x.AH === 0 && x.I > r.I; }).length +
          ETF.filter(function (x, j) { return x.AG === 1 && x.AH === 0 && x.I === r.I && j < i; }).length + 1
        : 0;
    });
    ETF.forEach(function (r) {
      if (r.AJ === 0) { r.AK = 0; return; }
      var prima = ETF.reduce(function (s, x) { return s + (x.AJ > 0 && x.AJ < r.AJ ? x.X : 0); }, 0);
      var t = Math.max(0, Math.min(r.X, B58 - prima));
      r.AK = t < B13 ? 0 : t;
    });
    ETF.forEach(function (r) {
      r.AL = r.AG === 0 ? 0 : (B59 === 'RIBILANCIAMENTO' ? r.X : (r.AH > 0 ? r.AI : r.AK));
      r.AM = r.AL > 0 ? r.AH * 1000 + (r.AH > 0 ? (r.N_ || 0) : r.I) * 100 + (100 - r.riga) / 10000 : -1;
    });
    ETF.forEach(function (r) { r.AN = r.AM < 0 ? 0 : ETF.filter(function (x) { return x.AM > r.AM; }).length + 1; });
    ETF.forEach(function (r) {
      if (r.AN === 0) { r.AO = 0; return; }
      var prima = ETF.reduce(function (s, x) { return s + (x.AN > 0 && x.AN < r.AN ? x.AL : 0); }, 0);
      r.AO = Math.max(0, Math.min(r.AL, B60 - prima));
      var q = floorTo(r.AO, arrot);
      r.AP = q >= B13 ? q : 0;
    });
    ETF.forEach(function (r) { if (r.AP === undefined) r.AP = 0; r.AR = 0; });

    // --- livello 3: vendite di ETF (buffer negativo)
    var rowsAll = ETF.concat(spec.map(function (s) {
      return { isin: s.isin, nome: s.nome, F: s.F, G: 0, U: s.U, AQ: 0, AR: s.AR, riga: s.rigaExcel, spec: true, ref: s };
    }));
    rowsAll.forEach(function (r) {
      var tol = PA.tolleranzaVendite;
      if (r.spec) r.AS = B46 <= 0 ? 0 : Math.max(0, r.F - r.AR);
      else r.AS = B46 <= 0 ? 0 : Math.max(0, r.F - r.AQ - r.G * (1 - tol));
      r.AT = r.F > 0 ? Math.max(0, (r.F - r.U) / r.F) * B14 : 0;
      r.AU = (r.AS > 0 && (r.AS >= B13 || r.AS >= r.F - 0.005)) ? r.AT * 1e6 - (r.F - r.G) / 1e6 + r.riga / 1e9 : BIG;
    });
    rowsAll.forEach(function (r) { r.AV = r.AU >= BIG ? 0 : rowsAll.filter(function (x) { return x.AU < r.AU; }).length + 1; });
    rowsAll.forEach(function (r) {
      var prima = rowsAll.reduce(function (s, x) { return s + (x.AV > 0 && x.AV < r.AV ? x.AS : 0); }, 0);
      var rest = B46 - prima;
      if (r.AV === 0 || rest <= 0) { r.AW = 0; return; }
      var m = Math.min(r.AS, Math.max(Math.min(B13, r.AS), rest));
      if (m >= r.AS - 0.005) r.AW = r.AS;
      else r.AW = Math.max(Math.min(B13, r.AS), Math.min(r.AS, ceilTo(m, arrot)));
    });
    var B47 = rowsAll.reduce(function (s, r) { return s + r.AW; }, 0);
    var B48 = Math.max(0, B46 - B47);
    rowsAll.forEach(function (r) {
      r.AX = r.AQ + r.AR + r.AW;
      var AY = (r.AX > 0 && r.F > 0) ? r.AX - r.AX * r.U / r.F : 0;
      r.plus = AY; r.imposta = Math.max(0, AY) * B14; r.minus = Math.max(0, -AY);
      r.costoComm = ((r.AP || 0) > 0 || r.AX > 0) ? PA.commissione : 0;
      r.costoSpread = ((r.AP || 0) + r.AX) * PA.spreadEtf;
      r.costi = r.costoComm + r.costoSpread;
      r.importo = (r.AP || 0) - r.AX;
      r.guadagnoLatente = r.F - r.U;
    });

    // --- testo di stato degli ETF
    ETF.forEach(function (r) {
      var f = PA.fasce, nomeFascia = r.AH > 0 ? f[r.AH - 1].nome.toLowerCase() : '';
      var t;
      if (!B38) t = 'BLOCCATO';
      else if (r.AX > 0) t = r.AW > 0 ? 'VENDI: riduzione dell’azionario' : 'VENDI: ribilanciamento (sopra la banda)';
      else if (r.inEsaurimento) t = 'In esaurimento: si tiene, non si compra';
      else if (r.AP > 0) t = r.AH > 0 ? 'COMPRA: sottopeso + ribasso ' + nomeFascia : (B59 === 'RIBILANCIAMENTO' ? 'COMPRA: ribilanciamento' : 'COMPRA: sottopeso');
      else if (r.O !== 'OK' && r.O !== 'STORICO BREVE') t = 'Non si compra: ' + r.O.toLowerCase();
      else if (r.X >= B13) t = r.AH > 0 ? 'Sottopeso + ribasso ' + nomeFascia + ': capitale del mese esaurito' : 'Sottopeso: in attesa';
      else if (r.H <= -B13) t = 'Sovrappeso: non si compra';
      else t = r.H > 0 ? 'In linea (sottopeso sotto l’ordine minimo)' : 'In linea';
      r.segnale = t;
      // prossima soglia
      r.prossima = null;
      if (r.livelli && !r.inEsaurimento) {
        var prox = r.AH === 0 ? r.livelli[0] : (r.AH === 1 ? r.livelli[1] : (r.AH === 2 ? r.livelli[2] : null));
        if (prox != null) r.prossima = { prezzo: prox, variazione: prox / r.prezzo - 1 };
      }
    });
    spec.forEach(function (s) {
      var t;
      if (s.F <= 0) t = 'Non in portafoglio';
      else if (!B38) t = 'BLOCCATO';
      else if (s.AR > 0) t = 'VENDI: proficuo (+' + eur0(s.BE) + ' € netti stimati)';
      else if (s.BF != null) t = 'TIENI: sotto il pareggio (' + fx(s.BF, 2) + ' € per quota)';
      else t = 'TIENI';
      s.segnale = t;
    });
    // testo delle azioni
    az.forEach(function (r) {
      var t;
      if (!B38) t = 'BLOCCATO';
      else if (r.K === 0 && r.AB === 0) t = 'USCITA: verdetto Graham «' + r.verdetto + '»';
      else if (r.K === 0) t = (r.AX < 1 ? 'USCITA: punteggio sceso da ' + fx(r.def.punteggioRiferimento, 0) + ' a ' + fx(r.punteggio, 0) + ', allocazione sotto il minimo' : 'USCITA: allocazione sotto il minimo') + ' (minimo ' + eur0(B31) + ' €)';
      else if (r.AI > 0) t = 'RIDUCI: azioni sopra il tetto del ' + pct0(B17);
      else if (r.AE > 0) t = r.AX < 1 ? 'RIDUCI: punteggio sceso da ' + fx(r.def.punteggioRiferimento, 0) + ' a ' + fx(r.punteggio, 0) : (r.AB < 1 ? 'RIDUCI: verdetto Graham «' + r.verdetto + '»' : 'RIDUCI: sopra il massimo per azienda (' + eur0(B29) + ' €)');
      else if (r.AN > 0) t = r.AX > 1 ? 'AUMENTA: punteggio salito da ' + fx(r.def.punteggioRiferimento, 0) + ' a ' + fx(r.punteggio, 0) + ', margine ' + fx(r.AT * 100, 0) + '%' : 'RINFORZA: margine di sicurezza ' + fx(r.AT * 100, 0) + '%';
      else if (r.AL > 0) t = 'Acquisto possibile, ma manca spazio o capitale';
      else if (r.stato !== 'OK') t = 'MANTIENI (dati Graham ' + r.stato.toLowerCase() + ')';
      else t = 'MANTIENI' + (r.AW != null ? ' (punteggio ' + fx(r.punteggio, 0) + ', riferimento ' + fx(r.def.punteggioRiferimento, 0) + ')' : '');
      r.segnale = t;
      // quando rinforzare
      var cambioR = isNum(r.def.cambioLocale) && r.def.cambioLocale > 0 ? r.def.cambioLocale : null;
      var prezzoRinforzo = (cambioR && isNum(r.def.valoreLocale) && r.AC === 'SI') ? r.def.valoreLocale * (1 - B32) / cambioR : null;
      r.prezzoRinforzo = prezzoRinforzo;
      var quando;
      if (r.K === 0 || r.AJ > 0) quando = 'in uscita: non si rinforza';
      else if (r.AC !== 'SI') quando = 'verdetto o dati: niente rinforzi';
      else if (r.valore >= r.K - B13 + 1e-9) quando = r.valore > r.K ? 'sopra l’allocazione obiettivo: niente rinforzi' : 'già all’allocazione obiettivo';
      else quando = prezzoRinforzo != null ? 'se il prezzo scende sotto ' + fx(prezzoRinforzo, 2) + ' €' : '';
      r.quando = quando;
    });

    // --- riepilogo e operazioni
    var B61 = ETF.reduce(function (s, r) { return s + r.AL; }, 0);
    var B62 = ETF.reduce(function (s, r) { return s + r.AP; }, 0);
    var B63 = Math.min(B60, B61) + B54, B64 = B62 + B54, B65 = Math.max(0, B9 - B64);
    var B66 = B42 + B43 + B45 + B47 + B51;

    var ops = [];
    rowsAll.forEach(function (r) {
      if (r.importo !== 0 && !(r.spec && r.AX === 0 && !(r.AP > 0))) {
        ops.push({
          tipo: r.spec ? 'Speculativo' : 'ETF', nome: r.nome, isin: r.isin, verso: r.importo > 0 ? 'COMPRA' : 'VENDI',
          importo: Math.abs(r.importo), prezzo: r.spec ? r.ref.prezzo : r.prezzo,
          motivo: r.segnale || (r.ref && r.ref.segnale) || '', costi: r.costi, imposta: r.imposta, minus: r.minus, ordine: r.riga
        });
      }
    });
    // le speculative hanno il testo dentro spec[]
    ops.forEach(function (o) { if (o.tipo === 'Speculativo') { var s = spec.filter(function (x) { return x.isin === o.isin; })[0]; if (s) o.motivo = s.segnale; } });
    az.forEach(function (r) {
      if (r.N !== 0) {
        ops.push({ tipo: 'Azione', nome: r.nome, isin: r.isin, verso: r.N > 0 ? 'COMPRA' : 'VENDI', importo: Math.abs(r.N),
          prezzo: r.prezzo, motivo: r.segnale, costi: r.costi, imposta: r.imposta, minus: r.minus, ordine: 100 + r.rigaExcel });
      }
    });
    ops.sort(function (a, b) {
      var sa = a.verso === 'VENDI' ? 0 : 1, sb = b.verso === 'VENDI' ? 0 : 1;
      return sa !== sb ? sa - sb : a.ordine - b.ordine;
    });
    ops.forEach(function (o, i) {
      o.n = i + 1;
      o.quantita = isNum(o.prezzo) && o.prezzo > 0 ? o.importo / o.prezzo : null;
    });

    var sintesi;
    if (!B38) sintesi = 'BLOCCATO: ' + motivoBlocco;
    else if (ops.length > 0) sintesi = 'Operazioni suggerite: ' + ops.length + '. Prima le vendite, poi gli acquisti.';
    else if (B9 > 0) {
      var nElig = ETF.filter(function (r) { return r.AG === 1; }).length;
      var nFasce = ETF.filter(function (r) { return r.AH > 0; }).length;
      if (nElig === 0) sintesi = 'ATTENDI: nessun ETF sotto il suo obiettivo di almeno un ordine minimo. Il capitale resta disponibile.';
      else if (nFasce === 0) sintesi = 'ATTENDI: la quota base del mese (' + eur0(B58) + ' €) non arriva all’ordine minimo e non ci sono ribassi: il capitale si accumula per i mesi dopo.';
      else sintesi = 'ATTENDI: gli importi del mese restano sotto l’ordine minimo. Il capitale resta disponibile.';
    } else if (B9 < 0) sintesi = 'Buffer negativo, ma niente da vendere rispettando le regole: vedi «Non riducibile».';
    else sintesi = 'Buffer nullo: nessuna operazione necessaria.';

    res.quadro = {
      buffer: B6, bufferResiduo: B9, capitaleAutorizzato: B10, valoreAzionario: B5, patrimonio: B11,
      candidato: B63, acquisti: B64, inAttesa: B65, riduzioneRichiesta: B41, vendite: B66, nonRiducibile: B48,
      costi: ops.reduce(function (s, o) { return s + o.costi; }, 0),
      imposte: ops.reduce(function (s, o) { return s + o.imposta; }, 0),
      minus: ops.reduce(function (s, o) { return s + o.minus; }, 0),
      etfCore: B18, spec: B19, azioni: B20, altriNonClassificati: B21,
      obiettivoEtf: B24v, tettoAzioni: B23, azioniDopoVendite: B52, spazioAzioni: B53,
      pesoMax: B29, pesoMedio: B30, pesoMin: B31, ordineMinimo: B13,
      acquistiMese: B55, quotaBase: B58, modo: B59, capitaleEtf: B60, valido: B38 === 1, motivoBlocco: motivoBlocco, sintesi: sintesi,
      etaDati: etaSnap
    };
    res.etf = ETF; res.speculativi = spec; res.azioni = az; res.operazioni = ops;
    if (B21 > 0) res.avvisi.push('Ci sono ' + eur0(B21) + ' € di ETF azionari fuori dal paniere, che l’app non gestisce.');
    return res;
  }

  /* ------------------------------------------------------------ operazioni registrate */
  /* Registra un'operazione eseguita: aggiorna quantita', costo, prezzo e liquidita'. Restituisce nuove posizioni. */
  function applicaOperazione(posizioni, op) {
    var nuove = posizioni.map(function (p) { return Object.assign({}, p); });
    var p = nuove.filter(function (x) { return x.isin === op.isin && x.classe === 'Azionario' && !x.archiviata; })[0];
    var liq = nuove.filter(function (x) { return x.tipo === 'Liquidità'; })[0];
    if (!p) throw new Error('Posizione non trovata');
    var q = op.importo / op.prezzo;
    var comm = num(op.commissione, 0);
    if (op.verso === 'COMPRA') {
      p.qta = num(p.qta, 0) + q; p.costo = num(p.costo, 0) + op.importo;
      if (liq) liq.qta -= (op.importo + comm);
    } else {
      var q0 = num(p.qta, 0);
      var qv = Math.min(q, q0);
      var quota = q0 > 0 ? qv / q0 : 1;
      p.costo = num(p.costo, 0) * (1 - quota); p.qta = q0 - qv;
      if (liq) liq.qta += (op.importo - comm);
      if (p.qta < 1e-6) { p.qta = 0; p.costo = 0; if (p.tipo === 'Azione') p.archiviata = true; }
    }
    p.prezzo = op.prezzo;
    return nuove;
  }

  var API = {
    CLASSI: CLASSI, valorePosizione: valorePosizione, dalleCurva: dalleCurva, calcolaPortafoglio: calcolaPortafoglio,
    calcolaBilanciamento: calcolaBilanciamento, percentileRibasso: percentileRibasso, applicaOperazione: applicaOperazione,
    giorniTra: giorniTra, meseChiave: meseChiave, isNum: isNum, eur0: eur0, fx: fx
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else root.Motore = API;
})(typeof window !== 'undefined' ? window : this);
