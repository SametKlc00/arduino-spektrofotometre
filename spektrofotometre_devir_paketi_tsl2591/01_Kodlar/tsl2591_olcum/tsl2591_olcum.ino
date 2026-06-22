#include <Wire.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_TSL2591.h"

Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);

const int SAMPLE_COUNT = 5;

float readLuxAverage() {
  float sum = 0;
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    sensors_event_t event;
    tsl.getEvent(&event);
    sum += event.light;
    delay(200);
  }
  return sum / SAMPLE_COUNT;
}

void setup() {
  Serial.begin(9600);
  delay(1000);

  if (!tsl.begin()) {
    Serial.println("TSL2591 bulunamadi. SDA/SCL, VCC ve GND baglantilarini kontrol et.");
    while (1);
  }

  tsl.setGain(TSL2591_GAIN_MED);
  tsl.setTiming(TSL2591_INTEGRATIONTIME_300MS);

  Serial.println("sample_id,lux");
}

void loop() {
  float lux = readLuxAverage();
  Serial.print("TSL2591_TEST,");
  Serial.println(lux, 3);
  delay(1000);
}
