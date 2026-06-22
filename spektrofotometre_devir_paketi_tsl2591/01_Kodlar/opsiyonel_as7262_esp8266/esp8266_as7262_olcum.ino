#include <Wire.h>
#include "SparkFun_AS726X.h"

/*
  ESP8266 NodeMCU + AS7262 opsiyonel ileri sürüm ölçüm kodu
  Gerekli kütüphane: SparkFun AS726X
*/

AS726X sensor;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(4, 5);      // SDA D2(GPIO4), SCL D1(GPIO5)
  Wire.setClock(100000);

  if (sensor.begin() == false) {
    Serial.println("AS7262 bulunamadı. Lehim, SDA/SCL ve 3V3 bağlantısını kontrol et.");
    while (1);
  }

  Serial.println("sample_id,violet_450,blue_500,green_550,yellow_570,orange_600,red_650");
}

void loop() {
  sensor.takeMeasurements();

  Serial.print("AS7262_TEST,");
  Serial.print(sensor.getCalibratedViolet(), 2);
  Serial.print(",");
  Serial.print(sensor.getCalibratedBlue(), 2);
  Serial.print(",");
  Serial.print(sensor.getCalibratedGreen(), 2);
  Serial.print(",");
  Serial.print(sensor.getCalibratedYellow(), 2);
  Serial.print(",");
  Serial.print(sensor.getCalibratedOrange(), 2);
  Serial.print(",");
  Serial.println(sensor.getCalibratedRed(), 2);

  delay(1000);
}
