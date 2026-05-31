# LuaTools Ultimate

**Versio 9.0.7**

> *Made in Ingria by Free People*  
> *Tehty Inkerissä vapaiden ihmisten toimesta*  
> 59°57′N 30°19′E

> 📄 Muut kielet: [Русский](README.ru.md) · [English (US)](README.md) · [Українська](README.uk.md) · [Беларуская](README.be.md)

---

## 1. Tarkoitus

**LuaTools Ultimate** on Millennium-alustan liitännäinen Steam-asiakasohjelmaan. Se aktivoi pelejä SteamTools-tyylisten `.lua`-komentosarjojen avulla.

Ohjelmisto tarjoaa:

- aktivointikomentosarjojen haun yhdeksän lähteen ketjusta;
- depot-manifestien välimuistin eheyden ylläpidon ja vioittuneiden tietueiden automaattisen korjauksen;
- useiden käyttäjätilien hallinnan ilman asiakasohjelman uudelleenkäynnistystä;
- Tokeer-käynnistimien määrityksen Denuvo-suojatuille peleille;
- asennetun pelikirjaston tilan taustaseurannan.

Ohjelmistorunko on toteutettu Pythonilla (taustajärjestelmä) ja JavaScriptillä (käyttöliittymä). Erillistä käännösvaihetta ei tarvita.

---

## 2. Rakenne

```
ltsteamplugin-ultimate/
├── plugin.json                     Millennium-manifesti
├── README.md / .ru.md / .uk.md / .be.md / .fi.md
├── CLAUDE.md                       kehityskonteksti
├── SENTINEL_v9.md                  Sentinelin suunnitteludokumentti
│
├── backend/
│   ├── main.py                     sisääntulopiste, IPC-kääreet
│   │
│   ├── ── Lataus ja aktivointi ──
│   ├── downloads.py                yhdeksän lähteen ketju
│   ├── batch.py                    rinnakkainen latausjono
│   ├── source_chain.py             käyttäjän järjestämä lähdeketju
│   ├── history.py                  SQLite-loki, lähdekohtainen tilasto
│   ├── custom_apis.py              käyttäjän omat lähteet
│   │
│   ├── ── Korjaukset ──
│   ├── fixes.py                    HuggingFace-indeksi, RAR/7Z, LFS
│   ├── cloud_fix.py                online-korjausten latain
│   ├── steamtools.py               auditointi, välimuistin korjaus
│   │
│   ├── ── Käyttäjätilit (v8.4–8.5) ──
│   ├── account_transfer.py         userdata-kansion kopiointi
│   ├── account_switch.py           DPAPI-purku, tilin vaihto
│   ├── tokeer_launcher.py          Denuvo-ohitus Tokeerilla
│   ├── key_vault.py                Ryuu/DepotBox/Morrenus-avainprofiilit
│   │
│   ├── ── Automaatio v9.0 ──
│   ├── sentinel.py                 taustavalvoja
│   ├── sentinel_worker.py          itsenäinen työprosessi
│   ├── sentinel_service.py         Windows-ajastetun tehtävän asentaja
│   ├── sync_engine.py              koneiden välinen synkronointi
│   ├── crack_migrator.py           vanhojen krakkausten tunnistus
│   ├── profiles.py                 pelikohtaiset kokoonpanot
│   ├── workshop_manager.py         Steam Workshop -tilausten hallinta
│   ├── achievement_watch.py        saavutusten seuranta (vain luku)
│   │
│   ├── ── Infrastruktuuri ──
│   ├── settings/                   asetusten skeema ja tallennus
│   ├── steam_utils.py              VDF-jäsennin, asennuspolun haku
│   ├── steam_version.py            Steam-prosessin tunnistus
│   ├── http_client.py              jaettu httpx-asiakas
│   ├── auto_update.py              GitHub-julkaisujen seuranta
│   ├── donate_keys.py              7 vuorokauden kaksoiskappalevälimuisti
│   ├── events.py                   webhook-koukut (Discord, ntfy.sh)
│   ├── mod_system.py               käyttäjämodien latain
│   ├── security.py                 ZIP-tarkistus, polkusuojaus
│   ├── paths.py                    Windows 11 -polkujen ratkaisu
│   ├── logger.py
│   └── locales/                    yli 30 kielen käännökset
│
├── public/
│   ├── luatools.js                 käyttöliittymä (~8200 riviä)
│   ├── steamdb-webkit.css          SteamDB-integraatio
│   ├── luatools-icon.png
│   └── themes/                     12 teemaa
│       └── ingria.css              oletusteema
│
├── mods/                           käyttäjän .lua-modit
├── scripts/                        PowerShell-apuskriptit
└── .millennium/Dist/               käännetty käyttöliittymäpaketti
```

---

## 3. Toiminnot

### 3.1 Lähdeketju

Aktivointikomentosarjat haetaan kyselemällä yhdeksää lähdettä tärkeysjärjestyksessä:

```
Paikallinen kansio → TwentyTwo Cloud → Ryuu Premium →
DepotBox Premium → ManifestHub API → Custom APIs →
Free APIs → SLStools Fallbacks → GitHub-arkistot
```

Kolmen peräkkäisen *connection refused* -virheen jälkeen ketju keskeytetään. Tämä estää kaskadimaisen virheen verkon ollessa poissa käytöstä.

### 3.2 Depot-välimuistin korjaus

Suoritetaan neljässä vaiheessa:

1. **Kartoitus.** Jokainen `.manifest`-tiedosto luokitellaan kelvolliseksi, vioittuneeksi, nollatavuiseksi tai orvoksi.
2. **Lataus.** Puuttuvat ja vioittuneet manifestit haetaan uudelleen peilipalvelimilta GitHub → Morrenus → ManifestHub.
3. **Siivous.** Tyhjät tiedostot poistetaan, vioittuneet korvataan, vanhentuneet orvot poistetaan.
4. **Lua-korjaus** *(valinnainen).* Syntaktisesti virheelliset rivit kommentoidaan merkinnällä `--LUATOOLS_AUTOFIXED:`, mikä tekee toiminnosta peruutettavan.

Esikatselutila on käytettävissä ennen jokaista tuhoavaa toimenpidettä.

### 3.3 Sentinel — taustaseuranta

Ohjelmademoni, joka suoritetaan joko:

- säikeenä liitännäisprosessin sisällä (oletus), tai
- itsenäisenä prosessina **Windowsin ajastetun tehtävän** kautta (`schtasks.exe /SC ONLOGON`, ei UAC:ia).

Demonin toiminnot:

- `steamapps/`-kansion seuranta uusien asennusten varalta;
- käyttäjän ilmoittaminen Windowsin ponnahdusviesteillä;
- manifestien vanhentumisen säännöllinen tarkistus `api.steamcmd.net`-rajapinnan kautta (oletus: 24 tunnin pelikohtainen tarkistusväli);
- ohitettujen pelien luettelo ja ilmoituskohtaiset aikakatkaisut.

### 3.4 Käyttäjätilit

| Osajärjestelmä | Tarkoitus |
|---|---|
| `account_transfer` | Kopioi `userdata/<accountId>/<appid>/` kahden oman tilin välillä Denuvo-aktivointitunnusten tai pilvitallennusten siirtämiseksi. |
| `account_switch` | Käynnistää Steamin uudelleen valitulle tilille kirjautuneena. Purkaa tallennetut refresh-tunnukset DPAPI-menetelmällä. Vaihto kestää noin kolme sekuntia. |
| `key_vault` | Tallentaa aktiiviset API-avaimet nimettyinä profiileina. Vie kannettavaan base64-muotoon `.ltkeys`. |

### 3.5 Denuvo-ohitus (Tokeer)

Kolmellekymmenelle kahdelle Denuvo-suojatulle pelille, jotka toimitetaan `tokeer_launcher.exe`-tiedoston kanssa, kirjoitetaan automaattisesti Steamin käynnistysasetukset valitun käyttäjän `localconfig.vdf`-tiedostoon. Luetteloon kuuluvat muun muassa Pragmata, Resident Evil Requiem, MGSV: TPP, Hogwarts Legacy, Persona 5 Royal, Stellar Blade ja Mortal Kombat 1.

### 3.6 Koneiden välinen synkronointi

Ohjelmiston tila synkronoidaan usean asennuksen välillä kahdella mekanismilla:

- **Git.** Mikä tahansa yksityinen etäarkisto (GitHub, GitLab, Codeberg).
- **Kansio.** Paikallinen polku, verkkoasema tai Syncthing-valvottu hakemisto. Peilaus sisällön mukaan (SHA-256).

Synkronoidaan: `.lua`-komentosarjat, avainprofiilit, Sentinelin kokoonpano, lähdeketju, pyydettäessä latausloki. Steamin asennuspolut ja konekohtaiset välimuistit pysyvät paikallisina.

### 3.7 Krakkausten siirto

Asennettujen pelien kartoitus kahdeksan krakkausperheen tunnisteiden varalta: Goldberg, CODEX/CPY, CreamAPI, ALI213, UnSteam, RUNE, yleiset Steam API -lataimet, DLL-välityskaappaukset.

Siirto suoritetaan oletuksena *dry-run* -tilassa. Vahvistettaessa tiedostot siirretään hakemistoon `<peli>/_luatools_migration_<aikaleima>/`. Alkuperäisiä tiedostoja ei koskaan poisteta.

### 3.8 Pelikohtaiset profiilit

Jokaiselle pelille voidaan tallentaa useita nimettyjä kokoonpanoja, joista kukin sisältää `.lua`-komentosarjan sisällön ja käynnistysasetukset. Vaihto esimerkiksi kokoonpanojen *»Persona 5 + Tokeer»* ja *»Persona 5 vanilla»* välillä tapahtuu yhdellä napsautuksella.

### 3.9 Workshop

Käyttäjän Steam Workshop -tilaukset luetaan `localconfig.vdf`-tiedostosta. Jokaiselle tilatulle kohteelle haetaan metatiedot ja suora latausosoite julkisen `ISteamRemoteStorage/GetPublishedFileDetails`-rajapinnan kautta. Lataus tapahtuu suoraan Steam-asiakasohjelman ohi.

### 3.10 Saavutusten seuranta *(vain luku)*

Koontinäyttö, joka esittää saavutusten edistymisen kunkin `.lua`-aktivoidun pelin osalta. Tietolähteet:

- Web API -skeema (`ISteamUserStats/GetSchemaForGame`) — saavutusten kokonaismäärä;
- paikallinen tiedosto `UserGameStats_<accountId>_<appid>.bin` — avattujen laskuri.

Tilastotiedostoihin ei kirjoiteta. Osajärjestelmä on tarkoituksellisesti toteutettu vain luku -tilassa — julkisten saavutustilastojen muokkaaminen rikkoo Steamin käyttöehtoja.

---

## 4. Järjestelmävaatimukset

| Komponentti | Vaatimus |
|---|---|
| Käyttöjärjestelmä | Windows 10 / 11 (x64) |
| Alusta | Millennium 2.35+ |
| Python | toimitetaan Millenniumin mukana |
| Verkko | Lähtevä HTTPS osoitteisiin `huggingface.co`, `api.steampowered.com`, `api.steamcmd.net`, `github.com` sekä valitut premium-lähteet |
| Valinnainen | 7-Zip tai WinRAR (RAR/7Z-korjausten purkuun), Git (arkistopohjaiseen synkronointiin) |

---

## 5. Asennus

1. Pura arkisto hakemistoon `<Steam>\plugins\luatools\` (esimerkiksi `D:\Steam\plugins\luatools\`).
2. Käynnistä Steam uudelleen.
3. Ota liitännäinen käyttöön: **Steam → Millennium → Plugins → LuaTools Ultimate**.

---

## 6. Turvallisuusohjeet

- **Steamin on oltava suljettuna** ennen jokaista toimenpidettä, joka kirjoittaa tiedostoihin `userdata/`, `localconfig.vdf` tai `loginusers.vdf`.
- **Varmuuskopiot luodaan automaattisesti** ennen jokaista tuhoavaa toimenpidettä. Nimeämiskäytäntö: `*.bak-<aikaleima>` tai `*.presync-<aikaleima>`.
- **DPAPI-tunnukset luetaan, mutta niitä ei muuteta.** Tilin vaihto käsittelee vain `loginusers.vdf`-tiedoston `MostRecent`-osoitinta.
- **Lua-automaattikorjaus on peruutettavissa.** Virheellisiä rivejä ei poisteta — ne kommentoidaan selkeällä merkinnällä `--LUATOOLS_AUTOFIXED:`.

---

## 7. IPC-rajapinta

Katso tiedosto `backend/main.py`. Yleisimmin käytetyt:

```
RepairDepotCache(appid, fix_lua, remove_orphans, dry_run)
SyncDepotcache(appid)
GetAchievementProgress(appid, accountId32)
TransferGameUserdata(from, to, appid, overwrite, backup)
SwitchToAccount(accountName)
ConfigureTokeerLaunch(appid, accountId32)
SyncPush() / SyncPull(dryRun=False)
ScanCrackedGames() / MigrateGame(appid, dryRun=True)
ListWorkshopSubscribed(appid, accountId32)
SaveProfile(appid, name) / ActivateProfile(appid, slug)
GetSentinelService() / InstallSentinelService()
```

---

## 8. Kiitokset

| Lähde | Panos |
|---|---|
| **madoiscool** | alkuperäinen `ltsteamplugin` |
| **sigmachan** | muokattu haarautuma (Ryuu/DepotBox/teemat) |
| **clemdotla** | `steamtools-collection` — auditointi- ja synkronointilogiikka, siirretty Luasta Pythoniin Windowsille |
| **RaiSantos** | `lt_api_links` — Tokeer-yhteensopivuusluettelo, `Devuvo.ps1`, HuggingFace-korjausindeksi, manifestiketju |
| **RobiZkt** | `Steam-Token-Grabber` — DPAPI-toteutus tilin vaihtoon |
| **SteamTokenDumper-yhteisö** | depot-tunnusten tietokanta |

---

## 9. Aatteellisuuden hylkääminen

Ohjelmisto ei sisällä poliittisia tunnuksia, lippukuvioita eikä iskulauseita. Oletusteeman väripaletti perustuu luoteisalueen ilmastoon: kirkas talvitaivas Suomenlahden yllä, valoisten öiden pehmeä hehku. Kaikki muut mielleyhtymät jäävät lukijan omiksi.

---

*Tekniset termit esitetään vakiintuneessa englanninkielisessä muodossa, jotta koodihaku pysyy yhtenäisenä kielten välillä.*
