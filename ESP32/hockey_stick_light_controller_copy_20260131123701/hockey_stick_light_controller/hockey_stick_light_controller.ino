#include <Adafruit_NeoPixel.h>
/* Use below for full-size ESP32
#define LED_PIN    4
#define LED_COUNT  300
#define BRIGHTNESS 60
*/

#define LED_PIN 10      // D10 on XIAO
#define LED_COUNT 300
#define BRIGHTNESS 60
#define RX_PIN 20       // D7 on XIAO  
#define TX_PIN 21       // D6 on XIAO


// Serial1 pins for Raspberry Pi communication (XIAO ESP32C3)
// D7 = GPIO20 = RX, D6 = GPIO21 = TX

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// Celebration state
bool isCelebrating = false;
unsigned long celebrationStartTime = 0;
uint32_t activeColors[5]; 
int activeColorCount = 0;
int chaseOffset = 0;

void setup() {
  // Give USB time to initialize
  delay(2000);
  
  // USB Serial for debugging (don't wait for it - blocks without USB connected)
  Serial.begin(115200);
  // Note: Removed "while (!Serial)" - it blocks forever if USB isn't connected
  
  Serial.println("Starting up...");
  
  // Serial1 for Raspberry Pi communication
  // XIAO ESP32C3: D6=GPIO21=TX, D7=GPIO20=RX
  Serial1.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);
  
  strip.begin();
  strip.setBrightness(BRIGHTNESS);
  strip.show();
  Serial.println("Universal LED Controller Online.");
}

void loop() {
  // Listen for commands from USB Serial OR Raspberry Pi Serial2
  String input = "";
  
  if (Serial.available() > 0) {
    input = Serial.readStringUntil('\n');
    input.trim();
    Serial.print("USB received: ");
    Serial.println(input);
  } else if (Serial1.available() > 0) {
    input = Serial1.readStringUntil('\n');
    input.trim();
    Serial.print("Serial1 received: ");
    Serial.println(input);
  }
  
  if (input.length() > 0) {
    if (input.startsWith("C:")) {
      Serial.println("Received celebration command");
      parseCelebration(input.substring(2));
    } else if (input == "I") {
      Serial.println("Received idle command");
      stopCelebration();
    } else if (input == "P") {
      // Ping/health check - respond with "PONG"
      Serial.println("Received ping");
      Serial1.println("PONG");
      Serial.println("PONG");
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