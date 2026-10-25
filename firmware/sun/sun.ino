// Node C "Sun": deliberate interferer. Bursts of 250-byte junk broadcasts.
// Duty = knob on GPIO34, or a serial override frame {0xF1, duty%, uint16 seconds}.
// Safety: transmits only while an override is active, or the knob is >5% and
// was moved within the last 30 s.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#ifndef CHANNEL
#define CHANNEL 1
#endif
#ifndef TX_POWER_QDBM
#define TX_POWER_QDBM 8  // units of 0.25 dBm: 8 = 2 dBm (the minimum)
#endif
#define KNOB_PIN 34
#define PERIOD_MIN_MS 200  // each cycle is a random length so bursts never phase-lock with the data
#define PERIOD_MAX_MS 400
#define KNOB_TIMEOUT_MS 30000
#define KNOB_MOVE_THRESH 120  // ADC counts (~3%); ignores ADC noise

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint8_t junk[250];

static int lastKnob;
static bool knobMoved = false;
static uint32_t lastMoveMs = 0;
static uint8_t overrideDuty = 0;
static uint32_t overrideEndMs = 0;
static bool overrideOn = false;

uint8_t crc8(const uint8_t *d, size_t n, uint8_t c = 0) {
  while (n--) {
    c ^= *d++;
    for (int i = 0; i < 8; i++) c = (c & 0x80) ? (c << 1) ^ 0x07 : c << 1;
  }
  return c;
}

void handlePayload(const uint8_t *p, uint8_t n) {
  if (p[0] != 0xF1 || n < 4) return;
  uint16_t secs = p[2] | (p[3] << 8);
  overrideDuty = min<uint8_t>(p[1], 100);
  overrideOn = secs > 0;  // seconds = 0 cancels the override
  overrideEndMs = millis() + secs * 1000UL;
}

static uint8_t st = 0, len = 0, pos = 0, buf[250];

void pollSerial() {
  while (Serial.available()) {
    uint8_t b = Serial.read();
    if (st == 0) {
      if (b == 0xA5) st = 1;
    } else if (st == 1) {
      if (b >= 1 && b <= 250) { len = b; pos = 0; st = 2; }
      else st = (b == 0xA5);
    } else if (st == 2) {
      buf[pos++] = b;
      if (pos == len) st = 3;
    } else {
      if (b == crc8(buf, len, crc8(&len, 1))) handlePayload(buf, len);
      st = 0;
    }
  }
}

// Returns the duty (0..100) to use right now; 0 means stay silent.
int currentDuty() {
  uint32_t now = millis();
  if (overrideOn && (int32_t)(now - overrideEndMs) >= 0) overrideOn = false;
  if (overrideOn) return overrideDuty;

  int k = analogRead(KNOB_PIN);
  if (abs(k - lastKnob) > KNOB_MOVE_THRESH) {
    lastKnob = k;
    knobMoved = true;
    lastMoveMs = now;
  }
  int duty = (long)lastKnob * 100 / 4095;
  if (duty <= 5 || !knobMoved || now - lastMoveMs > KNOB_TIMEOUT_MS) return 0;
  return duty;
}

void setup() {
  Serial.begin(921600);
  for (int i = 0; i < 250; i++) junk[i] = esp_random();
  analogReadResolution(12);
  lastKnob = analogRead(KNOB_PIN);  // the boot position doesn't count as a move
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_max_tx_power(TX_POWER_QDBM);
  esp_now_init();
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  esp_now_add_peer(&peer);
  Serial.println("ROLE sun");
}

void loop() {
  static uint32_t periodStart = 0, periodMs = 0;
  static int duty = 0, prevDuty = 0;
  pollSerial();
  uint32_t now = millis();
  if (now - periodStart >= periodMs) {
    periodStart = now;
    periodMs = PERIOD_MIN_MS + esp_random() % (PERIOD_MAX_MS - PERIOD_MIN_MS + 1);
    duty = currentDuty();
    if ((duty > 0) != (prevDuty > 0)) Serial.printf("# sun %s duty=%d\n", duty ? "on" : "off", duty);
    prevDuty = duty;
  }
  if (now - periodStart < (uint32_t)duty * periodMs / 100) {
    if (esp_now_send(BCAST, junk, sizeof(junk)) == ESP_ERR_ESPNOW_NO_MEM) delay(1);
  } else {
    delay(1);
  }
}
