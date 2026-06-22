# Kullanım El Kitapçığı

## Amaç

Bu el kitapçığı, Arduino tabanlı düşük maliyetli spektrofotometre projesinin mezuniyet sonrası hocaya devredilmesi için hazırlanmıştır. Ana sürümde TSL2591 dijital ışık sensörü, LED ışık kaynağı, küvet yuvası ve ışık sızdırmayan 3D baskı kutu kullanılmaktadır.

## Projenin Gelişim Özeti

Proje ilk olarak LM393 LDR modülüyle kaba ışık ölçümü yapacak şekilde başlatıldı. Daha sonra ölçüm hassasiyetini artırmak için TSL2591 dijital ışık sensörüne geçildi. Kutu, LED hizası ve dark/blank/sample kalibrasyon adımları geliştirilerek tekrarlanabilir absorbans hesabı hedeflendi.

## Çalışma Prensibi

LED ışık kaynağından çıkan ışık siyah optik tüpten geçer, küvetteki blank veya numuneden geçtikten sonra TSL2591 sensöre ulaşır. Sensör ışık şiddetini dijital olarak okur. Dark ve blank değerleri kullanılarak numune için transmittance ve absorbans hesaplanır.

## Optik Yol

Son kutu mantığında optik yol şu şekildedir: LED solda, siyah tüp ortada, küvet yuvası tüpten sonra, TSL2591 sensör ise karşı tarafta konumlanır. LED, küvet ve sensör aynı eksende tutulmalıdır. Kutu kapalıyken dış ortam ışığı minimum olmalıdır.

## Sensör Bağlantısı

TSL2591, Arduino Uno üzerinde I2C ile bağlanır. SDA pini A4'e, SCL pini A5'e, VCC pini modülün desteklediği beslemeye, GND pini GND'ye bağlanır. Modül 5V uyumlu değilse 3.3V kullanılmalıdır. Pin yuvalarında temassızlık olmaması için header lehimlenmeli ve kablolar sabitlenmelidir.

## LED Seçimi

Dalga boyunu kontrol etmek için rastgele renk LED paketleri yerine açıklamasında nm değeri yazan 5 mm LED seçilmelidir. Vişne suyu ölçümleri için 520-525 nm yeşil LED uygundur. 550 nm hedefleniyorsa 550 nm veya bulunamazsa 565-570 nm yellow-green LED alınabilir. Karşılaştırma için 590-600 nm amber ve 650-660 nm kırmızı LED eklenebilir.

## Kalibrasyon Mantığı

Her ölçüm serisinde önce dark, sonra blank, sonra sample alınır. Dark ölçümde LED kapalı ve kutu kapalıdır. Blank ölçümde LED açık, küvette saf su veya çözücü vardır. Sample ölçümde aynı LED açıkken numune küveti yerleştirilir.

## Absorbans Hesabı

Karanlık düzeltmesi yapıldıktan sonra I_blank = Blank - Dark ve I_sample = Sample - Dark hesaplanır. Transmittance T = I_sample / I_blank olarak bulunur. Absorbans A = -log10(T) formülüyle hesaplanır. T değeri 0 ile 1 arasında olmalıdır.

## Vişne Suyu Ölçüm Akışı

Vişne suyu testlerinde önce saf su blank olarak alınır. Ardından vişne suyu ve suyla seyreltilmiş numuneler sırayla ölçülür. Önerilen sıra: doğrudan vişne suyu, 5 pipet su eklenmiş az seyreltilmiş numune, 10 pipet su eklenmiş orta numune, 15 pipet su eklenmiş çok seyreltilmiş numune ve 20 pipet su eklenmiş aşırı seyreltilmiş numune.

## Veri Kaydı

Önerilen CSV kolonları: tarih_saat, sample_id, led_nm, dark_lux, blank_lux, sample_lux, transmittance, absorbance, tekrar_no, not. Her numune için en az 3 tekrar alınması, sonucun ortalama ve sapma ile raporlanması önerilir.

## Sorun Giderme

Sensör değeri zıplıyorsa önce kablo teması, lehim, USB güç kaynağı, LED kararlılığı ve kutu kapağı kontrol edilir. Absorbans negatif çıkarsa sample blanktan daha fazla ışık geçiriyor olabilir; blank/sample sırası, küvet yönü ve ışık sızıntısı tekrar kontrol edilmelidir.

## Hocaya Devir Notu

Paket içinde kodlar, rapor yer tutucuları, parça listesi, envanter kontrol listesi, kullanım el kitapçığı ve hocaya gönderilebilecek kısa açıklama metni vardır. Eski raporlar, fotoğraflar ve STL dosyaları ilgili klasörlere eklenerek teslim klasörü tamamlanmalıdır.

## Opsiyonel İleri Sürüm Notu

Proje ileride AS7262/AS726x gibi çok kanallı spektral sensöre taşınırsa bu paket içindeki TSL2591 ana sürümü arşiv olarak korunmalı, yeni ESP8266/AS7262 kodları ayrı alt klasörde tutulmalıdır. Böylece proje geçmişi karışmadan izlenebilir.
