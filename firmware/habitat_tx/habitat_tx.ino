// Node A "Habitat": serial frames in -> ESP-NOW broadcast out.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#ifndef CHANNEL
#define CHANNEL 1
#endif

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

uint8_t crc8(const uint8_t *d, size_t n, uint8_t c = 0) {
  while (n--) {
    c ^= *d++;
    for (int i = 0; i < 8; i++) c = (c & 0x80) ? (c << 1) ^ 0x07 : c << 1;
  }
  return c;
}

void sendFrame(const uint8_t *p, uint8_t n) {
  uint8_t hdr[2] = {0xA5, n};
  Serial.write(hdr, 2);
  Serial.write(p, n);
  Serial.write(crc8(p, n, crc8(&n, 1)));
}

// Broadcast, waiting briefly if the ESP-NOW TX queue is full.
bool bcast(const uint8_t *p, size_t n) {
  esp_err_t e;
  while ((e = esp_now_send(BCAST, p, n)) == ESP_ERR_ESPNOW_NO_MEM) delay(1);
  return e == ESP_OK;
}

void runTestBurst(uint16_t count, uint16_t gap, uint8_t size) {
  size = constrain(size, 3, 250);
  uint8_t buf[250];
  for (int i = 3; i < size; i++) buf[i] = i;
  buf[0] = 0x7E;
  uint16_t sent = 0;
  for (uint16_t seq = 0; seq < count; seq++) {
    buf[1] = seq & 0xFF;
    buf[2] = seq >> 8;
    if (bcast(buf, size)) sent++;
    delay(gap);
  }
  uint8_t reply[3] = {0xC1, (uint8_t)(sent & 0xFF), (uint8_t)(sent >> 8)};
  sendFrame(reply, 3);
}

void handlePayload(const uint8_t *p, uint8_t n) {
  if (p[0] == 0xC0 && n >= 6)
    runTestBurst(p[1] | (p[2] << 8), p[3] | (p[4] << 8), p[5]);
  else
    bcast(p, n);
}

void setup() {
  Serial.setRxBufferSize(4096);
  Serial.begin(921600);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) Serial.println("# esp_now_init failed");
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  esp_now_add_peer(&peer);
  Serial.println("ROLE habitat");
}

// Frame parser state: 0 = wait sync, 1 = len, 2 = payload, 3 = crc
static uint8_t st = 0, len = 0, pos = 0, buf[250];

void loop() {
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
