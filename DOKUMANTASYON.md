# ScrapeHub — Ayrıntılı Dokümantasyon ve Mimari Rehberi

> Bu dosya, projeyi **sıfırdan** anlamak isteyen biri için yazılmış kapsamlı bir rehberdir.
> Hiç scraping/Celery/Redis bilmeden okumaya başlayabilirsin; her kavramı yeri geldikçe
> açıklıyoruz. Hızlı kurulum için ana [README.md](README.md)'ye bak; bu dosya **"neden ve
> nasıl"** sorularına odaklanır.

İçindekiler:

1. [Proje ne yapıyor?](#1-proje-ne-yapıyor)
2. [Büyük resim: dağıtık pipeline nedir?](#2-büyük-resim-dağıtık-pipeline-nedir)
3. [Bir isteğin baştan sona yolculuğu](#3-bir-isteğin-baştan-sona-yolculuğu)
4. [Dosya dosya: her parça ne işe yarar?](#4-dosya-dosya-her-parça-ne-işe-yarar)
5. [Katman 1 — API + Kuyruk (FastAPI + Celery + Redis)](#5-katman-1--api--kuyruk)
6. [Katman 2 — Tekilleştirme (Dedup: Bloom filter + içerik-hash)](#6-katman-2--tekilleştirme)
7. [Katman 3+4 — Nazik indirme (Fetcher)](#7-katman-34--nazik-indirme)
8. [Katman 5 — Çok kademeli dayanıklı parser](#8-katman-5--çok-kademeli-dayanıklı-parser)
9. [Depolama (SQLAlchemy + upsert)](#9-depolama)
10. [Ölçeklenme: chunk/batch dağıtım](#10-ölçeklenme-chunkbatch-dağıtım)
11. [Domain-bazlı rate limit](#11-domain-bazlı-rate-limit)
12. [Incremental (artımlı) güncelleme](#12-incremental-artımlı-güncelleme)
13. [Dayanıklılık: retry + dead-letter](#13-dayanıklılık-retry--dead-letter)
14. [İzleme: Flower](#14-i̇zleme-flower)
15. [Web Arayüzü (Kontrol Paneli)](#15-web-arayüzü-kontrol-paneli)
16. [Çalıştırma kılavuzu (3 mod)](#16-çalıştırma-kılavuzu)
17. [Test stratejisi](#17-test-stratejisi)
18. [Konfigürasyon (tüm env değişkenleri)](#18-konfigürasyon)
19. [Sık sorulan sorular](#19-sık-sorulan-sorular)
20. [Etik ve yasal](#20-etik-ve-yasal

---

## 1. Proje ne yapıyor?

ScrapeHub, bir web sitesindeki sayfaları **otomatik olarak gezip** (crawl), her sayfadan
**yapısal veri çıkaran** (parse) ve bunu bir **veritabanına yazan** bir sistemdir. Hedef
sitemiz [books.toscrape.com](https://books.toscrape.com) — tam olarak bu amaçla, yani
scraping pratiği yapılsın diye **kasıtla yayınlanmış**, anti-bot savunması olmayan, izinli
bir demo kitap mağazasıdır.

Ama asıl amaç "kitap çekmek" değil. Asıl amaç, **gerçek dünyada ölçeklenen bir scraping
mimarisinin** nasıl kurulduğunu öğretmek:

- Binlerce sayfayı **paralel** işleme (tek tek değil, aynı anda onlarca worker).
- Aynı sayfayı **iki kez işlememe** (deduplication).
- Sunucuyu **yormama** (nezaket gecikmesi, retry/backoff, robots.txt).
- Site tasarımı **değişse bile kırılmayan** veri çıkarımı.
- Bir şey **ters giderse** (ağ hatası, çökme) sistemin kendini toparlaması.

Aynı iskelet; izin veren herhangi bir site veya açık bir API için kullanılabilir.

---

## 2. Büyük resim: dağıtık pipeline nedir?

"Pipeline" (boru hattı) = veri, bir dizi istasyondan sırayla geçer. "Dağıtık" = bu
istasyonlar tek bir programda değil, **birbirinden bağımsız çalışan parçalarda** durur ve
aralarında bir **kuyruk** üzerinden haberleşir.

Neden tek bir döngü (`for url in urls: ...`) yerine bu karmaşa? Çünkü:

- **Paralellik:** 10.000 sayfayı tek tek çekmek saatler sürer. 50 worker'a dağıtırsan
  dakikalara iner.
- **Dayanıklılık:** Bir worker çökerse iş kaybolmaz; başka worker devralır.
- **Ölçeklenme:** Yük artınca sadece worker sayısını artırırsın; kod değişmez.

Parçalar:

```
  İstemci ──HTTP──► FastAPI ──kuyruğa koy──► Redis ──dağıt──► Celery Worker'lar ──yaz──► DB
  (sen/cron)        (API)                    (broker)         (gerçek işçiler)          (Postgres/SQLite)
```

- **FastAPI (API):** Dışarıdan "şu siteyi kaz" emrini alır, işi kuyruğa koyar ve **hemen**
  döner (uzun işi beklemez — buna *asenkron* denir).
- **Redis (broker):** İşlerin biriktiği kuyruk. Aynı zamanda dedup için Bloom filter'ı tutar.
- **Celery Worker'lar:** Kuyruktaki işleri çekip asıl scraping'i yapan işçiler. Kaç tane
  olduklarını sen belirlersin.
- **Veritabanı:** Sonuçların yazıldığı yer.

---

## 3. Bir isteğin baştan sona yolculuğu

Diyelim `POST /scrape {"max_pages": 5, "chunk_size": 10}` gönderdin. Adım adım ne olur:

1. **`app/main.py`** isteği alır, `discover_catalog` görevini kuyruğa koyar (`.delay()`),
   sana bir `task_id` döndürür. (Burada henüz hiçbir sayfa çekilmedi!)
2. Bir worker kuyruktan **`discover_catalog`** görevini çeker. Katalog sayfalarını (1..5)
   gezer, her sayfadaki kitap linklerini toplar. Diyelim 100 kitap URL'i buldu.
3. Bu 100 URL'i tek tek değil, **10'arlı gruplar (chunk)** halinde tekrar kuyruğa koyar.
   Yani 10 adet "10 kitabı işle" görevi oluşur (broker'a 100 mesaj yerine 10 mesaj = daha verimli).
4. Boştaki worker'lar bu chunk görevlerini kapışır. Her chunk içindeki her URL için
   **`scrape_book`** mantığı çalışır:
   - **Dedup:** Bu URL'i daha önce işledik mi? (Bloom filter'a sor.) İşlediyse **atla**.
   - **Fetch:** Sayfayı nazikçe indir (retry'lı, gecikmeli). Başarısızsa → retry → dead-letter.
   - **Parse:** HTML'den `Book` objesi çıkar (JSON-LD → CSS → regex fallback zinciriyle).
   - **Store:** Veritabanına yaz (URL'e göre upsert: varsa güncelle, yoksa ekle).
5. Sen bu sırada `GET /status/{task_id}` ile durumu, `GET /stats` ile DB'deki kitap
   sayısını sorgulayabilirsin. `http://localhost:5555` (Flower) ile worker'ları canlı izlersin.

---

## 4. Dosya dosya: her parça ne işe yarar?

```
ScrapeProjem/
├── app/
│   └── main.py            # FastAPI: dış dünyaya açılan kapı (endpoint'ler + frontend servisi)
├── frontend/
│   ├── index.html         # Web kontrol paneli
│   ├── styles.css         # Karanlık tema CSS
│   └── app.js             # Vanilla JS dashboard mantığı
├── workers/
│   ├── celery_app.py      # Celery yapılandırması (broker, retry, rate limit ayarları)
│   └── tasks.py           # Asıl görevler: discover_catalog + scrape_book
├── core/
│   ├── config.py          # Tüm ayarların tek merkezi (env'den okur, default'ları var)
│   ├── dedup.py           # Tekilleştirme: Bloom filter + içerik-hash
│   └── fetcher.py         # Nazik HTTP indirici (retry/backoff/robots/gecikme)
├── parser/
│   └── extract.py         # HTML -> Pydantic Book (çok kademeli, LLM'siz)
├── storage/
│   └── db.py              # SQLAlchemy: tablo tanımı + upsert + sayım
├── tests/                 # Pytest paketi + canlı bloom doğrulama scripti
│   ├── conftest.py        # Test ortak kurulum (izole geçici DB, memory dedup)
│   ├── test_parser.py     # Parser doğru Book çıkarıyor mu? Fallback'ler çalışıyor mu?
│   ├── test_dedup.py      # İlk görüş False / ikinci True?
│   ├── test_db.py         # Upsert duplicate satır açmıyor mu?
│   ├── test_discover.py   # Chunk dağıtımı çalışıyor mu? (eager mod)
│   ├── test_incremental.py# Domain gecikme + içerik-hash mantığı
│   ├── test_deadletter.py # Retry tetikleyici + dead-letter yönlendirme
│   └── verify_bloom.py    # CANLI RedisBloom doğrulaması (test değil, elle çalıştırılır)
├── run_local.py           # Redis/Celery KURMADAN tüm pipeline'ı senkron çalıştırır
├── requirements.txt       # Python bağımlılıkları
├── Dockerfile             # API/worker imajı
├── docker-compose.yml     # redis + postgres + api + worker + flower
├── README.md              # Hızlı başlangıç
└── DOKUMANTASYON.md       # (bu dosya) ayrıntılı rehber
```

**Tasarım ilkesi:** Her dosya **tek bir sorumluluğa** sahip. Dedup'ı değiştirmek istersen
sadece `core/dedup.py`'a dokunursun; fetcher'dan habersizdir. Bu, "separation of concerns"
(sorumlulukların ayrılması) ilkesidir ve kodu test edilebilir/değiştirilebilir kılar.

---

## 5. Katman 1 — API + Kuyruk

**Dosyalar:** `app/main.py`, `workers/celery_app.py`, `workers/tasks.py`

### FastAPI (`app/main.py`)
Dış dünyaya 5 endpoint açar:

| Endpoint | Ne yapar |
|----------|----------|
| `POST /scrape` | Katalog tarama işini kuyruğa atar (`start_url`, `max_pages`, `chunk_size`) |
| `POST /scrape-one` | Tek bir URL'i kuyruğa atar |
| `GET /status/{task_id}` | Bir Celery görevinin durumunu sorgular |
| `GET /stats` | DB'deki kitap sayısı + dedup backend bilgisi |
| `GET /health` | Servis ayakta mı + hedef site + dedup backend |

Kritik nokta: `/scrape` **işi yapmaz**, sadece **kuyruğa koyar** ve anında döner. Asıl iş
worker'larda arka planda olur. Bu sayede API binlerce isteği bloke olmadan karşılar.

### Celery (`workers/celery_app.py`)
Celery, "görev kuyruğu" kütüphanesidir. Yapılandırmadaki önemli ayarlar:

- `task_acks_late=True`: Görev **bittiğinde** onaylanır. Worker yarıda çökerse görev
  kuyrukta kalır, başka worker tekrar dener. (Aksi halde "alındı" der almaz çökerse iş kaybolur.)
- `task_reject_on_worker_lost=True`: Worker ölürse görev kaybolmaz, yeniden kuyruğa döner.
- `worker_prefetch_multiplier=1`: Her worker kuyruktan tek tek iş alır = adil dağıtım
  (yavaş bir worker önden 100 iş kapıp tıkamaz).
- `task_default_rate_limit`: Worker tarafında saniyede maksimum görev sayısı (nezaket).

### Görevler (`workers/tasks.py`)
İki görev var:

- **`discover_catalog`**: Katalog sayfalarını gezip kitap URL'lerini bulur ve `scrape_book`
  görevlerini (chunk'lar halinde) kuyruğa koyar. (Detay: [Bölüm 10](#10-ölçeklenme-chunkbatch-dağıtım))
- **`scrape_book`**: Tek bir kitabı işler (dedup → fetch → parse → store). Hata yönetimi
  ve incremental mod burada. (Detay: [Bölüm 13](#13-dayanıklılık-retry--dead-letter))

---

## 6. Katman 2 — Tekilleştirme

**Dosya:** `core/dedup.py`

İki ayrı soruya cevap verir:

### a) "Bu URL'i daha önce gördük mü?" — Bloom Filter

**Sorun:** 500.000 URL'i bir SQL tablosunda `SELECT ... WHERE url=?` ile aramak pahalıdır
(her kontrol disk/indeks erişimi).

**Çözüm:** **Bloom filter** — olasılıksal bir veri yapısı. RAM'de O(1) (nanosaniye) hızında
"bu öğeyi kesinlikle görmedim" veya "muhtemelen gördüm" cevabı verir. Tek "kusur"u: küçük,
ayarlanabilir bir yanlış-pozitif oranı (default %0.1). Yani çok nadiren "gördüm" der ama
görmemiştir; **asla** tersi olmaz ("görmedim" dediyse kesin görmemiştir). Scraping'de bu
takas mükemmeldir: nadiren bir sayfayı atlamak, milyonlarca sayfayı hızlı kontrol etmenin
yanında önemsizdir.

Çalışma modları:
- **Redis Stack varsa** → gerçek **RedisBloom** modülü (`BF.RESERVE` / `BF.ADD` / `BF.EXISTS`
  komutları). Devasa ölçek, RAM'de, kalıcı.
- **Redis yoksa** → otomatik olarak **in-memory set** fallback'ine düşer (tek makinede
  ders/test için yeterli). Kod hiç değişmez; `backend` alanı `"memory"` olur.

İlgili metotlar: `seen(url)`, `mark(url)`, `check_and_mark(url)` (atomik: görmediyse işaretle
ve `False` dön = işle; gördüyse `True` dön = atla).

> **Canlı görmek ister misin?** `tests/verify_bloom.py` bir Redis Stack'e bağlanıp
> `backend == "redis-bloom"` olduğunu ve `BF.ADD/EXISTS`'in gerçekten çalıştığını kanıtlar.

### b) "Gördüğümüzden beri sayfa değişti mi?" — İçerik Hash

`content_changed(url, html)`: Sayfanın içeriğinin SHA-1 özetini saklar. Aynı URL tekrar
geldiğinde yeni özeti eskiyle karşılaştırır:
- Yeni URL ya da içerik değişmiş → `True` (yeniden işle) + yeni özeti sakla.
- İçerik aynı → `False` (boşuna parse/DB yazımı yapma).

Bu, **incremental güncellemenin** kalbidir ([Bölüm 12](#12-incremental-artımlı-güncelleme)).

---

## 7. Katman 3+4 — Nazik indirme

**Dosya:** `core/fetcher.py`

"Stealth tarayıcı / proxy şelalesi / anti-bot bypass" YOK. İzin veren bir hedefte bunlara
gerek yoktur. Onun yerine **sağlam mühendislik**:

- **httpx** ile basit, hızlı istekler.
- **Retry + exponential backoff:** İstek başarısızsa (ağ hatası ya da `429/503` "yavaşla"
  sinyali) üstel artan beklemeyle tekrar dener (1s, 2s, 4s...). Sunucuya saygı.
- **Nezaket gecikmesi:** Her istekten sonra biraz bekler. Artık bu gecikme **domain-bazlı**
  ayarlanabilir ([Bölüm 11](#11-domain-bazlı-rate-limit)).
- **robots.txt kontrolü:** Hedef sitenin izin verdiği path'leri çeker (`respect_robots`).

`get(url)` başarısızsa `None` döndürür; çağıran taraf (görev) buna göre retry/dead-letter
kararı verir.

---

## 8. Katman 5 — Çok kademeli dayanıklı parser

**Dosya:** `parser/extract.py`

**Felsefe:** "Site tasarımı değişse de parser çalışmaya devam etsin, hiçbir API anahtarı
gerekmesin." Eskiden bir LLM parser'ı vardı; **kaldırıldı**. Yerine her alan için **üç
kademeli fallback** zinciri kuruldu. Bir kaynak başarısız olursa diğerine düşer:

1. **Yapısal veri:** `<script type="application/ld+json">` (schema.org) ve `og:`/`<meta>`
   etiketleri. Sayfanın görünümünden bağımsız, en sağlam kaynak.
2. **CSS seçiciler:** Aynı alan için **birden fazla** yedek seçici. Biri kırılırsa diğeri yakalar.
3. **Regex/pattern:** Son çare. Ham metinden desenle çek (ör. `£51.77`, `22 available`,
   `4 out of 5`).

Her kademe `Optional` döndürür; **ilk None-olmayan değer kazanır** (`_first(...)` yardımcısı).
Pydantic `Book` modeli **değişmedi** (title, price, availability, rating, url, description).

Örnek — `title` alanının fallback zinciri:
```
JSON-LD "name"  →  og:title/meta  →  div.product_main h1 / h1 / article h1  →  <title> etiketi
```

Bu sayede tek bir CSS seçici değişse bile alan boş kalmaz. `parse_html()` title'ı hiçbir
kaynaktan bulamazsa (sayfa tanınmıyor) `None` döner ve görev `parse_failed` olur.

---

## 9. Depolama

**Dosya:** `storage/db.py`

- **SQLAlchemy** ile veritabanı soyutlanır. `DATABASE_URL` Postgres'e işaret ediyorsa
  Postgres, etmiyorsa **SQLite** kullanılır. Böylece repoyu klonlayan kişi **sıfır kurulumla**
  (SQLite ile) çalıştırır; prodüksiyonda tek satır env değiştirip Postgres'e geçer.
- `BookRow` tablosunda `url` üzerinde tek bir **unique index** (`ix_books_url`) var → aynı URL
  iki kez yazılamaz **ve** upsert'teki `WHERE url = ?` araması indeksli/hızlı olur.
- **`upsert_book(book)`:** URL'e göre "upsert" — satır varsa **günceller**, yoksa **ekler**.
  Bu sayede aynı kitabı tekrar işlersen DB'de **duplicate satır oluşmaz**, sadece güncellenir.

---

## 10. Ölçeklenme: chunk/batch dağıtım

**Dosya:** `workers/tasks.py` → `discover_catalog`

**Sorun:** 10.000 kitap URL'ini tek tek `.delay()` ile kuyruğa atmak = broker'a 10.000 ayrı
mesaj = gereksiz yük.

**Çözüm:** Celery'nin **`chunks`** özelliği. URL'leri gruplayıp tek bir `group` olarak
kuyruğa atarız:
```python
items = [(u,) for u in book_urls]
scrape_book.chunks(items, chunk_size).group().apply_async()
```
`chunk_size=10` ise 1000 URL → 100 görev (her görev 10 URL işler). Çok daha az mesaj, daha
iyi throughput.

**Geriye uyumluluk:** `chunk_size <= 1` verilirse eski davranışa (her URL için ayrı
`.delay()`) düşer. Böylece küçük demo akışı hiç değişmeden çalışır. Parametre
`POST /scrape`'ten ayarlanabilir.

---

## 11. Domain-bazlı rate limit

**Dosyalar:** `core/config.py` (`request_delay_for`), `core/fetcher.py`

Farklı siteler farklı hassasiyettedir. Tek bir global gecikme yerine **domain başına** ayrı
gecikme tanımlanabilir. `DOMAIN_DELAYS` env'i:
```
DOMAIN_DELAYS="books.toscrape.com:0.5,example.com:2.0"
```
`settings.request_delay_for(url)`, URL'in domain'ine bakar; tanımlıysa ona özel gecikmeyi,
değilse genel `REQUEST_DELAY` default'unu döndürür (`www.` öneki toleranslı). Fetcher hem
nezaket gecikmesinde hem backoff hesabında bu değeri kullanır.

---

## 12. Incremental (artımlı) güncelleme

**Dosyalar:** `core/dedup.py` (`content_changed`), `workers/tasks.py` (`scrape_book`)

**Senaryo:** Aynı katalogu her gün çekiyorsun. Çoğu sayfa **değişmedi**; sadece bazı
fiyat/stok güncellendi. Hepsini baştan parse edip DB'ye yazmak israf.

**Çözüm:** `INCREMENTAL=true` olduğunda `scrape_book` şöyle davranır:
- URL daha önce görülmüş olsa **bile** sayfayı çeker.
- `content_changed(url, html)` ile içeriği önceki özetle karşılaştırır.
  - Değişmemiş → `skipped_unchanged` (parse/DB yazımı yok, kaynak tasarrufu).
  - Değişmiş → yeniden parse + `upsert` → `updated`.

`INCREMENTAL` kapalıyken (default) klasik URL-bazlı bloom davranışı aynen geçerlidir.
İki mekanizmanın farkı: **Bloom** = "bu URL'i hiç gördük mü?"; **content-hash** = "gördüğümüzden
beri değişti mi?".

---

## 13. Dayanıklılık: retry + dead-letter

**Dosyalar:** `workers/tasks.py`, `workers/celery_app.py`

Gerçek dünyada istekler başarısız olur (ağ kesintisi, geçici 503...). Sistem bununla baş
etmeli:

- **Otomatik retry:** `scrape_book` fetch başarısız olunca `FetchError` fırlatır. Celery
  bunu yakalayıp **üstel backoff + jitter** (gürültü) ile `max_retries` kez yeniden dener.
  ```python
  @shared_task(autoretry_for=(FetchError,), retry_backoff=True, retry_jitter=True, ...)
  ```
  (jitter, tüm worker'ların aynı anda tekrar denemesini — "thundering herd" — önler.)
- **Dead-letter:** Tüm retry'lar tükenip görev **kalıcı** başarısız olunca, özel
  `DeadLetterTask.on_failure` devreye girer ve başarısız görevi bir **dead-letter kuyruğuna**
  (`scrapehub:dead_letter` redis listesi) yazar. Redis yoksa loga düşer. Operatör buradan
  başarısızları inceleyip elle yeniden işleyebilir.
- **Worker çökmesi:** `task_acks_late` + `task_reject_on_worker_lost` sayesinde bir worker
  iş ortasında ölürse görev kaybolmaz, başka worker'a geçer.

---

## 14. İzleme: Flower

**Dosya:** `docker-compose.yml` (flower servisi)

**Flower**, Celery için web tabanlı bir izleme arayüzüdür. `docker compose up` ile gelir;
`http://localhost:5555` adresinden:
- Aktif/biten/başarısız görevleri,
- Worker'ların canlı durumunu, yükünü,
- Görev başına süreleri ve sonuçları
canlı izlersin. Docker'sız çalıştırmak için:
```bash
celery -A workers.celery_app.celery_app flower --port=5555
```

---

## 15. Web Arayüzü (Kontrol Paneli)

**Dosyalar:** `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`, `app/main.py` (static mount + CORS)

API'ye entegre, modern ve karanlık tema bir kontrol paneli eklendi. `docker compose up` veya `uvicorn app.main:app` çalıştırdıktan sonra tarayıcıdan `http://localhost:8000` adresine giderek kullanabilirsiniz.

Arayüz üzerinden yapabilecekleriniz:

- **Dashboard:** DB'deki kitap sayısı, işlenen/başarısız sayfa, dead-letter derinliği ve ham Prometheus metrikleri.
- **Kazıma Başlat:**
  - Katalog kazıma (start URL, max sayfa, chunk boyutu, webhook).
  - Tek URL kazıma (force seçeneği ile Bloom Filter'ı atla).
  - AI destekli dinamik kazıma (Playwright + Llama).
- **Görevler:** Celery task ID ile durum sorgulama ve son görev geçmişi.
- **Kitaplar:** Veritabanındaki kitapları tablo halinde görüntüleme ve sayfalama.
- **Dead Letter:** Başarısız görevleri ve hata mesajlarını inceleme.
- **Sağlık:** Redis ve PostgreSQL bağlantı durumu.

Teknik detaylar:

- FastAPI `StaticFiles` ile `frontend/` dizini `/static` altında servis edilir.
- `GET /` isteği `frontend/index.html` dosyasını döndürür.
- CORS açıktır; frontend ayrı bir domainden de çalışabilir.
- API Key, tarayıcının `localStorage`'ında saklanır; sayfa yenilense bile korunur.

---

## 16. Çalıştırma kılavuzu

### Mod 1 — Sıfır altyapı (en kolay)
Redis/Celery KURMADAN tüm pipeline'ı **senkron** çalıştırır (öğrenmek için ideal):
```bash
pip install -r requirements.txt
python run_local.py --pages 2
```
Çıktıda dedup backend'ini, çekilen kitapları ve toplam sayıyı görürsün; SQLite'a yazar.

### Mod 2 — Tam dağıtık (Docker)
```bash
docker compose up --build
```
Sonra:
```bash
curl -X POST localhost:8000/scrape -H "Content-Type: application/json" \
     -d '{"max_pages": 5, "chunk_size": 10}'
curl localhost:8000/stats
# Flower: http://localhost:5555
```

### Mod 3 — Manuel dağıtık (Docker olmadan, ayrı terminaller)
```bash
docker run -p 6379:6379 redis/redis-stack:latest                                   # 1) Redis Stack
celery -A workers.celery_app.celery_app worker --loglevel=info --concurrency=4     # 2) Worker
uvicorn app.main:app --reload                                                      # 3) API
celery -A workers.celery_app.celery_app flower --port=5555                         # 4) (ops.) Flower
```

---

## 17. Test stratejisi

```bash
pytest -q
```

`tests/conftest.py` testleri **izole** eder: gerçek `scrapehub.db` yerine **geçici** bir
SQLite dosyası kullanır ve dedup'ı **memory** backend'ine zorlar (gerçek Redis gerektirmez).
Her test öncesi tablolar sıfırlanır.

| Test dosyası | Neyi kanıtlar |
|--------------|---------------|
| `test_parser.py` | HTML'den doğru `Book` çıkarımı + JSON-LD/meta/regex fallback'leri |
| `test_dedup.py` | İlk görüş `False`, ikinci görüş `True`; URL normalizasyonu |
| `test_db.py` | Aynı URL iki kez upsert → tek satır (duplicate yok), alanlar güncellenir |
| `test_discover.py` | Chunk dağıtımı (eager mod): 5 kitap → 3 chunk → hepsi DB'de; per-url fallback |
| `test_incremental.py` | Domain-bazlı gecikme + `content_changed` (yeni→aynı→değişti) |
| `test_deadletter.py` | Fetch hatası `FetchError` fırlatır; `on_failure` dead-letter'a yazar |
| `test_main.py` | API endpoint'leri (frontend, stats, books, health, metrics, yetkilendirme) |

Ayrıca `tests/verify_bloom.py` (test değil, elle çalıştırılır): **canlı** bir Redis Stack'e
karşı `backend == "redis-bloom"` ve `BF.ADD/EXISTS` davranışını kanıtlar:
```bash
REDIS_URL=redis://localhost:6379/0 python tests/verify_bloom.py
```

---

## 18. Konfigürasyon

Tüm ayarlar `core/config.py`'da toplanır; her biri bir env değişkeninden okunur ve makul bir
default'a sahiptir (hiçbir şey ayarlamadan çalışır).

| Değişken | Default | Açıklama |
|----------|---------|----------|
| `SCRAPE_BASE_URL` | `https://books.toscrape.com/` | Hedef site |
| `REDIS_URL` | `redis://localhost:6379/0` | Kuyruk + Bloom filter |
| `DATABASE_URL` | `sqlite:///scrapehub.db` | Postgres'e çevrilebilir |
| `REQUEST_DELAY` | `0.5` | İstekler arası saniye (genel default nezaket gecikmesi) |
| `DOMAIN_DELAYS` | (boş) | Domain-bazlı gecikme: `domain:sn,domain:sn` |
| `MAX_CONCURRENCY` | `4` | Eşzamanlı istek / worker rate limit tabanı |
| `REQUEST_TIMEOUT` | `20` | İstek zaman aşımı (sn) |
| `MAX_RETRIES` | `3` | Maksimum yeniden deneme |
| `RESPECT_ROBOTS` | `true` | robots.txt'e uy |
| `DEDUP_TTL` | `86400` | Memory dedup TTL (sn) |
| `BLOOM_CAPACITY` | `1000000` | Bloom filter kapasitesi |
| `BLOOM_ERROR_RATE` | `0.001` | Bloom yanlış-pozitif oranı |
| `INCREMENTAL` | `false` | `true` → içerik değiştiyse yeniden işle |
| `CONTENT_HASH_TTL` | `604800` | Incremental içerik hash saklama süresi (sn) |

`POST /scrape` gövdesi: `start_url`, `max_pages`, `chunk_size`.

---

## 19. Sık sorulan sorular

**S: Neden LLM parser kaldırıldı?**
C: API anahtarı/maliyet gerektiriyordu ve deterministik değildi. Yerine gelen çok kademeli
(JSON-LD → CSS → regex) parser, çoğu gerçek sitede LLM kadar dayanıklıdır ve **bedavadır**.

**S: Bloom filter yanlış-pozitif verirse veri kaybeder miyim?**
C: Çok nadiren bir sayfayı "gördüm" sanıp atlayabilir (oran ayarlanabilir, default %0.1).
Kritik veride bu kabul edilebilir bir takastır; istersen `BLOOM_ERROR_RATE`'i düşürürsün.

**S: Redis olmadan çalışır mı?**
C: Evet. Dedup memory'e, DB SQLite'a düşer. `python run_local.py` ile sıfır altyapıda çalışır.
Dağıtık mod (Celery) için Redis gerekir.

**S: Başka bir siteyi kazıyabilir miyim?**
C: Teknik olarak `SCRAPE_BASE_URL`'i değiştirmen yeter. Ama **önce** o sitenin kullanım
şartlarını, robots.txt'ini ve yasal durumu kontrol et ([Bölüm 19](#19-etik-ve-yasal)).

**S: `chunk_size` kaç olmalı?**
C: Küçük demolarda 1 (per-url, izlemesi kolay). Büyük ölçekte 10–50 arası iyi bir başlangıç;
çok büyük olursa bir chunk uzun sürer ve paralellik düşer.

---

## 20. Etik ve yasal

- Hedef site (books.toscrape.com) scraping pratiği için **kasıtla** yayınlanmıştır.
- `core/fetcher.py` **robots.txt'e saygı** duyar ve **nezaket gecikmesi** uygular.
- Başka bir siteye yönlendirirken: kullanım şartlarını, robots.txt'i ve ilgili veri koruma
  mevzuatını (ör. **KVKK/GDPR**) kontrol et. **Anti-bot savunması olan sitelerde izinsiz
  kullanma.** Bu proje, izin veren hedeflerde doğru mühendisliği öğretmek içindir; izinsiz
  scraping veya savunma atlatma için değildir.
