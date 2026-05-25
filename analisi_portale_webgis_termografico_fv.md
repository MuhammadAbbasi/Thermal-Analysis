# Analisi per la realizzazione di un portale WebGIS per impianto FV con storico termografico

## 1. Obiettivo del progetto

L'obiettivo è realizzare un portale WebGIS/SITR dedicato alla gestione tecnica e storica di un impianto fotovoltaico, integrando:

- layout completo dell'impianto;
- numero e posizione delle stringhe;
- posizione dei pannelli/moduli FV;
- ITS, cabine o stazioni tecniche;
- quadri di campo, quadri stringa, quadri AC/DC;
- inverter;
- campagne termografiche;
- raster termografici pubblicati tramite WMS/WMTS;
- anomalie termografiche georiferite;
- report, foto e documentazione tecnica;
- storico manutentivo.

Il sistema non deve essere un semplice visualizzatore di WMS, ma un archivio tecnico-geografico dell'impianto, simile a un **digital twin cartografico**.

---

## 2. Concetto generale del portale

La struttura logica del portale può essere rappresentata così:

```text
Impianto FV
 ├── Campo / Sottocampo
 │    ├── Fila
 │    │    ├── Modulo FV
 │    │    └── Stringa
 │    ├── Quadro di campo / quadro stringa
 │    ├── Inverter
 │    └── ITS / cabina / stazione tecnica
 └── Campagne termografiche
      ├── Raster termografico WMS/WMTS
      ├── Anomalie termografiche
      ├── Foto IR/RGB
      ├── Report PDF
      └── Stato manutentivo
```

Ogni anomalia termografica dovrebbe essere collegata al componente tecnico su cui ricade.

Esempio:

```text
Anomalia A-2026-0034
 ↓
Modulo FV01-C03-F12-M08
 ↓
Stringa S05
 ↓
Quadro QS02
 ↓
Inverter INV01
 ↓
ITS01
```

In questo modo il portale permette non solo di visualizzare un hotspot, ma di sapere **a quale componente elettrico-impiantistico è associato**.

---

## 3. Architettura generale consigliata

Architettura consigliata:

```text
Rilievo in campo
   ↓
Elaborazione termografie / ortomosaici
   ↓
QGIS / controllo GIS / georeferenziazione
   ↓
GeoTIFF / COG + layer anomalie
   ↓
PostgreSQL / PostGIS + archivio file
   ↓
GeoServer o QGIS Server
   ↓
WMS / WMTS / WFS
   ↓
Portale WebGIS tipo SITR
```

### Stack tecnologico consigliato

| Componente | Tecnologia consigliata | Funzione |
|---|---|---|
| Desktop GIS | QGIS Desktop | Preparazione dati, georeferenziazione, controllo qualità |
| Database | PostgreSQL + PostGIS | Storico, geometrie, anomalie, componenti impianto |
| Map server | GeoServer o QGIS Server | Pubblicazione WMS, WMTS, WFS |
| Frontend WebGIS | OpenLayers o Leaflet | Mappa web, layer, filtri, interrogazioni |
| Backend | FastAPI, Django o Node.js | API, utenti, documenti, workflow |
| Storage | File system strutturato o S3-compatible | GeoTIFF, foto, report, allegati |
| Basemap | OSM, provider tile o basemap istituzionale | Sfondo cartografico |

Per un portale evoluto e incrementabile, la combinazione più robusta è:

```text
QGIS Desktop + GeoServer + PostgreSQL/PostGIS + OpenLayers + Backend applicativo
```

---

## 4. Dati impiantistici da integrare

### 4.1 Moduli fotovoltaici

Ogni pannello dovrebbe essere gestito come oggetto geografico, idealmente un poligono.

| Campo | Descrizione |
|---|---|
| `id_modulo` | ID univoco modulo |
| `id_impianto` | Impianto di appartenenza |
| `campo` | Campo o sottocampo |
| `fila` | Fila |
| `posizione_fila` | Numero progressivo nella fila |
| `id_stringa` | Stringa collegata |
| `id_inverter` | Inverter associato |
| `id_quadro` | Quadro associato |
| `marca` | Marca modulo |
| `modello` | Modello modulo |
| `potenza_wp` | Potenza nominale |
| `matricola` | Numero seriale, se disponibile |
| `data_installazione` | Data installazione |
| `stato` | Attivo, sostituito, dismesso |
| `geom` | Geometria del modulo |

Scheda tipo nel portale:

```text
Modulo: FV01-C03-F12-M08
Campo: C03
Fila: F12
Stringa: S05
Quadro: QS02
Inverter: INV01
ITS: ITS01
Marca: ...
Modello: ...
Potenza: 550 Wp
Stato: Attivo
Anomalie rilevate: 2
Ultima campagna: 22/05/2026
Ultimo esito: hotspot alta gravità
```

---

### 4.2 Stringhe FV

Ogni stringa deve essere modellata come elemento tecnico e geografico, associato ai moduli che la compongono.

| Campo | Descrizione |
|---|---|
| `id_stringa` | ID stringa |
| `id_impianto` | Impianto |
| `campo` | Campo |
| `id_inverter` | Inverter collegato |
| `id_quadro` | Quadro stringa/campo |
| `n_moduli` | Numero moduli |
| `potenza_totale_kwp` | Potenza stringa |
| `tensione_nominale` | Tensione prevista |
| `corrente_nominale` | Corrente prevista |
| `stato` | Attiva, fuori servizio, modificata |
| `geom` | Linea o poligono della stringa |

Nel portale l'utente dovrebbe poter selezionare una stringa e vedere:

- moduli appartenenti;
- anomalie presenti;
- storico rilievi;
- eventuali interventi;
- dati elettrici, se disponibili;
- inverter e quadro associati.

---

### 4.3 Quadri di campo / quadri stringa / quadri AC-DC

| Campo | Descrizione |
|---|---|
| `id_quadro` | ID quadro |
| `tipo_quadro` | DC, AC, stringa, campo, generale |
| `id_impianto` | Impianto |
| `campo` | Campo |
| `id_inverter` | Inverter servito |
| `n_stringhe_collegate` | Numero stringhe |
| `marca` | Marca |
| `modello` | Modello |
| `matricola` | Matricola |
| `protezione_spd` | Presenza SPD |
| `sezionatore` | Sì/no |
| `stato` | Attivo, guasto, sostituito |
| `documentazione` | Link scheda tecnica |
| `geom` | Punto o poligono |

Il quadro deve essere interrogabile sulla mappa e collegato alle stringhe e all'inverter di riferimento.

---

### 4.4 Inverter

| Campo | Descrizione |
|---|---|
| `id_inverter` | ID inverter |
| `id_impianto` | Impianto |
| `campo` | Campo o sottocampo |
| `marca` | Marca |
| `modello` | Modello |
| `potenza_kw` | Potenza nominale |
| `n_stringhe` | Numero stringhe collegate |
| `id_its` | ITS/cabina/stazione associata |
| `matricola` | Matricola |
| `data_installazione` | Data installazione |
| `stato` | Attivo, guasto, sostituito |
| `geom` | Punto/poligono |

---

### 4.5 ITS / cabine / stazioni tecniche

Nel contesto di questa analisi, per ITS si intende una stazione tecnica, cabina o inverter-transformer station. Se nel progetto il termine ITS ha un significato diverso, il modello dati va adattato alla nomenclatura reale.

| Campo | Descrizione |
|---|---|
| `id_its` | ID ITS |
| `id_impianto` | Impianto |
| `tipo` | Cabina, stazione inverter, trasformazione, controllo |
| `campo_servito` | Campo/sottocampo |
| `n_inverter` | Numero inverter collegati |
| `potenza_kw` | Potenza associata |
| `trasformatore` | Dati trasformatore |
| `quadro_mt_bt` | Riferimento quadri |
| `stato` | Attiva, manutenzione, fuori servizio |
| `documentazione` | Link documenti |
| `geom` | Punto o poligono |

---

## 5. Modello dati aggiornato

Il database dovrebbe prevedere almeno le seguenti tabelle:

```text
impianti
campi_fv
file_fv
moduli_fv
stringhe_fv
quadri_fv
inverter_fv
its_cabine
campagne_termografiche
anomalie_termografiche
interventi_manutentivi
documenti
foto
utenti
```

### 5.1 Tabella `impianti`

```text
id_impianto
nome
localita
potenza_kwp
proprietario
gestore
geom
```

### 5.2 Tabella `campagne_termografiche`

```text
id_campagna
id_impianto
data_rilievo
operatore
strumento
meteo
irraggiamento
temperatura_ambiente
url_wms
nome_layer_wms
url_report
stato_validazione
note
```

### 5.3 Tabella `anomalie_termografiche`

```text
id_anomalia
id_campagna
id_impianto
id_modulo
id_stringa
id_quadro
id_inverter
id_its
tipo_anomalia
gravita
delta_t
stato
foto_termica
foto_rgb
report_pdf
note
geom
```

### 5.4 Tabella `interventi_manutentivi`

```text
id_intervento
id_anomalia
id_componente
tipo_componente
data_intervento
descrizione
esito
operatore
documento
stato_post_intervento
```

---

## 6. Layer cartografici da prevedere

### 6.1 Layer base impianto

| Layer | Geometria | Uso |
|---|---|---|
| Perimetro impianto | Poligono | Inquadramento generale |
| Campi/sottocampi | Poligono | Organizzazione impianto |
| File pannelli | Linea/poligono | Navigazione tecnica |
| Moduli FV | Poligono | Consultazione puntuale |
| Stringhe | Linea/poligono | Connessione elettrica |
| Quadri | Punto/poligono | Componenti elettrici |
| Inverter | Punto/poligono | Conversione energia |
| ITS/cabine | Punto/poligono | Nodi tecnici |
| Viabilità interna | Linea | Accessibilità |
| Recinzioni/cancelli | Linea/punto | Sicurezza e accesso |

### 6.2 Layer termografici

| Layer | Tipo | Uso |
|---|---|---|
| Termografia campagna 1 | Raster WMS/WMTS | Visualizzazione termica |
| Termografia campagna 2 | Raster WMS/WMTS | Storico |
| Termografia multi-data | ImageMosaic/WMS con TIME | Slider temporale |
| Anomalie | Vettore | Interrogazione tecnica |
| Aree critiche | Poligono | Analisi spaziale |
| Interventi | Punto/poligono | Manutenzione |

---

## 7. Funzioni del portale

### 7.1 Consultazione impianto

Il portale deve permettere di cliccare su un componente e aprire una scheda tecnica.

Componenti interrogabili:

- impianto;
- campo;
- fila;
- modulo;
- stringa;
- quadro;
- inverter;
- ITS/cabina;
- anomalia;
- intervento.

---

### 7.2 Ricerca tecnica

Esempi di ricerche da implementare:

```text
Cerca modulo FV01-C03-F12-M08
Cerca stringa S05
Cerca inverter INV01
Cerca quadro QS02
Mostra tutte le anomalie della ITS01
Mostra tutte le stringhe con anomalie critiche
Mostra i moduli sostituiti
Mostra tutte le anomalie aperte del campo C03
```

---

### 7.3 Filtri

Filtri consigliati:

- impianto;
- campo;
- fila;
- stringa;
- quadro;
- inverter;
- ITS;
- data campagna;
- tipo anomalia;
- gravità;
- stato anomalia;
- stato manutentivo;
- componente sostituito/non sostituito;
- presenza report;
- presenza foto termica;
- data ultimo intervento.

---

### 7.4 Funzioni minime MVP

Per il primo rilascio:

- login base;
- mappa WebGIS;
- basemap;
- layer layout impianto;
- moduli/stringhe/quadri/inverter/ITS interrogabili;
- caricamento WMS/WMTS termografia;
- anomalie vettoriali;
- scheda anomalia;
- scheda componente;
- filtro per campagna;
- filtro per gravità anomalia;
- link a foto e report;
- pannello admin minimo.

---

### 7.5 Funzioni avanzate

Per una seconda fase:

- slider temporale;
- confronto tra campagne;
- split map prima/dopo;
- dashboard anomalie;
- storico per modulo/stringa/inverter;
- workflow manutentivo;
- upload guidato di nuove campagne;
- validazione dati prima della pubblicazione;
- esportazione report PDF;
- gestione multi-impianto;
- API per integrazione con software O&M/CMMS.

---

## 8. Flusso operativo aggiornato

Il flusso aggiornato diventa:

```text
1. Raccolta documentazione impianto
   ↓
2. Digitalizzazione layout FV
   ↓
3. Creazione database componenti
   ↓
4. Georeferenziazione moduli, stringhe, quadri, inverter, ITS
   ↓
5. Rilievo termografico in campo
   ↓
6. Elaborazione raster termografico
   ↓
7. Pubblicazione WMS/WMTS
   ↓
8. Creazione anomalie vettoriali
   ↓
9. Collegamento anomalie ai componenti impianto
   ↓
10. Consultazione nel portale
   ↓
11. Aggiornamento storico e manutenzione
```

La priorità progettuale cambia rispetto a un semplice portale termografico:

```text
1. Prima costruire il layout tecnico dell'impianto
2. Poi collegare il rilievo termografico al layout
3. Poi pubblicare WMS/WMTS e anomalie
4. Poi creare storico, dashboard e workflow
```

---

## 9. Procedura per il rilievo in campo

### 9.1 Preparazione prima del rilievo

Prima del rilievo occorre disporre di:

- planimetria impianto;
- layout moduli;
- schema stringhe;
- posizione quadri;
- posizione inverter;
- posizione ITS/cabine;
- perimetro impianto;
- viabilità interna;
- codifica componenti.

### 9.2 Acquisizione termografica

Durante il rilievo vanno raccolti:

- immagini termiche radiometriche;
- immagini RGB, se disponibili;
- coordinate GNSS/RTK o riferimenti georeferenziabili;
- data e ora;
- condizioni meteo;
- irraggiamento;
- temperatura ambiente;
- vento;
- stato operativo impianto;
- operatore;
- strumento utilizzato;
- note di campo.

### 9.3 Output del rilievo

Output attesi:

```text
immagini IR
immagini RGB
metadati campagna
log coordinate
note rilievo
prime evidenze anomalia
```

---

## 10. Elaborazione GIS e pubblicazione WMS/WMTS

### 10.1 Elaborazione dati

Passaggi:

1. organizzazione immagini e metadati;
2. elaborazione ortomosaico termico o tavole termografiche;
3. esportazione GeoTIFF;
4. eventuale conversione in COG;
5. georeferenziazione o controllo in QGIS;
6. creazione layer anomalie;
7. classificazione anomalie;
8. collegamento anomalie ai componenti;
9. creazione report.

### 10.2 Pubblicazione WMS/WMTS

Con GeoServer o QGIS Server:

1. caricamento raster;
2. definizione CRS;
3. definizione bounding box;
4. impostazione stile;
5. pubblicazione WMS;
6. eventuale cache WMTS;
7. pubblicazione WFS/API anomalie;
8. test in QGIS;
9. test nel portale.

### 10.3 Storico temporale

Per molte campagne nel tempo è consigliabile usare:

```text
GeoServer ImageMosaic + dimensione TIME
```

In questo modo il portale richiama lo stesso layer con date diverse:

```text
...&LAYERS=fv_termografie:impianto01_termografie&TIME=2026-05-22
```

---

## 11. Team previsto

Il team indicato è composto da:

```text
1 persona per rilievo
1 persona per elaborazione dato GIS
1 persona per architettura del portale
```

### 11.1 Ruolo rilievo

Responsabilità:

- pianificazione rilievo;
- acquisizione termografie;
- raccolta metadati;
- controllo condizioni operative;
- supporto alla classificazione anomalie;
- validazione tecnica dei risultati.

### 11.2 Ruolo GIS

Responsabilità:

- digitalizzazione layout;
- georeferenziazione;
- costruzione base impianto;
- gestione moduli/stringhe/quadri/inverter/ITS;
- elaborazione GeoTIFF/COG;
- creazione anomalie vettoriali;
- controllo qualità dati;
- preparazione layer per PostGIS/GeoServer.

### 11.3 Ruolo architettura portale

Responsabilità:

- architettura software;
- database;
- configurazione GeoServer/QGIS Server;
- backend;
- frontend WebGIS;
- autenticazione;
- sicurezza;
- deploy;
- manutenzione;
- performance.

Questa è la figura più critica perché concentra molti compiti tecnici. Se non è anche sviluppatore full-stack, serve almeno una figura aggiuntiva.

---

## 12. Impatto dell'integrazione del layout impianto sulle tempistiche

La prima stima per un portale solo termografico era:

```text
MVP operativo: 8-12 settimane
Versione completa: 14-20 settimane
Sistema evoluto: 5-8 mesi
```

Con l'integrazione completa del layout impianto, la stima diventa:

```text
MVP operativo completo: 12-16 settimane
Versione completa: 18-26 settimane
Sistema evoluto multi-impianto: 6-10 mesi
```

Il maggiore impatto riguarda soprattutto:

- digitalizzazione GIS;
- costruzione anagrafica componenti;
- collegamento moduli-stringhe-quadri-inverter-ITS;
- schede componente nel portale;
- ricerca tecnica;
- filtri più avanzati.

---

## 13. Nuova ripartizione per fasi

| Fase | Durata precedente | Durata aggiornata |
|---|---:|---:|
| Analisi requisiti | 1 settimana | 1-2 settimane |
| Base GIS impianto | 1-2 settimane | 3-5 settimane |
| Setup infrastruttura | 1-2 settimane | 1-2 settimane |
| Modello dati impiantistico | Incluso | 1-2 settimane |
| Rilievo pilota | 2-5 giorni | 2-5 giorni |
| Elaborazione termografie | 1-2 settimane | 1-2 settimane |
| Pubblicazione WMS | 3-7 giorni | 3-7 giorni |
| Portale WebGIS MVP | 3-5 settimane | 4-6 settimane |
| Test e validazione | 1 settimana | 1-2 settimane |

---

## 14. Cronoprogramma sintetico aggiornato

```text
Settimana 1
Analisi requisiti, definizione struttura impianto, naming componenti

Settimane 2-3
Raccolta layout, schemi elettrici, planimetrie, dati stringhe, quadri, inverter, ITS

Settimane 4-6
Digitalizzazione GIS: campi, file, moduli, stringhe, quadri, inverter, ITS

Settimane 5-6
Setup PostGIS, GeoServer, archivio raster/documentale

Settimane 7-8
Sviluppo portale WebGIS: mappa, layer impianto, schede componenti

Settimana 9
Rilievo termografico pilota

Settimane 10-11
Elaborazione termografie, GeoTIFF, anomalie, report

Settimana 12
Pubblicazione WMS/WMTS e collegamento anomalie-componenti

Settimane 13-14
Storico campagne, filtri, ricerca per componente

Settimane 15-16
Test, validazione, correzioni, rilascio MVP
```

---

## 15. Fasi progettuali consigliate

### Fase 1 - Gemello digitale base impianto

Obiettivo: creare la struttura GIS dell'impianto.

Include:

- perimetro;
- campi;
- file;
- moduli;
- stringhe;
- quadri;
- inverter;
- ITS/cabine;
- codifica componenti.

Durata stimata:

```text
4-6 settimane
```

---

### Fase 2 - Portale WebGIS tecnico

Obiettivo: consultare layout e componenti.

Include:

- mappa;
- schede componente;
- ricerca;
- filtri;
- layer on/off;
- documenti collegati;
- accesso utenti;
- pannello admin minimo.

Durata stimata:

```text
4-6 settimane
```

---

### Fase 3 - Integrazione termografica

Obiettivo: collegare rilievi termografici e storico.

Include:

- WMS/WMTS termografie;
- anomalie;
- report;
- storico campagne;
- collegamento anomalie-componenti;
- stato manutentivo.

Durata stimata:

```text
4-6 settimane
```

---

## 16. Stima finale aggiornata

### MVP completo

```text
12-16 settimane
```

Include:

- layout impianto;
- componenti principali;
- portale WebGIS;
- prima campagna termografica;
- WMS/WMTS;
- anomalie;
- schede e report.

### Versione avanzata

```text
18-26 settimane
```

Include anche:

- dashboard;
- storico avanzato;
- confronto campagne;
- workflow manutentivo;
- filtri evoluti;
- upload guidato.

### Sistema evoluto multi-impianto

```text
6-10 mesi
```

Include:

- gestione multi-impianto;
- ruoli avanzati;
- API;
- report automatici;
- integrazione con sistemi O&M;
- automazioni;
- validazione dati più strutturata.

---

## 17. Tempistiche per ogni nuova campagna termografica

Una volta realizzato il portale, ogni nuova campagna dovrebbe richiedere:

| Attività | Durata stimata |
|---|---:|
| Rilievo in campo | 1-3 giorni |
| Scarico e ordinamento dati | 0,5 giorni |
| Elaborazione GIS/termografica | 2-5 giorni |
| Creazione anomalie e report | 1-3 giorni |
| Pubblicazione WMS/WMTS | 0,5-1 giorno |
| Aggiornamento portale | 0,5-1 giorno |

Totale ordinario:

```text
5-12 giorni lavorativi
```

Per impianti piccoli e procedura rodata:

```text
3-5 giorni
```

Per impianti grandi o con molte anomalie:

```text
10-15 giorni
```

---

## 18. Criticità principali

| Criticità | Impatto | Mitigazione |
|---|---|---|
| Layout impianto incompleto | Rallenta base GIS e modello dati | Recuperare schemi e validare codifica subito |
| Moduli non georeferenziati | Difficile collegare anomalie e componenti | Digitalizzazione accurata e controllo QGIS |
| Stringhe non mappate | Riduce utilità tecnica del portale | Ricostruire associazioni modulo-stringa |
| WMS esterni non controllati | Rischio instabilità e link rotti | Preferire pubblicazione interna GeoServer |
| Persona portale sovraccarica | Rischio ritardi | Ridurre scope MVP o inserire sviluppatore |
| Raster pesanti | Portale lento | Usare COG, overviews, WMTS/cache |
| Mancanza procedura upload | Ogni campagna resta artigianale | Definire checklist e template obbligatori |

---

## 19. Priorità operative

Ordine consigliato:

1. definire codifica impianto;
2. raccogliere documentazione tecnica;
3. digitalizzare layout;
4. costruire database componenti;
5. predisporre GeoServer/PostGIS;
6. sviluppare portale base;
7. eseguire rilievo pilota;
8. pubblicare WMS/WMTS;
9. collegare anomalie a componenti;
10. testare workflow completo;
11. rilasciare MVP;
12. aggiungere storico avanzato e dashboard.

---

## 20. Raccomandazione finale

Il progetto deve essere impostato come un **portale tecnico-geografico dell'impianto FV**, non come un semplice archivio di termografie.

La strategia migliore è procedere in modo incrementale:

```text
Fase 1 - Gemello digitale base impianto
Fase 2 - Portale WebGIS tecnico
Fase 3 - Integrazione termografica
Fase 4 - Storico avanzato e manutenzione
Fase 5 - Multi-impianto e automazioni
```

Stima finale consigliata da presentare:

```text
MVP completo: 12-16 settimane
Versione avanzata: 18-26 settimane
Sistema evoluto multi-impianto: 6-10 mesi
```

Questa impostazione consente di trasformare il portale in uno strumento operativo per:

- consultazione tecnica;
- diagnostica termografica;
- manutenzione;
- tracciamento anomalie;
- gestione storica;
- supporto alle decisioni sull'impianto FV.
