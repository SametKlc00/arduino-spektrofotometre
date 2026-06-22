// =======================================================
// ARDUINO TABANLI SPEKTROFOTOMETRE FINAL INO KODU
// Sensör: TSL2591 dijital ışık sensörü
// Web Panel: Python / Flask app.py ile uyumlu
//
// Bu kodun görevi:
// 1. TSL2591 sensöründen görünür ışık değerini okumak
// 2. Dark ve Blank referanslarını komutla güncellemek
// 3. Transmittance ve Absorbance hesaplamak
// 4. Sonuçları seri porttan Flask web paneline göndermek
//
// Web panelden gelen komutlar:
// SET_DARK   : Işık kapalı + kutu kapalı iken darkRaw alır
// SET_BLANK  : Işık açık + kör/blank küvet varken blankRaw alır
// GET_REF    : Mevcut darkRaw ve blankRaw değerlerini gönderir
// RESET_AVG  : Ortalama hesaplama tamponunu sıfırlar
// =======================================================


// I2C haberleşmesi için gerekli kütüphane.
// TSL2591 sensörü Arduino UNO'da SDA=A4, SCL=A5 üzerinden haberleşir.
#include <Wire.h>

// Adafruit sensör altyapısı için kullanılan genel sensör kütüphanesi.
#include <Adafruit_Sensor.h>

// TSL2591 dijital ışık sensörünü kullanmak için gerekli kütüphane.
#include <Adafruit_TSL2591.h>

// log10() fonksiyonunu kullanmak için matematik kütüphanesi.
#include <math.h>


// TSL2591 sensör nesnesi oluşturulur.
// 2591 burada sensör ID değeri gibi kullanılır.
Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);


// =======================================================
// ÖLÇÜM AYARLARI
// =======================================================

// Ortalama almak için kaç ölçüm yapılacağını belirler.
// 10 ölçüm alınır, ortalaması hesaplanır ve web panele gönderilir.
const int sampleCount = 10;

// Dark veya blank alma sırasında kaç ölçüm alınacağını belirler.
// Daha yüksek sayı daha kararlı referans sağlar.
const int calibrationSampleCount = 20;

// Normal ölçümler arasında bekleme süresi.
// 200 ms x 10 ölçüm = yaklaşık 2 saniyede bir DATA gönderilir.
const int sampleDelayMs = 200;

// Dark/blank kalibrasyon ölçümleri arasındaki bekleme süresi.
const int calibrationDelayMs = 100;


// =======================================================
// REFERANS DEĞERLER
// =======================================================

// Dark Raw:
// Işık kapalı + kutu kapalı iken sensörün okuduğu taban değerdir.
// Web panelden SET_DARK komutu ile güncellenir.
float darkRaw = 0.7;

// Blank Raw:
// Işık açık + kör/blank küvet + kutu kapalı iken sensörün okuduğu referans değerdir.
// Başlangıçta eski ölçüm değeri yazılıdır.
// Web panelden SET_BLANK komutu ile güncellenir.
float blankRaw = 965.0;


// =======================================================
// ANLIK ÖLÇÜM DEĞİŞKENLERİ
// =======================================================

// Sensörden okunan anlık görünür ışık değeri.
float rawValue = 0.0;

// Anlık transmittance/geçirgenlik değeri.
// Hesaplamada 0-1 arasıdır, gönderirken yüzdeye çevrilir.
float transmittance = 0.0;

// Anlık absorbans değeri.
float absorbance = 0.0;


// =======================================================
// ORTALAMA HESAPLAMA DEĞİŞKENLERİ
// =======================================================

// Ortalama Raw Visible için toplam değer.
float totalRaw = 0.0;

// Ortalama transmittance için toplam değer.
float totalTransmittance = 0.0;

// Ortalama absorbance için toplam değer.
float totalAbsorbance = 0.0;

// Kaç ölçüm alındığını takip eden sayaç.
int readIndex = 0;

// Ortalama Raw Visible değeri.
float averageRaw = 0.0;

// Ortalama Transmittance değeri.
float averageTransmittance = 0.0;

// Ortalama Absorbance değeri.
float averageAbsorbance = 0.0;


// =======================================================
// KALİBRASYON DURUM BİLGİLERİ
// =======================================================

// Dark alma işleminin yapılıp yapılmadığını takip eder.
bool darkCalibrated = false;

// Blank alma işleminin yapılıp yapılmadığını takip eder.
bool blankCalibrated = false;


// =======================================================
// SETUP FONKSİYONU
// Arduino ilk açıldığında yalnızca bir kez çalışır.
// =======================================================
void setup() {

  // Seri haberleşme başlatılır.
  // Python/Flask tarafında da baud 9600 olmalıdır.
  Serial.begin(9600);

  // Seri portun oturması için kısa bekleme yapılır.
  delay(1000);

  // TSL2591 sensörü başlatılır.
  // Sensör bulunamazsa hata mesajı verilir.
  if (!tsl.begin()) {

    // Web panel bu hatayı okuyabilir.
    Serial.println("ERROR,TSL2591_NOT_FOUND");

    // Sensör bulunamazsa sistem burada durur.
    while (1) {
      delay(1000);
    }
  }

  // Sensör düşük kazanca alınır.
  // Güçlü ışıkta doygunluğu azaltır.
  tsl.setGain(TSL2591_GAIN_LOW);

  // Ölçüm süresi 100 ms yapılır.
  // Kısa entegrasyon daha hızlı tepki verir.
  tsl.setTiming(TSL2591_INTEGRATIONTIME_100MS);

  // Arduino'nun hazır olduğunu web panele bildirir.
  Serial.println("READY,TSL2591_OK");

  // Başlangıç dark ve blank değerleri web panele / Serial Monitor'e gönderilir.
  Serial.print("STATUS,REF,DARK=");
  Serial.print(darkRaw, 2);
  Serial.print(",BLANK=");
  Serial.println(blankRaw, 2);
}


// =======================================================
// LOOP FONKSİYONU
// Arduino açık kaldığı sürece sürekli çalışır.
// =======================================================
void loop() {

  // Web panelden veya Serial Monitor'den komut gelmiş mi kontrol eder.
  // SET_DARK, SET_BLANK, GET_REF, RESET_AVG komutları burada işlenir.
  handleSerialCommands();

  // TSL2591 sensöründen anlık görünür ışık değeri okunur.
  rawValue = readVisibleValue();

  // Kör/blank referansından dark değeri çıkarılır.
  // Böylece referans ışık değeri elde edilir.
  float I_blank = blankRaw - darkRaw;

  // Numune ölçümünden dark değeri çıkarılır.
  // Böylece numuneden geçen net ışık değeri elde edilir.
  float I_sample = rawValue - darkRaw;

  // Blank referansı geçersizse hesaplama yapılamaz.
  // Örneğin blankRaw darkRaw'dan küçük/eşitse bu hata oluşur.
  if (I_blank <= 0.0001) {
    Serial.println("ERROR,INVALID_REFERENCE");
    delay(1000);
    return;
  }

  // Numuneden geçen ışık sıfırdan küçük çıkarsa çok küçük değere sabitlenir.
  // Bu işlem log10 hesabında matematiksel hata oluşmasını engeller.
  if (I_sample < 0.0001) {
    I_sample = 0.0001;
  }

  // Transmittance hesaplanır.
  // T = I_sample / I_blank
  // Yani numuneden geçen ışığın körden geçen ışığa oranıdır.
  transmittance = I_sample / I_blank;

  // Transmittance çok küçükse minimum değere sabitlenir.
  // Böylece absorbans sonsuza gitmez.
  if (transmittance < 0.0001) {
    transmittance = 0.0001;
  }

  // Transmittance 1'den büyükse 1'e sabitlenir.
  // Çünkü numune teorik olarak körden daha fazla ışık geçirirse absorbans negatif çıkabilir.
  if (transmittance > 1.0) {
    transmittance = 1.0;
  }

  // Absorbans hesaplanır.
  // A = -log10(T)
  // T azalırsa absorbans artar.
  absorbance = -log10(transmittance);

  // Ortalama hesaplamak için anlık Raw değeri toplam değere eklenir.
  totalRaw += rawValue;

  // Ortalama hesaplamak için anlık transmittance toplam değere eklenir.
  totalTransmittance += transmittance;

  // Ortalama hesaplamak için anlık absorbans toplam değere eklenir.
  totalAbsorbance += absorbance;

  // Ölçüm sayacı 1 artırılır.
  readIndex++;

  // Bir sonraki ölçümden önce kısa bekleme yapılır.
  delay(sampleDelayMs);

  // Belirlenen ölçüm sayısına ulaşıldığında ortalama hesaplanır.
  if (readIndex >= sampleCount) {

    // Ortalama Raw Visible hesaplanır.
    averageRaw = totalRaw / sampleCount;

    // Ortalama Transmittance hesaplanır.
    averageTransmittance = totalTransmittance / sampleCount;

    // Ortalama Absorbance hesaplanır.
    averageAbsorbance = totalAbsorbance / sampleCount;

    // Flask web panelin okuyacağı veri satırı gönderilir.
    // Son app.py hem 5 alanlı hem de 7 alanlı DATA formatını destekliyor.
    //
    // Format:
    // DATA,AverageRaw,AverageTransmittancePercent,Absorbance,AverageAbsorbance,DarkRaw,BlankRaw
    //
    // Örnek:
    // DATA,55.70,5.70,1.2415,1.2439,0.70,379.70
    Serial.print("DATA,");

    // Ortalama ham görünür ışık değeri gönderilir.
    Serial.print(averageRaw, 2);
    Serial.print(",");

    // Ortalama transmittance yüzde olarak gönderilir.
    Serial.print(averageTransmittance * 100.0, 2);
    Serial.print(",");

    // Son hesaplanan anlık absorbans gönderilir.
    Serial.print(absorbance, 4);
    Serial.print(",");

    // Ortalama absorbans gönderilir.
    Serial.print(averageAbsorbance, 4);
    Serial.print(",");

    // Mevcut darkRaw değeri gönderilir.
    Serial.print(darkRaw, 2);
    Serial.print(",");

    // Mevcut blankRaw değeri gönderilir.
    Serial.println(blankRaw, 2);

    // Ortalama hesaplama toplamları sıfırlanır.
    totalRaw = 0.0;

    // Transmittance toplamı sıfırlanır.
    totalTransmittance = 0.0;

    // Absorbance toplamı sıfırlanır.
    totalAbsorbance = 0.0;

    // Ölçüm sayacı sıfırlanır.
    readIndex = 0;
  }
}


// =======================================================
// GÖRÜNÜR IŞIK OKUMA FONKSİYONU
// TSL2591 sensöründen full ve IR değerlerini alır.
// Görünür ışık = full - IR olarak hesaplanır.
// =======================================================
float readVisibleValue() {

  // Sensörden 32 bit toplam luminosity değeri alınır.
  uint32_t lum = tsl.getFullLuminosity();

  // Üst 16 bit IR yani kızılötesi değeridir.
  uint16_t ir = lum >> 16;

  // Alt 16 bit full spectrum yani toplam ışık değeridir.
  uint16_t full = lum & 0xFFFF;

  // Görünür ışık değeri hesaplanır.
  float visible = (float)full - (float)ir;

  // Eğer hesaplama negatif çıkarsa sıfıra çekilir.
  if (visible < 0) {
    visible = 0;
  }

  // Görünür ışık değeri geri döndürülür.
  return visible;
}


// =======================================================
// ORTALAMA GÖRÜNÜR IŞIK OKUMA FONKSİYONU
// Dark ve blank alma sırasında kullanılır.
// Birden fazla okuma yapıp ortalamasını döndürür.
// =======================================================
float readAverageVisible(int count) {

  // Okunan değerlerin toplamı.
  float sum = 0.0;

  // İstenen ölçüm sayısı kadar döngü çalışır.
  for (int i = 0; i < count; i++) {

    // Görünür ışık değeri okunup toplam değere eklenir.
    sum += readVisibleValue();

    // Ölçümler arasında kısa bekleme yapılır.
    delay(calibrationDelayMs);
  }

  // Ortalama değer hesaplanır.
  float avg = sum / count;

  // Ortalama değer döndürülür.
  return avg;
}


// =======================================================
// SERİ PORT KOMUTLARINI İŞLEYEN FONKSİYON
// Web panel Arduino'ya komutları seri porttan gönderir.
// Bu fonksiyon o komutları okuyup gerekli işlemi yapar.
// =======================================================
void handleSerialCommands() {

  // Seri portta veri yoksa fonksiyondan çıkılır.
  if (!Serial.available()) {
    return;
  }

  // Satır sonuna kadar gelen komut okunur.
  String command = Serial.readStringUntil('\n');

  // Komutun başındaki ve sonundaki boşluklar temizlenir.
  command.trim();

  // Komut büyük harfe çevrilir.
  // Böylece set_blank veya SET_BLANK yazılması fark etmez.
  command.toUpperCase();

  // -------------------------------------------------------
  // SET_DARK KOMUTU
  // Işık kapalı + kutu kapalı durumdayken kullanılmalıdır.
  // -------------------------------------------------------
  if (command == "SET_DARK") {

    // Önce ortalama tamponları sıfırlanır.
    resetAverages();

    // O anki karanlık değeri çoklu ölçümle alınır.
    darkRaw = readAverageVisible(calibrationSampleCount);

    // Dark kalibrasyon yapıldı bilgisi tutulur.
    darkCalibrated = true;

    // Web panele yeni dark değeri bildirilir.
    Serial.print("STATUS,DARK_SET,");
    Serial.println(darkRaw, 2);
  }

  // -------------------------------------------------------
  // SET_BLANK KOMUTU
  // Işık açık + kör/blank küvet takılı + kutu kapalı durumdayken kullanılmalıdır.
  // -------------------------------------------------------
  else if (command == "SET_BLANK") {

    // Önce ortalama tamponları sıfırlanır.
    resetAverages();

    // O anki blank değeri çoklu ölçümle alınır.
    blankRaw = readAverageVisible(calibrationSampleCount);

    // Blank kalibrasyon yapıldı bilgisi tutulur.
    blankCalibrated = true;

    // Web panele yeni blank değeri bildirilir.
    Serial.print("STATUS,BLANK_SET,");
    Serial.println(blankRaw, 2);
  }

  // -------------------------------------------------------
  // GET_REF KOMUTU
  // Mevcut darkRaw ve blankRaw değerlerini gösterir.
  // -------------------------------------------------------
  else if (command == "GET_REF") {

    // Referans değerleri web panele / Serial Monitor'e gönderilir.
    Serial.print("STATUS,REF,DARK=");
    Serial.print(darkRaw, 2);
    Serial.print(",BLANK=");
    Serial.println(blankRaw, 2);
  }

  // -------------------------------------------------------
  // RESET_AVG KOMUTU
  // Ortalama hesaplama tamponlarını sıfırlar.
  // Numune değişiminden sonra kullanılabilir.
  // -------------------------------------------------------
  else if (command == "RESET_AVG") {

    // Ortalama tamponları sıfırlanır.
    resetAverages();

    // Web panele bilgi mesajı gönderilir.
    Serial.println("STATUS,AVERAGE_RESET");
  }

  // -------------------------------------------------------
  // Tanınmayan komut gelirse hata mesajı gönderilir.
  // -------------------------------------------------------
  else {

    // Komut bilinmiyorsa hata olarak yazdırılır.
    Serial.print("ERROR,UNKNOWN_COMMAND,");
    Serial.println(command);
  }
}


// =======================================================
// ORTALAMA TAMPONLARINI SIFIRLAMA FONKSİYONU
// Dark/blank alma öncesinde veya numune değişiminde kullanılır.
// =======================================================
void resetAverages() {

  // Raw toplamı sıfırlanır.
  totalRaw = 0.0;

  // Transmittance toplamı sıfırlanır.
  totalTransmittance = 0.0;

  // Absorbance toplamı sıfırlanır.
  totalAbsorbance = 0.0;

  // Ölçüm sayacı sıfırlanır.
  readIndex = 0;

  // Ortalama Raw değeri sıfırlanır.
  averageRaw = 0.0;

  // Ortalama Transmittance değeri sıfırlanır.
  averageTransmittance = 0.0;

  // Ortalama Absorbance değeri sıfırlanır.
  averageAbsorbance = 0.0;
}