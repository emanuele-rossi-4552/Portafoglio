# Pendolo Portafoglio

App per telefono con le stesse regole di Portafoglio.xlsx e Bilanciamento.xlsx (pendolo, curva di allocazione, freno, tetto sulla cassa, fasce di ribasso degli ETF, Graham, limiti per azienda). Non legge nessun file Excel.

- **L'app** (`index.html`) gira sul telefono e si installa come app dalla schermata Home. Quantità, costi e operazioni restano **solo sul telefono**.
- **I dati di mercato** li scarica `scripts/aggiorna_dati.py` (FRED, Yahoo Finance, multpl, yfinance) con le stesse regole degli script. Lo fa GitHub, da solo ogni sera nei giorni di borsa e a richiesta dal pulsante **Aggiorna**, e salva il risultato in `dati/dati.json`.
- **I parametri** (curva, fasce, ETF del paniere, azioni, soglie Graham) stanno in `config.json`.

## Installazione (una volta, circa 10 minuti)

1. Su github.com crea un repository **pubblico** (es. `pendolo`). Pubblico serve a GitHub Pages gratuito; nel repository non ci sono quantità né importi, solo l'elenco degli strumenti e le regole.

2. Carica **tutto il contenuto di questa cartella** nel repository (Add file › Upload files, trascina i file e le cartelle, anche `.github`). **Non caricare `posizioni_iniziali.json`**: è il tuo portafoglio e resta sul telefono (il `.gitignore` lo esclude se usi git).

3. **Settings › Pages**: Source = *Deploy from a branch*, Branch = `main`, cartella `/ (root)`. Dopo un minuto l'app è su `https://UTENTE.github.io/pendolo/`.

4. **Settings › Actions › General › Workflow permissions**: *Read and write permissions*.

5. Scheda **Actions › Aggiorna dati › Run workflow** (lascia vuoto il campo): è il primo scarico vero. Ci mette alcuni minuti. Guarda il log: se una fonte non risponde lo dice.

6. Sul telefono apri l'indirizzo dell'app e aggiungila alla Home (iPhone: Condividi › Aggiungi a Home; Android: menu › Installa app).

7. Nell'app: **Importa il portafoglio** e scegli `posizioni_iniziali.json` (copialo sul telefono, o incollane il contenuto).

### Pulsante Aggiorna che scarica «adesso» (facoltativo)

Senza questo passaggio il pulsante legge i dati che GitHub ha già scaricato (ogni sera). Per far partire lo scarico dal telefono:

1. GitHub › Settings › Developer settings › **Fine-grained personal access tokens** › Generate.
2. *Repository access*: solo il repository `pendolo`. *Permissions › Repository permissions*: **Actions = Read and write**. Nient'altro.
3. Nell'app: Dati › **Collegamento a GitHub** › scrivi `utente/pendolo` e incolla il token › Prova › Salva.

Il token resta nel telefono. Con quel token si possono solo far partire e leggere le Actions di quel repository.

## Uso

- **Oggi**: cosa fare ora, il pendolo, l'allocazione.
- **Azionario**: ETF a scaglioni di ribasso, singole azioni, prova di un ribasso.
- Dopo aver eseguito un ordine nel tuo conto, tocca **Registra**: aggiorna quantità, costo di carico e liquidità e conta nei limiti del mese.
- **Dati › Backup**: salva ogni tanto il backup (nessuna sincronizzazione fra dispositivi). Lo stesso file serve a ripristinare o a passare a un altro telefono.

## Cosa fa l'aggiornamento

| Sezione | Fonti | Come l'app la usa |
|---|---|---|
| pendolo | FRED (13 serie), Yahoo `^GSPC`, multpl (CAPE), FRED DGS10 e CPIAUCSL | punteggio 0–100, riferimento, ottimismo nei prezzi |
| mercato | Yahoo (EUNL.DE, poi SWDA.MI, EUNL.F, IWDA.AS) | media mobile a 10 mesi e freno |
| prezzi | Yahoo (ticker in `config.json` o ricerca per ISIN) | prezzo di ETF e azioni, convertito in euro |
| etf | Yahoo, 22 anni, con pulizia dei prezzi sbagliati e verifica del ticker sul prezzo | massimo a 12 mesi, ribasso, soglie delle fasce |
| graham | yfinance e FRED (DAAA) | punteggio, valore intrinseco, margine, allerte (ogni 6 giorni) |

Se una fonte non risponde la sezione resta quella dell'ultima volta e la scheda **Dati** lo mostra; se i dati di punteggio, freno o ETF hanno più di 35 giorni le regole si bloccano, come nel foglio.

L'oro (prezzo manuale) e le obbligazioni non si scaricano: il prezzo lo scrivi tu (Posizioni › Modifica prezzi).

## Modificare strumenti e parametri

Tutto in `config.json` (modificabile direttamente su GitHub): ticker, ISIN, TER, pesi del paniere, soglie Graham, curva. Un'azione nuova va aggiunta in `bilanciamento.azioni` e in `strumenti` di `config.json`, e poi come posizione nell'app (oggi il telefono non crea posizioni nuove: si importano da file).

## Prove

- `python scripts/test_graham.py Bilanciamento.xlsx` confronta il punteggio Graham di Python con quello di Excel (file ricalcolato).
- `python scripts/test_offline.py` prova tutto lo script con dati simulati, senza rete.
- `python build.py` ricostruisce `index.html` e `sw.js` da `src/`.

## Limiti da sapere

- Yahoo non è un servizio ufficiale e a volte limita le richieste dagli indirizzi dei server di GitHub: se succede, la sezione resta ferma e compare nell'elenco degli avvisi. FRED e Yahoo non sono stati interrogati dal computer in cui questo codice è stato scritto: la prima esecuzione su GitHub è la vera prova.
- GitHub può sospendere le esecuzioni programmate dopo 60 giorni senza attività nel repository: se succede, riattivale dalla scheda Actions.
