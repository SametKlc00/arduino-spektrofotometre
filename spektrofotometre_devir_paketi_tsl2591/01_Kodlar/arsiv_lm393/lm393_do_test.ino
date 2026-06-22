/*
  LM393 dijital çıkış test kodu
  Bağlantı:
  - DO -> Arduino D2
  - VCC -> 5V
  - GND -> GND
*/

const int LM393_DO = 2;

void setup() {
  Serial.begin(9600);
  pinMode(LM393_DO, INPUT);
  Serial.println("LM393 DO test başladı");
}

void loop() {
  int digitalValue = digitalRead(LM393_DO);
  Serial.print("DO=");
  Serial.println(digitalValue);
  delay(500);
}
