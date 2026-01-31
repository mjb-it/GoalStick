#include <Adafruit_NeoPixel.h>

#define LED_PIN    4
#define LED_COUNT  300
#define BRIGHTNESS 60

// Serial2 pins for Raspberry Pi communication
#define RXD2 16
#define TXD2 17

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// Celebration state
bool isCelebrating = false;
unsigned long celebrationStartTime = 0;
uint32_t activeColors[5]; 
int activeColorCount = 0;
int chaseOffset = 0;

void setup() {
  // USB Serial for debugging
  Serial.begin(115200);
  
  // Serial2 for Raspberry Pi communication on GPIO 16/17
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2);
  
  strip.begin();
  strip.setBrightness(BRIGHTNESS);
  strip.show();
  Serial.println("Universal LED Controller Online. Waiting for Pi...");
}

void loop() {
  // Listen for commands from Raspberry Pi on Serial2
  if (Serial2.available() > 0) {
    String input = Serial2.readStringUntil('\n');
    input.trim();

    if (input.startsWith("C:")) {
      Serial.println("Received celebration command");
      parseCelebration(input.substring(2));
    } else if (input == "I") {
      Serial.println("Received idle command");
      stopCelebration();
    }
  }

  if (isCelebrating) {
    updateCelebration();
  }
}

// Parses a string like "FFFFFF,002D62,E51937"
void parseCelebration(String data) {
  activeColorCount = 0;
  int startIdx = 0;
  int nextComma = data.indexOf(',');

  while (nextComma != -1 && activeColorCount < 5) {
    String hex = data.substring(startIdx, nextComma);
    activeColors[activeColorCount++] = strtoul(hex.c_str(), NULL, 16);
    startIdx = nextComma + 1;
    nextComma = data.indexOf(',', startIdx);
  }
  // Catch the last color
  if (activeColorCount < 5) {
    String hex = data.substring(startIdx);
    activeColors[activeColorCount++] = strtoul(hex.c_str(), NULL, 16);
  }

  triggerGoal();
}

void triggerGoal() {
  isCelebrating = true;
  celebrationStartTime = millis();
  // Standard 3-blink
  for (int b = 0; b < 3; b++) {
    for(int i=0; i<strip.numPixels(); i++) strip.setPixelColor(i, activeColors[0]);
    strip.show(); delay(300);
    strip.clear(); strip.show(); delay(300);
  }
}

void updateCelebration() {
  if (millis() - celebrationStartTime > 10000) {
    stopCelebration();
    return;
  }

  int unitSize = 10;
  int patternLength = activeColorCount * unitSize;

  for (int i = 0; i < strip.numPixels(); i++) {
    int pos = (i + chaseOffset) % patternLength;
    strip.setPixelColor(i, activeColors[pos / unitSize]);
  }
  strip.show();
  chaseOffset++;
  delay(20);
}

void stopCelebration() {
  isCelebrating = false;
  strip.clear();
  strip.show();
}