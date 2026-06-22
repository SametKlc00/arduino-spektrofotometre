/*
  LM393 / LDR analog spektrofotometre arşiv kodu
  Bağlantı:
  - LM393 AO -> Arduino A0
  - VCC -> 5V
  - GND -> GND

  Not:
  Bu kod ilk prototip içindir. Final devir paketinde ana sensör TSL2591'dir.
*/

#include <math.h>

const int LDR_PIN = A0;
const int SAMPLE_COUNT = 5;

// Bu değerler örnektir. Kendi kutu ölçümünüzle güncellenmelidir.
float darkRaw = 1023.0;   // LED kapalı, kutu kapalı
float blankRaw = 200.0;   // LED açık, saf su / boş blank

float readAverageRaw() {
  long sum = 0;
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    sum += analogRead(LDR_PIN);
    delay(200);
  }
  return sum / (float)SAMPLE_COUNT;
}

void setup() {
  Serial.begin(9600);
  Serial.println("LM393 analog absorbans arşiv kodu");
  Serial.println("raw,T,A");
}

void loop() {
  float rawValue = readAverageRaw();

  // LM393/LDR modülünde ışık artınca analog değer düşebilir.
  // Bu yüzden ışık şiddeti darkRaw - rawValue mantığıyla hesaplanır.
  float iBlank = darkRaw - blankRaw;
  float iSample = darkRaw - rawValue;
  float T = iSample / iBlank;

  if (T <= 0.0001) T = 0.0001;
  if (T > 1.5) T = 1.5;

  float A = -log10(T);

  Serial.print(rawValue, 2);
  Serial.print(",");
  Serial.print(T, 4);
  Serial.print(",");
  Serial.println(A, 4);

  delay(1000);
}
