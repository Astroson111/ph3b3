# Native review — Italian (`it`), Polish (`pl`) & Russian (`ru`) portal UI

These portal-chrome strings were **drafted offline by Claude Code** (hand-translated,
no external translation service — the local-only rule), then given a **first
linguistic review pass** (part-of-speech parallelism on slider endpoints,
de-calquing, "machine"→"device", naturalness on the disclaimer). This sheet reflects
the **current** drafts and is open for a **native final polish** on tone and the
longer strings before a public demo. Italian is the most confident of the three.
128 keys each, 1:1 with `en.json`.

## How to review
- Put your fix in the **Correction** column *only where the draft is wrong or
  unnatural*. Leave it blank if the draft is fine — blank = "keep as drafted".
- 🚩 marks strings the drafter was least sure about (idiomatic, long, or softened).
  Please prioritize these; the rest are standard UI labels.
- **Do NOT translate these — keep them verbatim:** `Ph3b3`, `Phoebe`, `Alba`,
  `Argus`, `Morpheus`, `Ariadne`, `WireGuard`, `ATS`, `QR`, `UTC`, `PNG`,
  `img2img`, file extensions (`.txt` `.docx` `.pdf`), URLs, and the ATS-board names
  (`Greenhouse` `Lever` `Workday` `LinkedIn` `Indeed`). Karaoke → `Karaoke` (it/pl) /
  `Караоке` (ru); RNG → `RNG` (it/pl) / `ГСЧ` (ru).
- **Preserve the markup exactly** — only the words change: HTML tags
  (`<b>…</b>`, `<strong>…</strong>`), entities (`&amp;`, `&#8645;`, `&ensp;`,
  `&#8595;`, `&#10022;`), emoji, and the trailing ellipsis `…`.
- Drafts live in `static/locales/{it,pl,ru}.json`. Corrections from this sheet
  drop straight in (same keys, same order).

---

## Italian (`it`)

| Key | English | Draft | 🚩 | Correction (edit here) |
|-----|---------|-------|----|------------------------|
| `tab.status` | `Status` | `Stato` |  | |
| `tab.chat` | `Chat` | `Chat` |  | |
| `tab.karaoke` | `Karaoke` | `Karaoke` |  | |
| `tab.argus` | `Argus` | `Argus` |  | |
| `tab.morpheus` | `Morpheus` | `Morpheus` |  | |
| `tab.ariadne` | `Ariadne` | `Ariadne` |  | |
| `status.health` | `Health` | `Salute` |  | |
| `status.runtime` | `Runtime` | `Runtime` |  | |
| `status.langvoice` | `Language & Voice` | `Lingua e voce` |  | |
| `status.language` | `Language` | `Lingua` |  | |
| `status.voice` | `Voice` | `Voce` |  | |
| `status.tunnel` | `Remote Tunnel (WireGuard)` | `Tunnel remoto (WireGuard)` |  | |
| `status.checking` | `checking…` | `verifica…` |  | |
| `status.tunnel.down` | `Tunnel is <strong>down</strong> — zero exposure at home` | `Il tunnel è <strong>inattivo</strong> — nessuna esposizione a casa` |  | |
| `status.tunnel.enable` | `Enable` | `Attiva` |  | |
| `voice.note.installed` | `Voice model installed.` | `Modello vocale installato.` |  | |
| `voice.tier.strong` | `strong` | `forte` |  | |
| `voice.tier.functional` | `functional — small local models vary in fluency by language` | `funzionale — i piccoli modelli locali variano in fluidità a seconda della lingua` | 🚩 | |
| `voice.offer.prefix` | `Also switch voice to` | `Cambia anche la voce in` |  | |
| `voice.offer.yes` | `Yes` | `Sì` |  | |
| `voice.offer.keep` | `Keep current` | `Mantieni attuale` |  | |
| `chat.placeholder` | `Message Ph3b3…` | `Scrivi a Ph3b3…` |  | |
| `chat.send` | `Send` | `Invia` |  | |
| `util.title` | `Utilities` | `Utilità` |  | |
| `util.timer` | `Timer` | `Timer` |  | |
| `util.calc` | `Calculator` | `Calcolatrice` |  | |
| `util.converter` | `Converter` | `Convertitore` |  | |
| `util.scratchpad` | `Scratchpad` | `Blocco note` |  | |
| `util.qr` | `QR code` | `Codice QR` |  | |
| `util.dice` | `Dice & RNG` | `Dadi e RNG` |  | |
| `util.clock` | `World clock` | `Orologio mondiale` |  | |
| `common.loading` | `Loading…` | `Caricamento…` |  | |
| `chat.conversation` | `Conversation` | `Conversazione` |  | |
| `chat.speaking` | `Alba speaking…` | `Alba sta parlando…` |  | |
| `chat.mic` | `Hold to speak` | `Tieni premuto per parlare` |  | |
| `util.timer.countdown` | `Countdown` | `Conto alla rovescia` |  | |
| `util.timer.stopwatch` | `Stopwatch` | `Cronometro` |  | |
| `util.timer.ready` | `READY` | `PRONTO` |  | |
| `util.timer.start` | `Start` | `Avvia` |  | |
| `util.timer.reset` | `Reset` | `Reimposta` |  | |
| `util.conv.length` | `Length` | `Lunghezza` |  | |
| `util.conv.weight` | `Weight` | `Peso` |  | |
| `util.conv.temp` | `Temperature` | `Temperatura` |  | |
| `util.conv.data` | `Data size` | `Dimensione dati` |  | |
| `util.conv.volume` | `Volume` | `Volume` |  | |
| `util.conv.swap` | `&#8645; Swap units` | `&#8645; Inverti unità` |  | |
| `util.scratch.ph` | `Sticky note — saved to this device only, never synced…` | `Nota adesiva — salvata solo su questo dispositivo, mai sincronizzata…` | 🚩 | |
| `util.scratch.clear` | `Clear` | `Cancella` |  | |
| `util.qr.ph` | `Text or URL…` | `Testo o URL…` |  | |
| `util.qr.hint` | `Type above to generate a code.` | `Digita sopra per generare un codice.` |  | |
| `util.qr.dl` | `Download PNG` | `Scarica PNG` |  | |
| `util.dice.sub` | `crypto-grade randomness` | `casualità di livello crittografico` | 🚩 | |
| `util.dice.coin` | `Coin` | `Moneta` |  | |
| `util.dice.roll` | `Roll` | `Lancia` |  | |
| `util.clock.add` | `Add` | `Aggiungi` |  | |
| `util.clock.note` | `Local &amp; UTC always shown · up to 3 added zones` | `Locale &amp; UTC sempre mostrati · fino a 3 fusi aggiunti` |  | |
| `karaoke.title` | `KARAOKE` | `KARAOKE` |  | |
| `karaoke.tagline` | `she's a world karaoke machine` | `è una macchina da karaoke mondiale` | 🚩 | |
| `karaoke.discover` | `Discover` | `Scopri` | 🚩 | |
| `karaoke.surprise` | `&#10022;&ensp;Surprise me` | `&#10022;&ensp;Sorprendimi` |  | |
| `karaoke.search.ph` | `mood, genre or title…` | `umore, genere o titolo…` |  | |
| `karaoke.search` | `Search` | `Cerca` |  | |
| `karaoke.disc.hint` | `Tap 'Surprise me' to begin.` | `Tocca 'Sorprendimi' per iniziare.` |  | |
| `karaoke.prep` | `Prep` | `Prepara` |  | |
| `karaoke.drop` | `🎵&ensp;Drop a track here · or Browse` | `🎵&ensp;Trascina un brano qui · o Sfoglia` |  | |
| `karaoke.convert` | `Convert + Prep` | `Converti + Prepara` |  | |
| `karaoke.library` | `Library` | `Libreria` |  | |
| `morpheus.mode.gen` | `✦ Generate` | `✦ Genera` |  | |
| `morpheus.mode.edit` | `✎ Edit` | `✎ Modifica` |  | |
| `morpheus.generate` | `Generate` | `Genera` |  | |
| `morpheus.modelbl` | `Mode` | `Modalità` |  | |
| `morpheus.engine` | `Engine` | `Motore` |  | |
| `morpheus.animating` | `Animating a still` | `Animazione di un fermo immagine` | 🚩 | |
| `morpheus.prompt.ph` | `Describe the image…` | `Descrivi l'immagine…` |  | |
| `morpheus.negative.ph` | `Negative — things to avoid (optional)` | `Negativo — cose da evitare (opzionale)` |  | |
| `morpheus.advanced` | `Advanced` | `Avanzate` |  | |
| `morpheus.steps` | `Steps` | `Passi` |  | |
| `morpheus.width` | `Width` | `Larghezza` |  | |
| `morpheus.height` | `Height` | `Altezza` |  | |
| `morpheus.seed` | `Seed (−1 = random)` | `Seed (−1 = casuale)` |  | |
| `morpheus.genbtn` | `✦ Generate` | `✦ Genera` |  | |
| `morpheus.generation` | `Generation` | `Generazione` |  | |
| `morpheus.cancel` | `Cancel` | `Annulla` |  | |
| `morpheus.output` | `Output` | `Output` | 🚩 | |
| `morpheus.output.empty` | `Nothing yet — hit Generate.` | `Ancora niente — premi Genera.` |  | |
| `morpheus.download` | `&#8595; Download` | `&#8595; Scarica` |  | |
| `morpheus.gallery` | `Gallery` | `Galleria` |  | |
| `morpheus.refresh` | `Refresh` | `Aggiorna` |  | |
| `morpheus.delall` | `Delete All` | `Elimina tutto` |  | |
| `morpheus.edit.title` | `Edit — img2img` | `Modifica — img2img` |  | |
| `morpheus.edit.clipnote` | `Clip editing isn't supported yet — Edit works on stills only. Pick an image, or drop one below.` | `La modifica delle clip non è ancora supportata — Modifica funziona solo su immagini fisse. Scegli un'immagine o trascinane una qui sotto.` | 🚩 | |
| `morpheus.edit.drop` | `🖼️&ensp;Drop an image · or Browse` | `🖼️&ensp;Trascina un'immagine · o Sfoglia` |  | |
| `morpheus.edit.prompt.ph` | `Describe the edit…` | `Descrivi la modifica…` |  | |
| `morpheus.strength` | `Strength` | `Intensità` |  | |
| `morpheus.strength.min` | `touch-up` | `ritocco` | 🚩 | |
| `morpheus.strength.max` | `transform` | `trasformazione` | 🚩 | |
| `morpheus.edit.run` | `✎ Edit image` | `✎ Modifica immagine` |  | |
| `morpheus.edit.job` | `Edit job` | `Lavoro di modifica` |  | |
| `morpheus.edit.ba` | `Before / After` | `Prima / Dopo` |  | |
| `morpheus.edit.empty` | `Upload an image and hit Edit.` | `Carica un'immagine e premi Modifica.` |  | |
| `morpheus.before` | `Before` | `Prima` |  | |
| `morpheus.after` | `After` | `Dopo` |  | |
| `argus.fleet` | `Fleet` | `Flotta` |  | |
| `argus.captures` | `Captures` | `Acquisizioni` | 🚩 | |
| `argus.chats` | `Chats` | `Chat` |  | |
| `argus.filter.alldevices` | `all devices` | `tutti i dispositivi` |  | |
| `argus.filter.alltypes` | `all types` | `tutti i tipi` |  | |
| `argus.filter.audio` | `audio` | `audio` |  | |
| `argus.filter.images` | `images` | `immagini` |  | |
| `argus.state.healthy` | `HEALTHY` | `SANO` |  | |
| `argus.state.sick` | `SICK` | `MALATO` | 🚩 | |
| `argus.state.silent` | `SILENT` | `SILENZIOSO` | 🚩 | |
| `argus.empty.devices` | `No devices known yet.` | `Nessun dispositivo ancora noto.` |  | |
| `ariadne.title` | `Ariadne — résumé ATS` | `Ariadne — CV ATS` |  | |
| `ariadne.note` | `Aligns your <b>truthful</b> experience to ATS vocabulary — it <b>never invents qualifications</b>. Missing keywords you genuinely evidence get surfaced; ones you don't are flagged for you to earn, never added. Your résumé is analyzed <b>locally and never leaves this machine</b> — the only outbound call is fetching a job-post URL you paste.` | `Allinea la tua esperienza <b>veritiera</b> al vocabolario ATS — <b>non inventa mai qualifiche</b>. Le parole chiave mancanti che dimostri realmente vengono evidenziate; quelle che non hai sono segnalate affinché tu le guadagni, mai aggiunte. Il tuo CV è analizzato <b>localmente e non lascia mai questo dispositivo</b> — l'unica chiamata in uscita è il recupero dell'URL di un annuncio che incolli.` | 🚩 | |
| `ariadne.yourresume` | `Your résumé` | `Il tuo CV` |  | |
| `ariadne.resume.ph` | `Paste your résumé text…` | `Incolla il testo del tuo CV…` |  | |
| `ariadne.upload` | `📄&ensp;…or upload .txt / .docx / .pdf` | `📄&ensp;…o carica .txt / .docx / .pdf` |  | |
| `ariadne.jd` | `Job description` | `Descrizione del lavoro` |  | |
| `ariadne.jd.opt` | `— optional, enables the keyword gap` | `— opzionale, abilita l'analisi delle parole chiave` | 🚩 | |
| `ariadne.jd.ph` | `Paste the job description…` | `Incolla la descrizione del lavoro…` |  | |
| `ariadne.or` | `— or —` | `— o —` |  | |
| `ariadne.url.ph` | `https://…  (Greenhouse / Lever / Workday / career page)` | `https://…  (Greenhouse / Lever / Workday / pagina carriere)` |  | |
| `ariadne.hint` | `LinkedIn &amp; Indeed are login-walled — paste their text instead.` | `LinkedIn &amp; Indeed richiedono il login — incolla invece il loro testo.` | 🚩 | |
| `ariadne.analyze` | `Analyze` | `Analizza` |  | |
| `ariadne.build` | `Build ATS résumé` | `Crea CV ATS` |  | |
| `ariadne.result` | `Result` | `Risultato` |  | |
| `ariadne.download` | `⬇&ensp;Download ATS .docx` | `⬇&ensp;Scarica ATS .docx` |  | |

---

## Polish (`pl`)

| Key | English | Draft | 🚩 | Correction (edit here) |
|-----|---------|-------|----|------------------------|
| `tab.status` | `Status` | `Status` |  | |
| `tab.chat` | `Chat` | `Czat` |  | |
| `tab.karaoke` | `Karaoke` | `Karaoke` |  | |
| `tab.argus` | `Argus` | `Argus` |  | |
| `tab.morpheus` | `Morpheus` | `Morpheus` |  | |
| `tab.ariadne` | `Ariadne` | `Ariadne` |  | |
| `status.health` | `Health` | `Kondycja` |  | |
| `status.runtime` | `Runtime` | `Środowisko` |  | |
| `status.langvoice` | `Language & Voice` | `Język i głos` |  | |
| `status.language` | `Language` | `Język` |  | |
| `status.voice` | `Voice` | `Głos` |  | |
| `status.tunnel` | `Remote Tunnel (WireGuard)` | `Zdalny tunel (WireGuard)` |  | |
| `status.checking` | `checking…` | `sprawdzanie…` |  | |
| `status.tunnel.down` | `Tunnel is <strong>down</strong> — zero exposure at home` | `Tunel jest <strong>wyłączony</strong> — zero narażenia w domu` |  | |
| `status.tunnel.enable` | `Enable` | `Włącz` |  | |
| `voice.note.installed` | `Voice model installed.` | `Model głosu zainstalowany.` |  | |
| `voice.tier.strong` | `strong` | `silny` |  | |
| `voice.tier.functional` | `functional — small local models vary in fluency by language` | `funkcjonalny — małe modele lokalne różnią się płynnością w zależności od języka` | 🚩 | |
| `voice.offer.prefix` | `Also switch voice to` | `Przełącz też głos na` |  | |
| `voice.offer.yes` | `Yes` | `Tak` |  | |
| `voice.offer.keep` | `Keep current` | `Zachowaj obecny` |  | |
| `chat.placeholder` | `Message Ph3b3…` | `Napisz do Ph3b3…` |  | |
| `chat.send` | `Send` | `Wyślij` |  | |
| `util.title` | `Utilities` | `Narzędzia` |  | |
| `util.timer` | `Timer` | `Minutnik` |  | |
| `util.calc` | `Calculator` | `Kalkulator` |  | |
| `util.converter` | `Converter` | `Konwerter` |  | |
| `util.scratchpad` | `Scratchpad` | `Notatnik` |  | |
| `util.qr` | `QR code` | `Kod QR` |  | |
| `util.dice` | `Dice & RNG` | `Kości i RNG` |  | |
| `util.clock` | `World clock` | `Zegar światowy` |  | |
| `common.loading` | `Loading…` | `Ładowanie…` |  | |
| `chat.conversation` | `Conversation` | `Rozmowa` |  | |
| `chat.speaking` | `Alba speaking…` | `Alba mówi…` |  | |
| `chat.mic` | `Hold to speak` | `Przytrzymaj, aby mówić` |  | |
| `util.timer.countdown` | `Countdown` | `Odliczanie` |  | |
| `util.timer.stopwatch` | `Stopwatch` | `Stoper` |  | |
| `util.timer.ready` | `READY` | `GOTOWE` |  | |
| `util.timer.start` | `Start` | `Start` |  | |
| `util.timer.reset` | `Reset` | `Resetuj` |  | |
| `util.conv.length` | `Length` | `Długość` |  | |
| `util.conv.weight` | `Weight` | `Waga` |  | |
| `util.conv.temp` | `Temperature` | `Temperatura` |  | |
| `util.conv.data` | `Data size` | `Rozmiar danych` |  | |
| `util.conv.volume` | `Volume` | `Objętość` |  | |
| `util.conv.swap` | `&#8645; Swap units` | `&#8645; Zamień jednostki` |  | |
| `util.scratch.ph` | `Sticky note — saved to this device only, never synced…` | `Karteczka — zapisana tylko na tym urządzeniu, nigdy nie synchronizowana…` | 🚩 | |
| `util.scratch.clear` | `Clear` | `Wyczyść` |  | |
| `util.qr.ph` | `Text or URL…` | `Tekst lub URL…` |  | |
| `util.qr.hint` | `Type above to generate a code.` | `Wpisz powyżej, aby wygenerować kod.` |  | |
| `util.qr.dl` | `Download PNG` | `Pobierz PNG` |  | |
| `util.dice.sub` | `crypto-grade randomness` | `losowość klasy kryptograficznej` | 🚩 | |
| `util.dice.coin` | `Coin` | `Moneta` |  | |
| `util.dice.roll` | `Roll` | `Rzuć` |  | |
| `util.clock.add` | `Add` | `Dodaj` |  | |
| `util.clock.note` | `Local &amp; UTC always shown · up to 3 added zones` | `Lokalny &amp; UTC zawsze widoczne · do 3 dodanych stref` |  | |
| `karaoke.title` | `KARAOKE` | `KARAOKE` |  | |
| `karaoke.tagline` | `she's a world karaoke machine` | `to światowej klasy maszyna do karaoke` | 🚩 | |
| `karaoke.discover` | `Discover` | `Odkrywaj` | 🚩 | |
| `karaoke.surprise` | `&#10022;&ensp;Surprise me` | `&#10022;&ensp;Zaskocz mnie` |  | |
| `karaoke.search.ph` | `mood, genre or title…` | `nastrój, gatunek lub tytuł…` |  | |
| `karaoke.search` | `Search` | `Szukaj` |  | |
| `karaoke.disc.hint` | `Tap 'Surprise me' to begin.` | `Dotknij 'Zaskocz mnie', aby zacząć.` |  | |
| `karaoke.prep` | `Prep` | `Przygotuj` |  | |
| `karaoke.drop` | `🎵&ensp;Drop a track here · or Browse` | `🎵&ensp;Upuść utwór tutaj · lub Przeglądaj` |  | |
| `karaoke.convert` | `Convert + Prep` | `Konwertuj + Przygotuj` |  | |
| `karaoke.library` | `Library` | `Biblioteka` |  | |
| `morpheus.mode.gen` | `✦ Generate` | `✦ Generuj` |  | |
| `morpheus.mode.edit` | `✎ Edit` | `✎ Edytuj` |  | |
| `morpheus.generate` | `Generate` | `Generuj` |  | |
| `morpheus.modelbl` | `Mode` | `Tryb` |  | |
| `morpheus.engine` | `Engine` | `Silnik` |  | |
| `morpheus.animating` | `Animating a still` | `Animowanie stopklatki` | 🚩 | |
| `morpheus.prompt.ph` | `Describe the image…` | `Opisz obraz…` |  | |
| `morpheus.negative.ph` | `Negative — things to avoid (optional)` | `Negatyw — czego unikać (opcjonalnie)` |  | |
| `morpheus.advanced` | `Advanced` | `Zaawansowane` |  | |
| `morpheus.steps` | `Steps` | `Kroki` |  | |
| `morpheus.width` | `Width` | `Szerokość` |  | |
| `morpheus.height` | `Height` | `Wysokość` |  | |
| `morpheus.seed` | `Seed (−1 = random)` | `Seed (−1 = losowy)` |  | |
| `morpheus.genbtn` | `✦ Generate` | `✦ Generuj` |  | |
| `morpheus.generation` | `Generation` | `Generowanie` |  | |
| `morpheus.cancel` | `Cancel` | `Anuluj` |  | |
| `morpheus.output` | `Output` | `Wynik` | 🚩 | |
| `morpheus.output.empty` | `Nothing yet — hit Generate.` | `Jeszcze nic — naciśnij Generuj.` |  | |
| `morpheus.download` | `&#8595; Download` | `&#8595; Pobierz` |  | |
| `morpheus.gallery` | `Gallery` | `Galeria` |  | |
| `morpheus.refresh` | `Refresh` | `Odśwież` |  | |
| `morpheus.delall` | `Delete All` | `Usuń wszystko` |  | |
| `morpheus.edit.title` | `Edit — img2img` | `Edycja — img2img` |  | |
| `morpheus.edit.clipnote` | `Clip editing isn't supported yet — Edit works on stills only. Pick an image, or drop one below.` | `Edycja klipów nie jest jeszcze obsługiwana — Edycja działa tylko na nieruchomych obrazach. Wybierz obraz lub upuść go poniżej.` | 🚩 | |
| `morpheus.edit.drop` | `🖼️&ensp;Drop an image · or Browse` | `🖼️&ensp;Upuść obraz · lub Przeglądaj` |  | |
| `morpheus.edit.prompt.ph` | `Describe the edit…` | `Opisz edycję…` |  | |
| `morpheus.strength` | `Strength` | `Siła` |  | |
| `morpheus.strength.min` | `touch-up` | `retusz` | 🚩 | |
| `morpheus.strength.max` | `transform` | `przekształcenie` | 🚩 | |
| `morpheus.edit.run` | `✎ Edit image` | `✎ Edytuj obraz` |  | |
| `morpheus.edit.job` | `Edit job` | `Zadanie edycji` |  | |
| `morpheus.edit.ba` | `Before / After` | `Przed / Po` |  | |
| `morpheus.edit.empty` | `Upload an image and hit Edit.` | `Prześlij obraz i naciśnij Edytuj.` |  | |
| `morpheus.before` | `Before` | `Przed` |  | |
| `morpheus.after` | `After` | `Po` |  | |
| `argus.fleet` | `Fleet` | `Flota` |  | |
| `argus.captures` | `Captures` | `Przechwycenia` | 🚩 | |
| `argus.chats` | `Chats` | `Czaty` |  | |
| `argus.filter.alldevices` | `all devices` | `wszystkie urządzenia` |  | |
| `argus.filter.alltypes` | `all types` | `wszystkie typy` |  | |
| `argus.filter.audio` | `audio` | `audio` |  | |
| `argus.filter.images` | `images` | `obrazy` |  | |
| `argus.state.healthy` | `HEALTHY` | `ZDROWY` |  | |
| `argus.state.sick` | `SICK` | `CHORY` | 🚩 | |
| `argus.state.silent` | `SILENT` | `CICHY` | 🚩 | |
| `argus.empty.devices` | `No devices known yet.` | `Brak znanych urządzeń.` |  | |
| `ariadne.title` | `Ariadne — résumé ATS` | `Ariadne — CV ATS` |  | |
| `ariadne.note` | `Aligns your <b>truthful</b> experience to ATS vocabulary — it <b>never invents qualifications</b>. Missing keywords you genuinely evidence get surfaced; ones you don't are flagged for you to earn, never added. Your résumé is analyzed <b>locally and never leaves this machine</b> — the only outbound call is fetching a job-post URL you paste.` | `Dopasowuje Twoje <b>prawdziwe</b> doświadczenie do słownictwa ATS — <b>nigdy nie wymyśla kwalifikacji</b>. Brakujące słowa kluczowe, które faktycznie potwierdzasz, są wyróżniane; te, których nie masz, są oznaczane, abyś je zdobył, nigdy nie dodawane. Twoje CV jest analizowane <b>lokalnie i nigdy nie opuszcza tego urządzenia</b> — jedynym połączeniem wychodzącym jest pobranie adresu URL ogłoszenia, który wkleisz.` | 🚩 | |
| `ariadne.yourresume` | `Your résumé` | `Twoje CV` |  | |
| `ariadne.resume.ph` | `Paste your résumé text…` | `Wklej tekst swojego CV…` |  | |
| `ariadne.upload` | `📄&ensp;…or upload .txt / .docx / .pdf` | `📄&ensp;…lub prześlij .txt / .docx / .pdf` |  | |
| `ariadne.jd` | `Job description` | `Opis stanowiska` |  | |
| `ariadne.jd.opt` | `— optional, enables the keyword gap` | `— opcjonalnie, włącza analizę słów kluczowych` | 🚩 | |
| `ariadne.jd.ph` | `Paste the job description…` | `Wklej opis stanowiska…` |  | |
| `ariadne.or` | `— or —` | `— lub —` |  | |
| `ariadne.url.ph` | `https://…  (Greenhouse / Lever / Workday / career page)` | `https://…  (Greenhouse / Lever / Workday / strona kariery)` |  | |
| `ariadne.hint` | `LinkedIn &amp; Indeed are login-walled — paste their text instead.` | `LinkedIn &amp; Indeed wymagają logowania — wklej zamiast tego ich tekst.` | 🚩 | |
| `ariadne.analyze` | `Analyze` | `Analizuj` |  | |
| `ariadne.build` | `Build ATS résumé` | `Utwórz CV ATS` |  | |
| `ariadne.result` | `Result` | `Wynik` |  | |
| `ariadne.download` | `⬇&ensp;Download ATS .docx` | `⬇&ensp;Pobierz ATS .docx` |  | |

---

## Russian (`ru`)

| Key | English | Draft | 🚩 | Correction (edit here) |
|-----|---------|-------|----|------------------------|
| `tab.status` | `Status` | `Статус` |  | |
| `tab.chat` | `Chat` | `Чат` |  | |
| `tab.karaoke` | `Karaoke` | `Караоке` |  | |
| `tab.argus` | `Argus` | `Argus` |  | |
| `tab.morpheus` | `Morpheus` | `Morpheus` |  | |
| `tab.ariadne` | `Ariadne` | `Ariadne` |  | |
| `status.health` | `Health` | `Состояние` |  | |
| `status.runtime` | `Runtime` | `Среда выполнения` |  | |
| `status.langvoice` | `Language & Voice` | `Язык и голос` |  | |
| `status.language` | `Language` | `Язык` |  | |
| `status.voice` | `Voice` | `Голос` |  | |
| `status.tunnel` | `Remote Tunnel (WireGuard)` | `Удалённый туннель (WireGuard)` |  | |
| `status.checking` | `checking…` | `проверка…` |  | |
| `status.tunnel.down` | `Tunnel is <strong>down</strong> — zero exposure at home` | `Туннель <strong>отключён</strong> — нулевая уязвимость дома` |  | |
| `status.tunnel.enable` | `Enable` | `Включить` |  | |
| `voice.note.installed` | `Voice model installed.` | `Голосовая модель установлена.` |  | |
| `voice.tier.strong` | `strong` | `сильный` |  | |
| `voice.tier.functional` | `functional — small local models vary in fluency by language` | `функциональный — небольшие локальные модели различаются по беглости в зависимости от языка` | 🚩 | |
| `voice.offer.prefix` | `Also switch voice to` | `Также сменить голос на` |  | |
| `voice.offer.yes` | `Yes` | `Да` |  | |
| `voice.offer.keep` | `Keep current` | `Оставить текущий` |  | |
| `chat.placeholder` | `Message Ph3b3…` | `Написать Ph3b3…` |  | |
| `chat.send` | `Send` | `Отправить` |  | |
| `util.title` | `Utilities` | `Утилиты` |  | |
| `util.timer` | `Timer` | `Таймер` |  | |
| `util.calc` | `Calculator` | `Калькулятор` |  | |
| `util.converter` | `Converter` | `Конвертер` |  | |
| `util.scratchpad` | `Scratchpad` | `Блокнот` |  | |
| `util.qr` | `QR code` | `QR-код` |  | |
| `util.dice` | `Dice & RNG` | `Кости и ГСЧ` |  | |
| `util.clock` | `World clock` | `Мировые часы` |  | |
| `common.loading` | `Loading…` | `Загрузка…` |  | |
| `chat.conversation` | `Conversation` | `Разговор` |  | |
| `chat.speaking` | `Alba speaking…` | `Alba говорит…` |  | |
| `chat.mic` | `Hold to speak` | `Удерживайте, чтобы говорить` |  | |
| `util.timer.countdown` | `Countdown` | `Обратный отсчёт` |  | |
| `util.timer.stopwatch` | `Stopwatch` | `Секундомер` |  | |
| `util.timer.ready` | `READY` | `ГОТОВО` |  | |
| `util.timer.start` | `Start` | `Старт` |  | |
| `util.timer.reset` | `Reset` | `Сброс` |  | |
| `util.conv.length` | `Length` | `Длина` |  | |
| `util.conv.weight` | `Weight` | `Вес` |  | |
| `util.conv.temp` | `Temperature` | `Температура` |  | |
| `util.conv.data` | `Data size` | `Размер данных` |  | |
| `util.conv.volume` | `Volume` | `Объём` |  | |
| `util.conv.swap` | `&#8645; Swap units` | `&#8645; Поменять единицы` |  | |
| `util.scratch.ph` | `Sticky note — saved to this device only, never synced…` | `Заметка — сохраняется только на этом устройстве, никогда не синхронизируется…` | 🚩 | |
| `util.scratch.clear` | `Clear` | `Очистить` |  | |
| `util.qr.ph` | `Text or URL…` | `Текст или URL…` |  | |
| `util.qr.hint` | `Type above to generate a code.` | `Введите выше, чтобы создать код.` |  | |
| `util.qr.dl` | `Download PNG` | `Скачать PNG` |  | |
| `util.dice.sub` | `crypto-grade randomness` | `случайность криптографического уровня` | 🚩 | |
| `util.dice.coin` | `Coin` | `Монета` |  | |
| `util.dice.roll` | `Roll` | `Бросить` |  | |
| `util.clock.add` | `Add` | `Добавить` |  | |
| `util.clock.note` | `Local &amp; UTC always shown · up to 3 added zones` | `Локальное &amp; UTC всегда показаны · до 3 добавленных зон` |  | |
| `karaoke.title` | `KARAOKE` | `КАРАОКЕ` |  | |
| `karaoke.tagline` | `she's a world karaoke machine` | `она — всемирная караоке-машина` | 🚩 | |
| `karaoke.discover` | `Discover` | `Открытия` | 🚩 | |
| `karaoke.surprise` | `&#10022;&ensp;Surprise me` | `&#10022;&ensp;Удиви меня` |  | |
| `karaoke.search.ph` | `mood, genre or title…` | `настроение, жанр или название…` |  | |
| `karaoke.search` | `Search` | `Поиск` |  | |
| `karaoke.disc.hint` | `Tap 'Surprise me' to begin.` | `Нажмите «Удиви меня», чтобы начать.` |  | |
| `karaoke.prep` | `Prep` | `Подготовить` |  | |
| `karaoke.drop` | `🎵&ensp;Drop a track here · or Browse` | `🎵&ensp;Перетащите трек сюда · или Обзор` |  | |
| `karaoke.convert` | `Convert + Prep` | `Конвертировать + Подготовить` |  | |
| `karaoke.library` | `Library` | `Библиотека` |  | |
| `morpheus.mode.gen` | `✦ Generate` | `✦ Создать` |  | |
| `morpheus.mode.edit` | `✎ Edit` | `✎ Редактировать` |  | |
| `morpheus.generate` | `Generate` | `Создать` |  | |
| `morpheus.modelbl` | `Mode` | `Режим` |  | |
| `morpheus.engine` | `Engine` | `Движок` |  | |
| `morpheus.animating` | `Animating a still` | `Анимация стоп-кадра` | 🚩 | |
| `morpheus.prompt.ph` | `Describe the image…` | `Опишите изображение…` |  | |
| `morpheus.negative.ph` | `Negative — things to avoid (optional)` | `Негатив — чего избегать (необязательно)` |  | |
| `morpheus.advanced` | `Advanced` | `Дополнительно` |  | |
| `morpheus.steps` | `Steps` | `Шаги` |  | |
| `morpheus.width` | `Width` | `Ширина` |  | |
| `morpheus.height` | `Height` | `Высота` |  | |
| `morpheus.seed` | `Seed (−1 = random)` | `Seed (−1 = случайно)` |  | |
| `morpheus.genbtn` | `✦ Generate` | `✦ Создать` |  | |
| `morpheus.generation` | `Generation` | `Генерация` |  | |
| `morpheus.cancel` | `Cancel` | `Отмена` |  | |
| `morpheus.output` | `Output` | `Результат` | 🚩 | |
| `morpheus.output.empty` | `Nothing yet — hit Generate.` | `Пока ничего — нажмите Создать.` |  | |
| `morpheus.download` | `&#8595; Download` | `&#8595; Скачать` |  | |
| `morpheus.gallery` | `Gallery` | `Галерея` |  | |
| `morpheus.refresh` | `Refresh` | `Обновить` |  | |
| `morpheus.delall` | `Delete All` | `Удалить всё` |  | |
| `morpheus.edit.title` | `Edit — img2img` | `Редактирование — img2img` |  | |
| `morpheus.edit.clipnote` | `Clip editing isn't supported yet — Edit works on stills only. Pick an image, or drop one below.` | `Редактирование клипов пока не поддерживается — Редактирование работает только со стоп-кадрами. Выберите изображение или перетащите его ниже.` | 🚩 | |
| `morpheus.edit.drop` | `🖼️&ensp;Drop an image · or Browse` | `🖼️&ensp;Перетащите изображение · или Обзор` |  | |
| `morpheus.edit.prompt.ph` | `Describe the edit…` | `Опишите изменение…` |  | |
| `morpheus.strength` | `Strength` | `Интенсивность` |  | |
| `morpheus.strength.min` | `touch-up` | `ретушь` | 🚩 | |
| `morpheus.strength.max` | `transform` | `преобразование` | 🚩 | |
| `morpheus.edit.run` | `✎ Edit image` | `✎ Редактировать изображение` |  | |
| `morpheus.edit.job` | `Edit job` | `Задача редактирования` |  | |
| `morpheus.edit.ba` | `Before / After` | `До / После` |  | |
| `morpheus.edit.empty` | `Upload an image and hit Edit.` | `Загрузите изображение и нажмите Редактировать.` |  | |
| `morpheus.before` | `Before` | `До` |  | |
| `morpheus.after` | `After` | `После` |  | |
| `argus.fleet` | `Fleet` | `Флот` |  | |
| `argus.captures` | `Captures` | `Захваты` | 🚩 | |
| `argus.chats` | `Chats` | `Чаты` |  | |
| `argus.filter.alldevices` | `all devices` | `все устройства` |  | |
| `argus.filter.alltypes` | `all types` | `все типы` |  | |
| `argus.filter.audio` | `audio` | `аудио` |  | |
| `argus.filter.images` | `images` | `изображения` |  | |
| `argus.state.healthy` | `HEALTHY` | `ЗДОРОВ` |  | |
| `argus.state.sick` | `SICK` | `БОЛЕН` | 🚩 | |
| `argus.state.silent` | `SILENT` | `МОЛЧИТ` | 🚩 | |
| `argus.empty.devices` | `No devices known yet.` | `Устройства пока не известны.` |  | |
| `ariadne.title` | `Ariadne — résumé ATS` | `Ariadne — резюме ATS` |  | |
| `ariadne.note` | `Aligns your <b>truthful</b> experience to ATS vocabulary — it <b>never invents qualifications</b>. Missing keywords you genuinely evidence get surfaced; ones you don't are flagged for you to earn, never added. Your résumé is analyzed <b>locally and never leaves this machine</b> — the only outbound call is fetching a job-post URL you paste.` | `Согласует ваш <b>правдивый</b> опыт со словарём ATS — <b>никогда не выдумывает квалификации</b>. Недостающие ключевые слова, которые вы действительно подтверждаете, выделяются; те, которых у вас нет, отмечаются, чтобы вы их заслужили, но никогда не добавляются. Ваше резюме анализируется <b>локально и никогда не покидает это устройство</b> — единственный исходящий запрос — это загрузка URL вакансии, который вы вставили.` | 🚩 | |
| `ariadne.yourresume` | `Your résumé` | `Ваше резюме` |  | |
| `ariadne.resume.ph` | `Paste your résumé text…` | `Вставьте текст вашего резюме…` |  | |
| `ariadne.upload` | `📄&ensp;…or upload .txt / .docx / .pdf` | `📄&ensp;…или загрузите .txt / .docx / .pdf` |  | |
| `ariadne.jd` | `Job description` | `Описание вакансии` |  | |
| `ariadne.jd.opt` | `— optional, enables the keyword gap` | `— необязательно, включает анализ ключевых слов` | 🚩 | |
| `ariadne.jd.ph` | `Paste the job description…` | `Вставьте описание вакансии…` |  | |
| `ariadne.or` | `— or —` | `— или —` |  | |
| `ariadne.url.ph` | `https://…  (Greenhouse / Lever / Workday / career page)` | `https://…  (Greenhouse / Lever / Workday / страница карьеры)` |  | |
| `ariadne.hint` | `LinkedIn &amp; Indeed are login-walled — paste their text instead.` | `LinkedIn &amp; Indeed требуют входа — вставьте вместо этого их текст.` | 🚩 | |
| `ariadne.analyze` | `Analyze` | `Анализировать` |  | |
| `ariadne.build` | `Build ATS résumé` | `Создать резюме ATS` |  | |
| `ariadne.result` | `Result` | `Результат` |  | |
| `ariadne.download` | `⬇&ensp;Download ATS .docx` | `⬇&ensp;Скачать ATS .docx` |  | |
