// Node B "Earth": every ESP-NOW frame received -> one serial frame
// payload = int8 rssi, uint32 millis (LE), received bytes.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#ifndef CHANNEL
#define CHANNEL 1
#endif
#define MAX_DATA (250 - 5)  // serial payload is capped at 250, so 5 bytes go to the header

struct Rx {
  int8_t rssi;
  uint32_t ms;
  uint8_t len;
  uint8_t data[250];
};

static QueueHandle_t q;

uint8_t crc8(const uint8_t *d, size_t n, uint8_t c = 0) {
  while (n--) {
    c ^= *d++;
    for (int i = 0; i < 8; i++) c = (c & 0x80) ? (c << 1) ^ 0x07 : c << 1;
  }
  return c;
}

void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  Rx r;
  r.rssi = info->rx_ctrl->rssi;
  r.ms = millis();
  r.len = len > MAX_DATA ? MAX_DATA : len;
  memcpy(r.data, data, r.len);
  xQueueSend(q, &r, 0);  // drop if the queue is full; never block the WiFi task
}

void setup() {
  Serial.setTxBufferSize(8192);
  Serial.begin(921600);
  q = xQueueCreate(32, sizeof(Rx));
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_now_init();
  esp_now_register_recv_cb(onRecv);
  Serial.println("ROLE earth");
}

void loop() {
  Rx r;
  if (xQueueReceive(q, &r, pdMS_TO_TICKS(10)) != pdTRUE) return;
  uint8_t p[250];
  p[0] = (uint8_t)r.rssi;
  memcpy(p + 1, &r.ms, 4);  // ESP32 is little-endian
  memcpy(p + 5, r.data, r.len);
  uint8_t n = 5 + r.len;
  uint8_t hdr[2] = {0xA5, n};
  Serial.write(hdr, 2);
  Serial.write(p, n);
  Serial.write(crc8(p, n, crc8(&n, 1)));
}
