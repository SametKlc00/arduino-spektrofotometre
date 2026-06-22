#include <Wire.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_TSL2591.h"
#include <math.h>

Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);

float darkLux = 0.0;
float blankLux = 1.0;
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

void printMeasurement(String label, float sampleLux) {
  float iBlank = blankLux - darkLux;
  float iSample = sampleLux - darkLux;
  float T = iSample / iBlank;
  float A = -log10(T);

  Serial.print(label);
  Serial.print(", lux=");
  Serial.print(sampleLux, 3);
  Serial.print(", T=");
  Serial.print(T, 4);
  Serial.print(", A=");
  Serial.println(A, 4);
}

void setup() {
  Serial.begin(9600);
  delay(1000);

  if (!tsl.begin()) {
    Serial.println("TSL2591 bulunamadi.");
    while (1);
  }

  tsl.setGain(TSL2591_GAIN_MED);
  tsl.setTiming(TSL2591_INTEGRATIONTIME_300MS);

  Serial.println("Komutlar: d=dark, b=blank, s=sample");
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();
    float lux = readLuxAverage();

    if (cmd == 'd') {
      darkLux = lux;
      Serial.print("Dark kaydedildi: ");
      Serial.println(darkLux, 3);
    } else if (cmd == 'b') {
      blankLux = lux;
      Serial.print("Blank kaydedildi: ");
      Serial.println(blankLux, 3);
    } else if (cmd == 's') {
      printMeasurement("Sample", lux);
    }
  }
}
