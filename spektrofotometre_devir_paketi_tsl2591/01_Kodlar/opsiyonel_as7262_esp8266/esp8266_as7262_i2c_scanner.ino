#include <Wire.h>

/*
  ESP8266 NodeMCU + AS7262 I2C tarama kodu
  Bağlantı:
  - AS7262 3V3 -> NodeMCU 3V3
  - AS7262 GND -> NodeMCU G
  - AS7262 SDA -> NodeMCU D2 / GPIO4
  - AS7262 SCL -> NodeMCU D1 / GPIO5
*/

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(4, 5);      // SDA GPIO4, SCL GPIO5
  Wire.setClock(100000);

  Serial.println();
  Serial.println("I2C tarama başladı");
}

void loop() {
  byte error;
  int deviceCount = 0;

  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("I2C cihaz bulundu: 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
      deviceCount++;
    }
  }

  if (deviceCount == 0) {
    Serial.println("I2C cihaz bulunamadı");
  }

  Serial.println("Tarama tamamlandı");
  delay(3000);
}
