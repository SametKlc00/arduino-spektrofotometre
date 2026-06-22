# Arduino Tabanlı Düşük Maliyetli Spektrofotometre

Bu proje, düşük maliyetli bir spektrofotometre prototipi geliştirmek amacıyla hazırlanmıştır. Sistem; LED ışık kaynağı, küvet yuvası, ışık sızdırmayan 3D baskı kutu, TSL2591 dijital ışık sensörü ve Arduino tabanlı ölçüm yazılımından oluşur.

## Projenin Amacı

Projenin amacı, belirli dalga boyundaki LED ışığının numuneden geçtikten sonra sensör tarafından ölçülmesi ve bu ölçümden geçirgenlik ile absorbans değerlerinin hesaplanmasıdır.

Bu sayede su, vişne suyu ve seyreltilmiş numuneler gibi örneklerde ışık geçirgenliği karşılaştırılabilir.

## Çalışma Prensibi

Optik yol:

```text
LED ışık kaynağı -> siyah optik tüp -> küvet -> TSL2591 ışık sensörü
```

Ölçüm sırasında üç temel değer alınır:

- **Dark:** LED kapalıyken alınan karanlık ölçüm
- **Blank:** LED açıkken saf su veya çözücü ile alınan referans ölçüm
- **Sample:** LED açıkken numune ile alınan ölçüm

Absorbans hesabı:

```text
I_blank = Blank - Dark
I_sample = Sample - Dark
T = I_sample / I_blank
A = -log10(T)
```

## Kullanılan Donanımlar

- Arduino Uno veya uyumlu geliştirme kartı
- TSL2591 dijital ışık sensörü
- 5 mm LED ışık kaynakları
- 520-525 nm yeşil LED
- 550 nm veya 565-570 nm yellow-green LED
- 590-600 nm amber/turuncu LED
- 650-660 nm kırmızı LED
- Küvet
- Siyah optik tüp
- Işık sızdırmayan 3D baskı kutu
- Jumper kablo, pin header ve dirençler

## TSL2591 Bağlantısı

| TSL2591 | Arduino Uno |
|---|---|
| SDA | A4 |
| SCL | A5 |
| VCC | 5V veya modüle göre 3.3V |
| GND | GND |

## Klasör Yapısı

| Klasör | Açıklama |
|---|---|
| `01_Kodlar` | Arduino ve Python ölçüm kodları |
| `02_Raporlar` | Proje raporları için ayrılan klasör |
| `03_PDF_Ciktilar` | PDF çıktıları |
| `04_Gorseller` | Devre, kutu ve ölçüm görselleri |
| `05_3D_Model_ve_Kutu` | 3D baskı kutu dosyaları |
| `06_Donanim_Notlari` | Parça listesi ve donanım notları |
| `07_Kullanim_El_Kitapcigi` | Kullanım kılavuzu |

## Kodlar

| Dosya | Açıklama |
|---|---|
| `01_Kodlar/tsl2591_olcum/tsl2591_olcum.ino` | TSL2591 sensöründen lux değeri okur |
| `01_Kodlar/tsl2591_absorbans_komutlu/tsl2591_absorbans_komutlu.ino` | Dark, blank ve sample ölçümleriyle absorbans hesabı yapar |
| `01_Kodlar/python_serial_csv_logger/tsl2591_csv_logger.py` | Seri porttan gelen verileri CSV dosyasına kaydeder |
| `01_Kodlar/arsiv_lm393/lm393_analog_absorbans.ino` | İlk LM393/LDR prototipinin arşiv kodudur |

## Ölçüm Sırası

1. Sensör ve LED bağlantıları kontrol edilir.
2. Kutu kapağı kapatılır.
3. LED kapalıyken dark ölçümü alınır.
4. Saf su veya çözücü ile blank ölçümü alınır.
5. Numune yerleştirilir ve sample ölçümü alınır.
6. Transmittance ve absorbans değeri hesaplanır.
7. Her numune için ölçüm birkaç kez tekrarlanır.

## Proje Gelişim Süreci

Proje ilk olarak LM393 LDR modülüyle başlatılmıştır. Daha sonra daha hassas ve kararlı ölçüm almak için TSL2591 dijital ışık sensörüne geçilmiştir.

Işık sızıntısını azaltmak ve ölçüm tekrarlanabilirliğini artırmak için 3D baskı kapalı kutu kullanılmıştır. Ölçümler dark, blank ve sample kalibrasyon adımlarıyla yapılmıştır.

## Not

Bu depo, projenin mezuniyet sonrası devredilebilmesi için düzenlenmiştir. Kodlar, parça listesi, kullanım kılavuzu ve rapor klasörleri birlikte sunulmuştur.
