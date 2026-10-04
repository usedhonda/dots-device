"""Compile the firmware's Wi-Fi recovery branch against a tiny stateful stub."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "firmware/kai_companion/kai_companion.ino").read_text()
start = source.index('    if(WiFi.status()!=WL_CONNECTED) {', source.index('static void bridgeTask'))
end = source.index('    String base=', start)
branch = source[start:end].replace('continue;', 'return;')

harness = r'''
#include <cassert>
#include <cstdint>
uint32_t nowMs = 0;
uint32_t millis() { return nowMs; }
uint32_t reconnects = 0, disconnects = 0, begins = 0, samples = 0;
bool associated = false, connected = false, reconnectResult = true;
uint32_t wifiReconnectAttempts = 0, wifiReconnectFailedCalls = 0;
void *stateLock = nullptr;
const char *bridgeStatus = "offline";
struct FakeWiFi {
  int status() const { return connected ? 3 : 0; }
  struct STAType { bool connected() const { return associated; } } STA;
  bool reconnect() { ++reconnects; return reconnectResult; }
  void disconnect() { ++disconnects; }
  void begin(const char*, const char*) { ++begins; }
} WiFi;
const int WL_CONNECTED = 3;
const char *WIFI_SSID = "ssid", *WIFI_PASSWORD = "password";
const int portMAX_DELAY = 0;
void xSemaphoreTake(void*, int) {}
void xSemaphoreGive(void*) {}
void vTaskDelay(int) {}
int pdMS_TO_TICKS(int ms) { return ms; }
void measurementSample(const char*) { ++samples; }
void oneIteration() {
  static uint32_t wifiAttempt = 0;
  static bool initialized = false;
  if (!initialized) { wifiAttempt = millis(); initialized = true; }
''' + branch + r'''
}
void reset(uint32_t t, bool isConnected, bool isAssociated) {
  nowMs=t; connected=isConnected; associated=isAssociated;
  reconnects=disconnects=begins=samples=0;
  wifiReconnectAttempts=wifiReconnectFailedCalls=0; reconnectResult=true;
}
int main() {
  // Healthy iterations refresh the attempt clock, so a later drop gets grace.
  reset(0, true, true); oneIteration(); nowMs=14999; connected=false; associated=false; oneIteration(); assert(reconnects==0);
  nowMs=15001; oneIteration(); assert(reconnects==1 && disconnects==0 && begins==0 && samples==1);
  assert(wifiReconnectAttempts==1 && wifiReconnectFailedCalls==0);
  // An associated station waiting for DHCP is left alone.
  reset(20000, true, true); oneIteration(); nowMs=40001; connected=false; associated=true; oneIteration(); assert(reconnects==0);
  // Failed API calls are counted without changing the reconnect schedule.
  reset(41000, true, true); oneIteration(); nowMs=57001; connected=false; associated=false; reconnectResult=false; oneIteration();
  assert(reconnects==1 && wifiReconnectAttempts==1 && wifiReconnectFailedCalls==1);
  nowMs=58000; oneIteration(); assert(reconnects==1);
  // Unsigned millis rollover still permits a retry after 15 seconds.
  reset(0xffffff00u, true, true); oneIteration(); nowMs=0x00003a99u; connected=false; associated=false; oneIteration(); assert(reconnects==1);
}
'''

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    cpp = root / "test.cpp"
    exe = root / "test"
    cpp.write_text(harness)
    subprocess.run(["c++", "-std=c++11", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS extracted Wi-Fi recovery: grace, associated wait, reconnect-only, rollover")
