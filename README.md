# OZAK POWER — DC/DC Modül Test Bench

Beş röle yuvasına takılan izole DC/DC dönüştürücüleri sırayla test eden, ölçümleri tarayıcıya aktaran ve Excel/CSV raporları üreten Python tabanlı test sistemi.

Sistem; UNI-T UDP6731 güç kaynağını, UNI-T UTL8511 elektronik yükü ve Arduino Uno röle seçicisini koordine eder. Aynı arayüzde donanımdan bağımsız simülasyon ve katalog karşılaştırmalı verimlilik grafikleri bulunur.

## İçindekiler

- [Kurulum ve çalıştırma](#kurulum-ve-çalıştırma)
- [Donanım ve yuva düzeni](#donanım-ve-yuva-düzeni)
- [Arayüz ve çalışma modları](#arayüz-ve-çalışma-modları)
- [Modül belirleme](#modül-belirleme)
- [Otomatik test prosedürü](#otomatik-test-prosedürü)
- [Güç ve akım sınırları](#güç-ve-akım-sınırları)
- [Verimlilik eğrisi](#verimlilik-eğrisi)
- [Ölçüm ve regulation hesapları](#ölçüm-ve-regulation-hesapları)
- [Excel ve CSV raporları](#excel-ve-csv-raporları)
- [Kalibrasyon](#kalibrasyon)
- [Kod mimarisi](#kod-mimarisi)
- [API](#api)
- [Sorun giderme ve mevcut sınırlar](#sorun-giderme-ve-mevcut-sınırlar)

## Kurulum ve çalıştırma

### Gereksinimler

- Python 3.10 veya üzeri; kodda `X | None` tür gösterimi kullanılır.
- `requirements.txt`: FastAPI, Uvicorn, WebSockets, pyserial, Pydantic 2 ve openpyxl.
- Gerçek test için güç kaynağı, elektronik yük, Arduino ve seri/USB bağlantıları.
- Modern bir tarayıcı. Ayrı Node.js derleme aşaması yoktur.

Proje klasöründe PowerShell açın:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Arayüz: **http://localhost:8000**

Paketler kullandığınız Python'a kuruluysa `python main.py` veya `run.bat` kullanılabilir. `run.bat`, PATH üzerindeki `python` komutunu kullanır; sanal ortam kullanıyorsanız önce ortamı etkinleştirin veya yukarıdaki tam yolu kullanın.

Sunucuyu terminalde `Ctrl+C` ile durdurabilirsiniz. Enerjili bir test varsa önce **ACİL STOP** kullanın. Sunucu `reload=False` ile açılır; Python değişiklikleri yeniden başlatma, HTML/JavaScript değişiklikleri genellikle `Ctrl+F5` gerektirir.

### Yapılandırma

[backend/config.py](backend/config.py) içindeki varsayılanlar:

| Ayar | Değer | Anlamı |
|---|---|---|
| `HOST` | `0.0.0.0` | Dinlenen ağ arayüzü |
| `PORT` | `8000` | HTTP / WebSocket portu |
| `PSU_PORT` | `COM16` | UDP6731 portu |
| `UTL_PORT` | `COM11` | UTL8511 portu |
| `RELAY_PORT` | `COM14` | Arduino portu |
| Baud hızları | `9600` | Seri iletişim hızları |
| `SAMPLE_INTERVAL_SEC` | `0.250` | Normal telemetri döngüsünün bekleme aralığı |
| `PSU_TEST_CURRENT_LIMIT_A` | `12.0` | Üst giriş akımı sınırı |
| `LOAD_TEST_MAX_CURRENT_A` | `30.0` | Üst yük akımı sınırı |
| `INITIAL_MODE` | `HARDWARE` | Başlangıç modu |

COM numaraları bilgisayara ve USB bağlantısına göre değişir:

```powershell
python -m serial.tools.list_ports -v
```

`/api/ports/ensure`, cihaz kimliklerini doğrular ve gerekirse yeniden arar. Çalışma anındaki port seçimi ile başlangıç dosyası ayrıdır; kalıcı değişiklikte `config.py` dosyasını da güncelleyin. Arduino portu PSU ve yük için kullanılmaz.

Arayüzün Tailwind stil betiği dış bir adresten yüklenir. Tam çevrimdışı kullanımda bu kaynağın da yerel olarak sağlanması gerekir.

## Donanım ve yuva düzeni

```text
                  Arduino Uno
                  röle seçici
                       |
UDP6731 PSU ---> seçilen DC/DC modülü ---> UTL8511 elektronik yük
     |                                         |
     +-------------- Python sunucusu -----------+
                            |
                       WebSocket
                            |
                       Web arayüzü
```

Bench ve ekran yerleşimi:

```text
     [ YUVA 5 ]          [ YUVA 4 ]

                [ YUVA 3 ]

     [ YUVA 1 ]          [ YUVA 2 ]
```

| Yuva | Konum | Arduino pini | Seri maske |
|---|---|---|---|
| 1 | Sol alt | D2 | `10000` |
| 2 | Sağ alt | D3 | `01000` |
| 3 | Orta | D4 | `00100` |
| 4 | Sağ üst | D5 | `00010` |
| 5 | Sol üst | D6 | `00001` |
| Tümü kapalı | — | — | `00000` |

### Arduino yazılımı

[arduino/relay_selector/relay_selector.ino](arduino/relay_selector/relay_selector.ino) dosyasını Uno'ya yükleyin. Arduino IDE veya [platformio.ini](platformio.ini) yapılandırmasını kullanabilirsiniz.

- 9600 baud; beş bitlik maske ve satır sonu `\n` gönderilir.
- Başarılı yanıt, gönderilen maskeyi içerir: örneğin `OK 00100`.
- Birden çok yuva seçen maske reddedilir ve röleler kapatılır.
- Firmware başlangıçta tüm röleleri kapatır; yuva değişiminde önce önceki röleleri bırakır.
- `RELAY_ACTIVE_HIGH = true` varsayılandır. Aktif düşük kartta `false` yapın.
- Python röle değiştirmeden önce PSU'yu kapatır. Görsel vurgu, seçim listesini değil onaylanan aktif yuvayı izler.

## Arayüz ve çalışma modları

### Test modu

Gerçek cihazları kullanır. PSU bağlantısı kurulurken çıkış kapatılır. Gerilim ayarlamak tek başına çıkışı açmaz; açma komutu ayrıca gönderilir.

### Simülasyon modu

Üstteki **Simülasyon / Test** düğmesiyle seçilir. `ConverterSimulator`, sanal giriş/çıkış ve kayıp değerleri üretir. Normal simülasyon telemetrisi ve manuel simülasyon kontrolleri gerçek PSU/yük okumalarını veya çıkış komutlarını kullanmaz.

Donanımdan simülasyona geçişte bağlı çıkışlar ve seçili röle kapatılır. Test/kalibrasyon sürerken mod değiştirilemez. Donanıma dönüşte çıkışlar kapalı tutulur. Simülasyonda sayısal göstergeler yaklaşık 300 ms'lik yumuşak geçişlerle güncellenir; test modundaki ölçümlere görsel ara değer eklenmez.

Otomatik donanım testleri ve modül belirlemeli verimlilik taraması `HARDWARE` modu gerektirir. Simülasyon bu üretim testlerinin fiziksel doğrulaması değildir.

### Kontroller

| Kontrol | İşlev |
|---|---|
| `YUVA` | Manuel açma ve tek yuva testi için seçim. Listeyi değiştirmek enerjili röleyi anında değiştirmez. |
| `GÜÇ (W)` | START TEST / TEST YUVA için 20, 50, 100 veya 300 W ailesi. |
| `GİRİŞ` | Manuel açılışta yük/PSU'yu kapatır, seçili röleyi onaylatır, akım sınırını ayarlar ve **24 V** açar. |
| `ÇIKIŞ` | Elektronik yük girişini açar/kapatır. Akım için hedef de sıfırdan büyük olmalıdır. |
| Akım sürgüsü ve ± butonları | Manuel CC yük hedefini amper cinsinden değiştirir. |
| `START TEST` | Beş yuvada sırayla belirleme ve performans testi. |
| `TEST YUVA` | Seçilen tek yuvada aynı belirleme ve altı noktalı prosedür. |
| `ACİL STOP` | PSU/yükü kapatır, yükü sıfırlar, röleleri bırakır ve testi iptal eder. Yeniden açmayı kilitler; yeni test akışı kilidi temizleyebilir. |
| Kalibrasyon ayarları | Normalde kapalı, gerektiğinde açılan panel. |

Manuel akışta GİRİŞ ve ÇIKIŞ'ın ikisi de kapandığında röle bırakılır. Test/kalibrasyonun kontrol ettiği röleler kendi akışları tarafından yönetilir.

Yuva renkleri:

- **Turkuaz:** Test ediliyor veya sonuç yokken röle seçili.
- **Yeşil:** Çalışan / başarılı sonuç.
- **Kırmızı:** Boş/çalışmayan yuva veya başarısız performans noktası.
- **Sarı:** Belirsiz sonuç veya donanım kapasitesi nedeniyle tamamlanamayan tam yük testi.

Renkler tarayıcı belleğinde tutulur; yeni ilgili test veya sayfa yenileme bunları temizleyebilir. Kalıcı kayıt için raporu saklayın. Vitrin görünümü kullanıcı tarafından açılır; otomatik üretim testi değildir.

## Modül belirleme

Operatör watt ailesini belirtir; yazılım o aile içinde giriş aralığı ve çıkış geriliminden katalog modeli tahmin eder.

1. PSU kapatılır; yük kapatılıp sıfırlanır ve yalnızca hedef röle seçilir.
2. Modül önce **10 V**, sonra **24 V** ile, her noktada **50 mA** prob yüküyle ölçülür.
3. Her noktada önce modül yüksüz başlatılır; sonra prob akımı ayarlanıp yük açılır.
4. Akım ayarı `:CURR?`, açık/kapalı durum `:INP?` ile geri okunur. Gönderim/geri okuma başarısızsa işlem durur.
5. Üç örneğin medyanı alınır. Giriş toleransı `max(1 V, hedefin %10'u)`; çıkış varlığı eşiği **2,5 V**'tur. Çalışma için en az **25 mA** prob akımı doğrulanır.
6. 10 V'ta çalışan aday için 24 V nominal / 9–36 V ailesi değerlendirilir. 10 V giriş doğrulanmasına rağmen çıkış vermeyip 24 V'ta çalışan aday için 48 V nominal / 18–72 V ailesi değerlendirilir.
7. Katalog çıkışına `max(0,5 V, katalog değerinin %5'i)` toleransında bakılır. Tek eşleşme yoksa yüksek yüklü performans matrisi çalıştırılmaz.

10 V'ta çalışmayan ama 24 V'ta çalışan modül sırf 10 V sonucuyla arızalı sayılmaz. Giriş doğrulanamaması veya çıkış olup prob akımının oluşmaması belirsiz kabul edilir.

Bu işlem dijital kimlik okuma değildir. Aynı gerilim özelliklerine sahip modeller ayırt edilemeyebilir. Watt değeri bağımsız ölçülmez; yanlış aile yanlış eşleşmeye yol açabilir. Üretimde watt seçimi takılan modülle uyumlu olmalıdır.

## Otomatik test prosedürü

Model tek bir katalog adayıyla eşleşince her yuva için **altı performans noktası** alınır:

| PSU giriş noktası | Elektronik yük koşulları |
|---|---|
| Katalog minimum giriş | No load / yüksüz + full load / tam yük |
| Katalog nominal giriş | No load / yüksüz + full load / tam yük |
| Katalog maksimum giriş | No load / yüksüz + full load / tam yük |

**No load:** Hedef 0 A ve elektronik yük girişi kapalıdır. Sıfır ayarı ve kapalı giriş durumu geri okunur.

**Full load:** `min(katalog Imax, katalog güç / katalog çıkış gerilimi)` hedefi 1 mA çözünürlüğe aşağı yuvarlanır. Aynı akım üç girişte korunur. PSU/yük kapasitesi yetmezse nokta `skipped` olur; daha düşük yük “%100” diye raporlanmaz.

Bir noktanın geçmesi için giriş doğrulanmalı; çıkış gerilimi katalogdan `max(0,1 V, %5)` içinde olmalıdır. Tam yük akım farkı `max(5 mA, hedefin %5'i)` içinde; yüksüz akım ise en fazla 10 mA olmalıdır.

Testte normal telemetri okuyucusu duraklatılır ve seri portların paralel okunması engellenir. Test örnekleri WebSocket'e gönderilir; uzun oturma beklemelerinde de ölçüm/yayın sürer. İşlem sonunda PSU kapatılır ve röle yolları açılır.

## Güç ve akım sınırları

Giriş gücü bütçesi katalog çıkış gücünün **%150'sidir**:

```text
Pin_budget = 1,5 × Pnom
Iin_limit = min(12 A, Pin_budget / Vin_setpoint)
```

Akım sınırı 1 mA çözünürlüğe aşağı yuvarlanır. 20 W modülün bütçesi 30 W'tır:

| PSU gerilimi | Akım sınırı |
|---|---|
| 10 V | 3 A |
| 24 V | 1,25 A |
| 36 V | 0,833 A |

Modülün sürekli 30 W tüketmesi sağlanmaz. PSU'ya sabit güç modu değil seçilen gerilime göre **akım sınırı** programlanır. Gerçek güç, gerçek gerilim ve modül/yük davranışına bağlıdır.

Manuel açmada hesap üstteki katalog modeline; otomatik testte operatörün watt ailesi ve eşleşen modele dayanır. Yanlış yüksek watt seçimi elektriksel ölçümlerle kesin saptanamaz.

## Verimlilik eğrisi

Bu bölüm altı noktalı START TEST matrisinden ayrı bir güç taramasıdır.

1. Bölümün kendi **YUVA** ve **MODÜL GÜCÜ (W)** alanlarını seçin.
2. Başlangıç/bitiş/adım varsayılanı **5 / 20 / 5 W**'tır.
3. Önce yalnızca seçilen yuvada 10 V / 24 V belirleme yapılır; bu aşamada tam yük matrisi tekrarlanmaz.
4. Tek model eşleşince nominal giriş ve sınırlar katalogdan alınır. Model ve yuva grafik üstünde gösterilir.
5. Varsayılan çıkış hedefleri **5 → 10 → 15 → 20 W**'tır. Bitiş hedefi katalog gücü/akımıyla sınırlanır.
6. Her adımda ölçülen çıkıştan `I_target = P_target / Vout_measured` hesaplanıp CC akım komutu gönderilir. Bu sürekli geri beslemeli sabit güç modu değildir; gerçekleşen güç ayrıca ölçülür.
7. En az 5 saniye oturma, yakınsama ve çoklu örnekleme yapılır. Beş verim örneğinin en düşük/en yüksek olanı ayıklanıp kalanlar ortalanır.
8. Çıkış nominalin %85'inin altına düşerse, akım kapasitesi aşılırsa veya ölçülen giriş gücü %150 bütçesini aşarsa tarama durur.

X ekseni çıkış gücü, Y ekseni verimdir. Kırmızı kesikli çizgi bulunan modelin katalog tipik verimidir; bir sertifikasyon limiti değildir. Grafik yüksekliği sabittir, sonuç tablosu kendi içinde kayar. CSV raporu bu bölümden indirilir.

## Ölçüm ve regulation hesapları

### Güç ve verim

```text
Pin       = giriş kanallarında Σ(V × I)
Pout      = Vout × Iout
Verim (%) = 100 × Pout / Pin
Kayıp (W) = max(0, Pin − Pout)
```

Normal telemetride verim `Pin > 0,5 W` ve `Iout > 50 mA` olduğunda gösterilir, aksi durumda 0'dır. Görsel verim 0–100% arasında sınırlanır. Prob/yüksüz ölçümünde 0% tek başına arıza değildir. Verimlilik taraması kendi ortalama güçlerinden ayrıca verim hesaplar.

Termal sınıflar sıcaklık sensöründen gelmez; hesaplanan güç kaybına dayalı görsel göstergelerdir.

### Load regulation

Her giriş noktasındaki yüksüz/tam yük farkı:

```text
ΔVload = abs(Vout_no_load − Vout_full_load)
Load regulation (%) = 100 × ΔVload / Vout_catalog_nominal
```

Minimum, nominal ve maksimum giriş için ayrı üç sonuç üretilir.

### Line regulation

Aynı yükte üç giriş noktasındaki çıkış gerilimlerinin aralığı:

```text
ΔVline = max(Vout_minVin, Vout_nomVin, Vout_maxVin)
         − min(Vout_minVin, Vout_nomVin, Vout_maxVin)
Line regulation (%) = 100 × ΔVline / Vout_catalog_nominal
```

Yüksüz/tam yük için ayrı iki sonuç vardır. Yüzdelerin paydası katalog nominal çıkışıdır; farklı veri sayfalarıyla karşılaştırırken tanımların aynı olduğuna bakın.

Giriş/yük koşulu doğrulanmamış veya tam yük noktası atlanmışsa sonuç **boş** kalır; sıfır regülasyon yazılmaz. Uygun çift çıkışlı modellerde raylar arası toplam gerilim `catalog_output_span_v()` ile eşleştirme ve referansta kullanılır.

## Excel ve CSV raporları

### Modül testi: ZIP içinde XLSX

START TEST tamamlanınca `ozak_power_module_test_results.zip` otomatik indirilir. Her yuva için `slot_<yuva>_<model>.xlsx` içerir:

| Sayfa | İçerik |
|---|---|
| `Summary` | Zaman, watt ailesi, yuva/model, 10/24 V ölçümleri, altı performans noktası, durum ve atlama nedenleri |
| `Raw Samples` | Her noktanın Vin, Iin, Pin, Vout, Iout, Pout, verim örnekleri ve doğrulamaları |
| `Regulation` | Tanımlar, referans gerilim, üç load / iki line regulation sonucu, volt farkı, yüzde ve geçerlilik |

`/api/module/export-excel` bellekteki son raporu dışa aktarır. Tek yuva testi veya verimlilik ön-belirlemesi de bunu değiştirebilir; her rapor beş yuva içermez. Sunucu yeniden başlayınca rapor kaybolur; üretim kayıtlarını ayrıca saklayın.

### Verimlilik taraması: CSV

`/api/sweep/export-csv`; model/katalog hedefi, adım, hedef watt/akım, gerçek güçler, gerilimler, akımlar, verim, kayıp ve kararlılık aralığını içerir. Noktalar `SweepEngine` belleğindedir.

## Kalibrasyon

Varsayılan kapalı panel yuva kablo/PCB gerilim farkını iki farklı yük noktasında modellemek için kullanılır.

1. Yuvayı ve uygun katalog modelini seçin.
2. Düşük yük A ve daha yüksek yük B akımlarını girin.
3. Her noktayı uygulayın; PSU/yük terminal ölçümleri kaydedilir.
4. Multimetreyle doğrudan modül pinlerinden Vin/Vout ölçüp girin.
5. Kaydedin; PSU/yük kapanır ve röle bırakılır. İptal ve 3 dakika hareketsizlik de kapatır.

İki noktalı düzeltme modeli:

```text
Vin_DUT  = Vin_PSU  − (input_offset + Iin × input_resistance)
Vout_DUT = Vout_load + (output_offset + Iout × output_resistance)
```

Profiller `backend/slot_calibrations.json` dosyasında kalıcı tutulur ve bu bench'in yedeği olarak Git deposunda saklanır. Dosyada her yuvanın A/B ham ölçümleri, giriş/çıkış gerilim ofsetleri, eşdeğer kablo/PCB dirençleri ve kalibrasyon zamanı bulunur. Başka bir bench'e kurulumda bu katsayıları doğrudan geçerli kabul etmeyin; o bench'i yeniden kalibre edin. Dosya yoksa boş profille başlanır. Capture akışı seçili katalog modelinin nominal girişini kullanır; paneldeki 24 V açıklaması farklı nominal modeller için sabit bir garanti değildir.

UTL8511 bağlantısında yerel sense seçilir (`set_remote_sense(False)`). Bazı görsel “4-Wire” etiketleri remote sense'in etkin olduğunu kanıtlamaz; fiziksel bağlantı ve cihaz ayarı ayrıca doğrulanır. Tare, küçük pozitif artık akımı ölçümden çıkaran ayrı bir düzeltmedir.

## Kod mimarisi

```text
main.py                       Uvicorn başlangıcı
run.bat                       Windows başlangıcı
requirements.txt              Python bağımlılıkları
platformio.ini                Arduino Uno yapılandırması
backend/
  server.py                   REST, test akışları/kilitler, XLSX/ZIP
  engine.py                   Telemetri, modlar, yayın, kalibrasyon uygulama
  config.py                   Portlar, örnekleme ve üst sınırlar
  dut_catalog.py              Model, güç, gerilim, akım ve verim kataloğu
  math_engine.py              Telemetri şemaları ve hesaplar
  sweep_engine.py             Watt adımlı tarama ve CSV
  simulator.py                Sanal dönüştürücü
  slot_calibration.py         İki noktalı kalibrasyon ve kalıcı profiller
  drivers/base_driver.py      Seri port/SCPI ve sayısal yanıt çözümleme
  hal/utl8511_load.py          Aktif yük sürücüsü, ayar geri okuma
  hal/drivers/unit_udp6731.py  Aktif PSU sürücüsü
  hal/relay_selector.py       Arduino komutları ve onay denetimi
  hal/base_*.py               Donanım arayüzleri
  hal/mock_psu.py             Alternatif mock PSU
frontend/
  index.html                  Sayfa ve paneller
  css/styles.css              Ek stiller
  js/app.js                   API/WebSocket, modlar ve etkileşimler
  js/gauge.js                 Verim kadranı
  js/trend_chart.js           Canlı trend / modül testi gösterimi
  js/sweep_chart.js           Watt–verim grafiği
  js/showcase.js              Kullanıcı tarafından açılan vitrin
  assets/                     Logo ve örnek ekranlar
arduino/relay_selector/
  relay_selector.ino          Beş yuva röle firmware'i
```

Alternatif/eski cihaz sürücüleri de bulunur. Aktif nesneler `TelemetryManager.__init__()` içinde seçilir; her sürücü aynı anda kullanılmaz.

### Veri akışı

1. FastAPI yaşam döngüsü `MANAGER.start()` ile arka plan görevini başlatır.
2. `_telemetry_loop()` cihazları okur veya simülasyon üretir.
3. Yuva kalibrasyonu uygulanır; `MathEngine` güç/verimi hesaplar.
4. `broadcast()`, aktif yuva ve test durumu ekleyip `/ws/telemetry` üzerinden yollar.
5. `app.js` ölçüleri, renkleri, kadranı ve grafikleri günceller.
6. Testte `is_sweep_active` normal döngüyü duraklatır; `acquire_and_broadcast()` test örneklerini yayınlar.

Gerçek yayın aralığı seri sorgu sürelerine de bağlıdır; 250 ms ayarı garantili 4 Hz ölçüm hızı değildir.

## API

Sunucu açıkken **http://localhost:8000/docs** etkileşimli FastAPI şemasını gösterir.

| Yöntem | Yol | İşlev |
|---|---|---|
| GET | `/api/status` | Mod, bağlantılar, çıkışlar ve aktif yuva |
| GET | `/api/ports` | Seri port listesi |
| POST | `/api/ports/ensure` | Cihaz kimliği / yeniden keşif |
| POST | `/api/ports/configure` | Çalışma anındaki port ayarları |
| POST | `/api/mode` | `SIMULATION` / `HARDWARE` |
| GET | `/api/dut/catalog` | Katalog ve aktif model |
| POST | `/api/dut/select` | Model seçimi; testte engellenir |
| POST | `/api/psu/state` | Manuel PSU / yuva açma-kapatma |
| POST | `/api/psu/voltage` | Gerilim ayarı; tek başına açmaz |
| POST | `/api/load/state` | Yük açma/kapatma |
| POST | `/api/load/current` | CC akım hedefi |
| POST | `/api/load/tare` | Akım ofseti düzeltme |
| POST | `/api/module/detect` | Beş yuva belirleme ve performans testi |
| POST | `/api/module/test-slot` | Aynı prosedürün tek yuva sürümü |
| GET | `/api/module/export-excel` | Son raporun XLSX/ZIP çıktısı |
| POST | `/api/sweep/start` | Belirleme ve watt adımlı tarama |
| POST | `/api/sweep/stop` | Tarama iptal/kapatma |
| GET | `/api/sweep/status` | Noktalar, ilerleme ve model |
| GET | `/api/sweep/export-csv` | CSV |
| GET | `/api/telemetry/latest` | Son telemetri karesi |
| POST | `/api/emergency-stop` | Test iptali / çıkış-röle kapatma |
| GET | `/api/calibration/slots` | Kalibrasyon profilleri |
| POST | `/api/calibration/capture` | A/B noktası uygulama |
| POST | `/api/calibration/slot/save` | Kaydetme ve kapatma |
| POST | `/api/calibration/cancel` | Kalibrasyon iptali |
| WS | `/ws/telemetry` | Canlı ölçüm yayını |

Verimlilik taraması gövdesi:

```json
{
  "slot": 3,
  "rated_power_w": 20,
  "start_power_w": 5,
  "end_power_w": 20,
  "step_power_w": 5,
  "dwell_time_sec": 5
}
```

Tek yuva testi gövdesi:

```json
{ "slot": 3, "rated_power_w": 20 }
```

`/api/module/detect` watt ailesini sunucudaki seçili modelden alır. Arayüz START TEST öncesinde watt alanına göre bu aileyi seçer.

Doğrudan SCPI debug ve ek kalibrasyon uçları da vardır. Kimlik doğrulama yoktur; CORS geniş ve varsayılan `HOST` tüm arayüzlerdir. Bu sürüm kontrollü bench ağı içindir; internet yayını veya çok kullanıcılı üretim yetkilendirmesi sağlamaz.

## Sorun giderme ve mevcut sınırlar

| Belirti | Kontrol |
|---|---|
| Sayfa açılmıyor | `main.py` çıktısı, paketler ve 8000 portunu kullanan başka süreç |
| COM yok | USB/adaptör, sürücü, `serial.tools.list_ports` |
| COM var ama yanıt yok | Cihazın açık olması, kimlik-port eşleşmesi, baud, portu kullanan başka program |
| Windows aygıt hatası | USB/adaptörü yeniden bağlayın; numara değiştirmek yeterli olmayabilir |
| GİRİŞ açılmıyor | Arduino onayı, yuva, cihaz bağlantıları, test/kalibrasyon veya acil stop kilidi |
| Yük açık ama akım yok | Hedef akım, modül çıkışı, bağlantı ve 10 V'ta çalışabilme durumu |
| Model belirsiz | Watt ailesi, gerçek çıkış ve birden fazla katalog eşleşmesi |
| Regulation boş | Eksik/atlanan nokta, doğrulanmamış giriş veya oluşmayan yük |
| 300 W test tamamlanmıyor | 30 A yük, düşük Vin'de 12 A PSU sınırı ve gerçek cihaz kapasitesi |
| Verim %0 | Prob/yüksüz gösterim eşiği veya çıkışın kapalı olması |
| Arayüz eski | `Ctrl+F5`; Python değiştiyse sunucuyu yeniden başlatın |

Mevcut sınırlar:

- Seri numarası, operatör kimliği, veritabanı veya kalıcı test geçmişi tutulmaz.
- 3 W modeller katalogda olsa da standart otomatik seçim 20/50/100/300 W'tır. 2,5 V eşiği ve 10/24 V yöntemi bütün dönüştürücüler için genel bir test değildir.
- PSU sürücüsü küçük/eksik akım yanıtında yük gücünden tahmini giriş akımı/gücü üretebilir. Raporlanan verim her durumda bağımsız giriş güç ölçümüne dayanmayabilir. Metrologik doğrulama için fallback kaldırılmalı veya açıkça işaretlenmelidir.
- Görsel sense/termal etiketleri cihaz ayarını veya gerçek sıcaklığı her zaman temsil etmez.
- Regulation yüzdeleri tanımlanan formüllerle hesaplanır; katalog regulation limitine göre ayrı otomatik geçer/kalır kararı verilmez.
- NumPy `requirements.txt` içinde değildir. Ayrıca kuruluysa isteğe bağlı kayıp modeli regresyonu hesaplanabilir; yoksa bu alan boş kalır.
- Depoda kalıcı otomatik test paketi yoktur. Sözdizimi kontrolü gerçek donanım testi değildir:

```powershell
python -m compileall -q main.py backend
```

## Git'e alınmayan yerel dosyalar

`.gitignore`; önbellek, sanal ortam, PlatformIO yerel çekirdeği/derlemeleri, loglar, indirilen raporlar ve geçici kalibrasyon yazma dosyasını dışarıda bırakır. `backend/slot_calibrations.json` ise bu bench'in kalibrasyon yedeği olarak takip edilir; yeni kalibrasyondan sonra değişikliği commit/push ederek yedeği güncelleyin.

### Önbelleklerde ne bulunur?

| Klasör | İçerik | Yeniden üretilebilir mi? |
|---|---|---|
| `__pycache__/`, `backend/**/__pycache__/` | Python'un kaynak modüllerden derlediği `.pyc` bytecode; CPython sürümüne göre ayrı dosyalar | Evet, Python tekrar oluşturur. Kalibrasyon veya test geçmişi değildir. |
| `.pio/build/` | Arduino derleme nesneleri, firmware çıktıları ve derleme ara dosyaları | Evet, firmware derlemesiyle |
| `.platformio-core/.cache/` | PlatformIO indirme/çözümleme önbellekleri | Evet, gerektiğinde indirilir |
| `.platformio-core/packages/` | İndirilen derleyici, framework ve yükleme araçları | Evet, PlatformIO ile |
| `.platformio-core/platforms/` | Platform tanımları ve derleme/yükleme betikleri | Evet, PlatformIO ile |

`.platformio-core/appstate.json` yerel PlatformIO uygulama durumunu tutar. `bench-server.*.log` dosyaları ise önbellek değildir; sunucu çalışma mesajları, hatalar ve cihaz iletişim kayıtlarıdır. Bellekteki son test raporu/ölçüm noktaları da `.pyc` dosyalarına yazılmaz. Bunlar Excel/CSV ile ayrıca dışa aktarılır.
