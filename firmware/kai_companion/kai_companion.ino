#include <Arduino.h>
#include <esp_system.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <U8g2lib.h>
#include <Arduino_GFX_Library.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "FastIMU.h"
#include "esp_lcd_touch_axs5106l.h"
#include "kai_assets.h"
#include "private_config.h"
#if __has_include("direct_private_config.h")
#include "direct_private_config.h"
#include "direct_ca.h"
#include "direct_tunnel.h"
#include "direct_mcp.h"
#else
#define KAI_DIRECT 0
#endif
#include "gravity_motion.h"
#include "bubble_layout.h"
#include "tilt_input.h"
#include "japanese_ui.h"
#include "button_assets.h"
#include "themed_assets.h"

// Waveshare ESP32-C6 Touch LCD 1.47: landscape UI (native panel is 172x320).
#define SCREEN_W 320
#define SCREEN_H 172
#define ROTATION 1
#define GFX_BL 23
#define TOUCH_SDA 18
#define TOUCH_SCL 19
#define TOUCH_RST 20
#define TOUCH_INT 21
#define IMU_ADDRESS 0x6B
#define BG_COLOR 0xF77D
#define DARK_BG 0x10C4
#define DARK_CARD 0x2188
#define DARK_TEXT 0xF7BE
#define NORMAL_CARD 0xFFFF
#define NORMAL_TEXT 0x0825

Arduino_DataBus *bus = new Arduino_HWSPI(15, 14, 1, 2);
Arduino_GFX *panel = new Arduino_ST7789(bus, 22, 0, false, 172, 320, 34, 0, 34, 0);
Arduino_Canvas *gfx = new Arduino_Canvas(SCREEN_W, SCREEN_H, panel);
QMI8658 imu;
calData calib = {0};
AccelData accelData;
GyroData gyroData;

enum Page : uint8_t { HOME = 0, MENU = 1, DETAIL = 2, PAGE_PROGRESS = 3, SETTINGS = 4 };
static uint8_t PAGE_COUNT = 4;
static uint8_t MAX_PAGE = PAGE_COUNT - 1;
static Page page = HOME;
static uint32_t lastTouchMs = 0;
static uint32_t lastFrameMs = 0;
static uint32_t lastTelemetryMs = 0;
static float characterX = KAI_W / 2 + 4;
static GravityMotion motion;
static BubbleLayout bubbleLayout;
static float neutralX=0, neutralY=0;
static uint32_t motionUs=0, sensorMs=0, calibrationUntil=0;
static float injectedGravity=0;
static uint32_t injectedUntil=0;
static float scrollX=0, settleFrom=0;
static uint8_t targetPage=0;
static uint32_t settleStart=0, settleDuration=260;
static bool settling=false, fingerDown=false, dragging=false, interruptedSlide=false;
static int startTouchX=0, startTouchY=0, lastFingerX=0, lastFingerY=0;
static float dragOrigin=0, fingerVelocity=0;
static uint8_t dragPage=0;
static uint32_t fingerStart=0, fingerLast=0;
static uint32_t frameCount=0, lastRenderUs=0, maxRenderUs=0;
static uint8_t menuPage = 0;
static bool darkTheme = true;
static Preferences preferences;
static constexpr uint16_t rgb565(uint32_t c) {
  return (uint16_t)(((c >> 19) << 11) | (((c >> 10) & 0x3F) << 5) | ((c >> 3) & 0x1F));
}
static uint16_t themeBackground() { return darkTheme ? DARK_BG : BG_COLOR; }
static uint16_t themeCard() { return darkTheme ? DARK_CARD : NORMAL_CARD; }
static uint16_t themeText() { return darkTheme ? DARK_TEXT : NORMAL_TEXT; }

static bool imuReady = false;
static bool touchReady = false;
static bool simulated = false;
static String bridgeSummary = "Macへの接続を待っています";
static String directReceiptDisplay = "";
static String bridgeStatus = "offline";
static int lastHttpCode = 0;
static uint32_t wifiDisconnectCount = 0;
static uint32_t wifiLastDisconnectMs = 0;
static uint8_t wifiLastDisconnectReason = 0;
static uint32_t wifiFirstConnectedMs = 0, wifiFirstGotIpMs = 0;
static uint32_t firstValidClockMs = 0, firstTunnelPollMs = 0;
static uint32_t wifiReconnectAttempts = 0, wifiReconnectFailedCalls = 0;
static bool bridgeTaskCreated = false;
static TaskHandle_t bridgeTaskHandle=nullptr;
static String pendingCommand = "";
static SemaphoreHandle_t stateLock;
static String interactionId, interactionText, interactionSource, interactionStatus;
static String choiceIds[4], choiceLabels[4], selectedChoice;
static uint8_t choiceCount=0;
static bool interactionReceived=false;
static String choiceSendId, choiceSendInteraction, choiceSendValue, choiceSendStatus;
static bool interactionArrived=false;
static bool answerEventDelivered=false;
static uint32_t choiceRetryAt=0;
static uint32_t choiceQueuedAt=0,choiceQueueMs=0,choiceHttpMs=0,choiceTotalMs=0,choiceAttempts=0;
static String drawnInteractionId;
static int questionScrollPx=0, questionLineCount=1, questionDragStart=0;
static bool textDragging=false;
static constexpr int QUESTION_X=12, QUESTION_Y=12, QUESTION_W=176;
static constexpr int QUESTION_LINES=5, QUESTION_LEADING=26, QUESTION_BOTTOM=144;
static constexpr int ANSWER_X=204, ANSWER_W=104, ANSWER_Y=12, ANSWER_H=60, ANSWER_STEP=72;
static int questionMaxScroll(){return max(0,(questionLineCount-QUESTION_LINES)*QUESTION_LEADING);}

static void wifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event != ARDUINO_EVENT_WIFI_STA_DISCONNECTED &&
      event != ARDUINO_EVENT_WIFI_STA_CONNECTED &&
      event != ARDUINO_EVENT_WIFI_STA_GOT_IP) return;
  xSemaphoreTake(stateLock, portMAX_DELAY);
  if (event == ARDUINO_EVENT_WIFI_STA_CONNECTED) {
    if (!wifiFirstConnectedMs) wifiFirstConnectedMs = millis();
  } else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    if (!wifiFirstGotIpMs) wifiFirstGotIpMs = millis();
  } else {
    ++wifiDisconnectCount;
    wifiLastDisconnectReason = info.wifi_sta_disconnected.reason;
    wifiLastDisconnectMs = millis();
  }
  xSemaphoreGive(stateLock);
}

// A small durable journal keeps enough context to diagnose resets while avoiding
// a flash write for every one-second sample.  Entries are removed only after
// the bridge confirms a 200 response.
static constexpr uint8_t MEASUREMENT_CAPACITY = 16;
struct DiagnosticMeasurement {
  String bootId;
  uint32_t seq = 0;
  uint32_t uptimeMs = 0;
  int batteryMv = 0;
  int minBatteryMv = 0;
  int wifiStatus = 0;
  int rssi = 0;
  int httpCode = 0;
  int resetReason = 0;
  String stage;
};
static Preferences measurementPreferences;
static DiagnosticMeasurement measurementJournal[MEASUREMENT_CAPACITY];
static uint8_t measurementCount = 0;
static uint32_t measurementSeq = 0;
static uint32_t measurementLastSampleMs = 0;
static uint32_t measurementLastCheckpointMs = 0;
static String measurementBootId;
static uint32_t measurementBootCounter = 0;
static int bootMinBatteryMv = 0;

static int batteryMillivolts() { return (int)analogReadMilliVolts(0) * 3; }

static void measurementSaveUnlocked() {
  JsonDocument root;
  root["boot_counter"] = measurementBootCounter;
  JsonArray values = root["samples"].to<JsonArray>();
  for (uint8_t i = 0; i < measurementCount; ++i) {
    JsonObject item = values.add<JsonObject>();
    item["boot_id"] = measurementJournal[i].bootId; item["seq"] = measurementJournal[i].seq;
    item["uptime_ms"] = measurementJournal[i].uptimeMs; item["battery_mv"] = measurementJournal[i].batteryMv;
    item["min_battery_mv"] = measurementJournal[i].minBatteryMv; item["wifi_status"] = measurementJournal[i].wifiStatus;
    item["rssi"] = measurementJournal[i].rssi; item["http_code"] = measurementJournal[i].httpCode;
    item["reset_reason"] = measurementJournal[i].resetReason; item["stage"] = measurementJournal[i].stage;
  }
  String encoded; serializeJson(root, encoded);
  bool ok = measurementPreferences.putBytes("journal", encoded.c_str(), encoded.length()) == encoded.length();
  if (!ok) Serial.println("{\"type\":\"diagnostics\",\"event\":\"measurement_nvs_write_failed\"}");
  measurementLastCheckpointMs = millis();
}

static void measurementLoad() {
  size_t size = measurementPreferences.getBytesLength("journal");
  String journal;
  if (size > 0 && size < 12000) {
    char *buffer = new char[size + 1];
    size_t read = measurementPreferences.getBytes("journal", buffer, size);
    buffer[read] = 0; journal = buffer; delete[] buffer;
  }
  JsonDocument root;
  if (!journal.isEmpty() && !deserializeJson(root, journal)) {
    measurementBootCounter = root["boot_counter"] | 0U;
    JsonArray values = root["samples"].as<JsonArray>();
    measurementCount = min((uint8_t)values.size(), MEASUREMENT_CAPACITY);
    for (uint8_t i = 0; i < measurementCount; ++i) {
      JsonObject doc = values[i];
      measurementJournal[i].bootId = doc["boot_id"].as<String>(); measurementJournal[i].seq = doc["seq"] | 0;
      measurementJournal[i].uptimeMs = doc["uptime_ms"] | 0; measurementJournal[i].batteryMv = doc["battery_mv"] | 0;
      measurementJournal[i].minBatteryMv = doc["min_battery_mv"] | measurementJournal[i].batteryMv;
      measurementJournal[i].wifiStatus = doc["wifi_status"] | 0; measurementJournal[i].rssi = doc["rssi"] | 0;
      measurementJournal[i].httpCode = doc["http_code"] | 0; measurementJournal[i].resetReason = doc["reset_reason"] | 0;
      measurementJournal[i].stage = doc["stage"].as<String>();
    }
    return;
  }
  measurementCount = 0;

}

static void measurementAppendUnlocked(const char *stage, bool persistNow = false) {
  DiagnosticMeasurement m;
  m.bootId = measurementBootId;
  m.seq = measurementSeq++;
  m.uptimeMs = millis();
  m.batteryMv = batteryMillivolts();
  bootMinBatteryMv = bootMinBatteryMv == 0 ? m.batteryMv : min(bootMinBatteryMv, m.batteryMv);
  m.minBatteryMv = bootMinBatteryMv;
  m.wifiStatus = (int)WiFi.status();
  m.rssi = m.wifiStatus == WL_CONNECTED ? WiFi.RSSI() : 0;
  m.httpCode = lastHttpCode;
  m.resetReason = (int)esp_reset_reason();
  m.stage = stage;
  if (measurementCount == MEASUREMENT_CAPACITY) {
    uint8_t drop = 0;
    for (uint8_t i = 0; i < measurementCount; ++i) if (measurementJournal[i].stage == "sample") { drop = i; break; }
    for (uint8_t i = drop + 1; i < MEASUREMENT_CAPACITY; ++i) measurementJournal[i - 1] = measurementJournal[i];
    measurementCount--;
  }
  measurementJournal[measurementCount++] = m;
  if (persistNow) measurementSaveUnlocked();
}

static void measurementSample(const char *stage, bool persistNow = false) {
  xSemaphoreTake(stateLock, portMAX_DELAY);
  measurementAppendUnlocked(stage, persistNow);
  xSemaphoreGive(stateLock);
}

static void measurementCheckpointIfDue() {
  if (millis() - measurementLastCheckpointMs < 30000) return;
  xSemaphoreTake(stateLock, portMAX_DELAY);
  measurementSaveUnlocked();
  xSemaphoreGive(stateLock);
}

static void serialMeasurements() {
  xSemaphoreTake(stateLock, portMAX_DELAY);
  JsonDocument doc;
  JsonArray values = doc["samples"].to<JsonArray>();
  for (uint8_t i = 0; i < measurementCount; ++i) {
    JsonObject item = values.add<JsonObject>();
    item["boot_id"] = measurementJournal[i].bootId;
    item["seq"] = measurementJournal[i].seq;
    item["uptime_ms"] = measurementJournal[i].uptimeMs;
    item["battery_mv"] = measurementJournal[i].batteryMv;
    item["min_battery_mv"] = measurementJournal[i].minBatteryMv;
    item["wifi_status"] = measurementJournal[i].wifiStatus;
    item["rssi"] = measurementJournal[i].rssi;
    item["http_code"] = measurementJournal[i].httpCode;
    item["reset_reason"] = measurementJournal[i].resetReason;
    item["stage"] = measurementJournal[i].stage;
  }
  serializeJson(doc, Serial); Serial.println();
  xSemaphoreGive(stateLock);
}


static void lcdRegInit(void) {
  static const uint8_t init_operations[] = {
    BEGIN_WRITE,
    WRITE_COMMAND_8, 0x11,  // 2: Out of sleep mode, no args, w/delay
    END_WRITE,
    DELAY, 120,

    BEGIN_WRITE,
    WRITE_C8_D16, 0xDF, 0x98, 0x53,
    WRITE_C8_D8, 0xB2, 0x23,

    WRITE_COMMAND_8, 0xB7,
    WRITE_BYTES, 4,
    0x00, 0x47, 0x00, 0x6F,

    WRITE_COMMAND_8, 0xBB,
    WRITE_BYTES, 6,
    0x1C, 0x1A, 0x55, 0x73, 0x63, 0xF0,

    WRITE_C8_D16, 0xC0, 0x44, 0xA4,
    WRITE_C8_D8, 0xC1, 0x16,

    WRITE_COMMAND_8, 0xC3,
    WRITE_BYTES, 8,
    0x7D, 0x07, 0x14, 0x06, 0xCF, 0x71, 0x72, 0x77,

    WRITE_COMMAND_8, 0xC4,
    WRITE_BYTES, 12,
    0x00, 0x00, 0xA0, 0x79, 0x0B, 0x0A, 0x16, 0x79, 0x0B, 0x0A, 0x16, 0x82,

    WRITE_COMMAND_8, 0xC8,
    WRITE_BYTES, 32,
    0x3F, 0x32, 0x29, 0x29, 0x27, 0x2B, 0x27, 0x28, 0x28, 0x26, 0x25, 0x17, 0x12, 0x0D, 0x04, 0x00, 0x3F, 0x32, 0x29, 0x29, 0x27, 0x2B, 0x27, 0x28, 0x28, 0x26, 0x25, 0x17, 0x12, 0x0D, 0x04, 0x00,

    WRITE_COMMAND_8, 0xD0,
    WRITE_BYTES, 5,
    0x04, 0x06, 0x6B, 0x0F, 0x00,

    WRITE_C8_D16, 0xD7, 0x00, 0x30,
    WRITE_C8_D8, 0xE6, 0x14,
    WRITE_C8_D8, 0xDE, 0x01,

    WRITE_COMMAND_8, 0xB7,
    WRITE_BYTES, 5,
    0x03, 0x13, 0xEF, 0x35, 0x35,

    WRITE_COMMAND_8, 0xC1,
    WRITE_BYTES, 3,
    0x14, 0x15, 0xC0,

    WRITE_C8_D16, 0xC2, 0x06, 0x3A,
    WRITE_C8_D16, 0xC4, 0x72, 0x12,
    WRITE_C8_D8, 0xBE, 0x00,
    WRITE_C8_D8, 0xDE, 0x02,

    WRITE_COMMAND_8, 0xE5,
    WRITE_BYTES, 3,
    0x00, 0x02, 0x00,

    WRITE_COMMAND_8, 0xE5,
    WRITE_BYTES, 3,
    0x01, 0x02, 0x00,

    WRITE_C8_D8, 0xDE, 0x00,
    WRITE_C8_D8, 0x35, 0x00,
    WRITE_C8_D8, 0x3A, 0x05,

    WRITE_COMMAND_8, 0x2A,
    WRITE_BYTES, 4,
    0x00, 0x22, 0x00, 0xCD,

    WRITE_COMMAND_8, 0x2B,
    WRITE_BYTES, 4,
    0x00, 0x00, 0x01, 0x3F,

    WRITE_C8_D8, 0xDE, 0x02,

    WRITE_COMMAND_8, 0xE5,
    WRITE_BYTES, 3,
    0x00, 0x02, 0x00,

    WRITE_C8_D8, 0xDE, 0x00,
    WRITE_C8_D8, 0x36, 0x00,
    WRITE_COMMAND_8, 0x21,
    END_WRITE,

    DELAY, 10,

    BEGIN_WRITE,
    WRITE_COMMAND_8, 0x29,  // 5: Main screen turn on, no args, w/delay
    END_WRITE
  };
  bus->batchOperation(init_operations, sizeof(init_operations));
}


static void drawText(const char *text, int x, int y, uint16_t color, uint8_t size = 2) {
  gfx->setFont((const GFXfont*)nullptr);gfx->setUTF8Print(false);
  gfx->setTextColor(color);
  gfx->setTextSize(size);
  gfx->setCursor(x, y);
  gfx->print(text);
}

static void drawButton(int x,int y,int w,int h,const char *label,uint8_t icon) {
  gfx->fillRoundRect(x,y,w,h,12,themeCard());
  gfx->drawRoundRect(x,y,w,h,12,darkTheme?rgb565(0x35465D):rgb565(0xDBE3EA));
  drawActionIcon(gfx,icon,x+(w-ACTION_ICON_SIZE)/2,y+14,themeCard());
  JapaneseUI::selectFont(gfx,true);
  int tx=x+(w-JapaneseUI::pixelWidth(gfx,String(label),true))/2;
  JapaneseUI::draw(gfx,String(label),tx,y+h-32,themeText(),true);
}

static uint32_t waveUntil=0;
static uint32_t touchSamples=0, gestureCount=0;
static String commandStatus="", commandId="", commandSummary="";
static uint32_t commandAt=0;
static uint32_t lastBridgeMs=0;
static uint32_t stateSuccesses=0,stateFailures=0;

static void setPageIndex(uint8_t index) {
  targetPage=constrain(index,(uint8_t)0,MAX_PAGE);page=targetPage==0?HOME:(targetPage==MAX_PAGE?SETTINGS:MENU);menuPage=targetPage?targetPage-1:0;
}
static void slideTo(uint8_t index) {
  setPageIndex(index);settleFrom=scrollX;settleStart=millis();
  settleDuration=constrain((int)(180+fabsf(index*SCREEN_W-scrollX)*0.24f),180,410);
  settling=true;
}
static void updateSlide() {
  if(!settling)return;
  float t=(float)(millis()-settleStart)/settleDuration;
  if(t>=1){scrollX=targetPage*SCREEN_W;settling=false;return;}
  float u=1-t;scrollX=settleFrom+(targetPage*SCREEN_W-settleFrom)*(1-u*u*u);
}
static void drawKai(int offset) {
  uint8_t state=motion.vx>18?1:(motion.vx<-18?2:0);
  if(millis()<waveUntil)state=3;
  uint8_t frame=(millis()/(state==0?180:140))%kai_frame_counts[state];
  drawKaiFrame(gfx,kai_frame_offsets[state]+frame,
               offset+(int)lroundf(motion.x)-KAI_W/2,
               (int)lroundf(motion.y)-KAI_H/2,themeBackground());
}
static bool bubbleHidden=false;
static String lastBubbleMessage;
static void drawBubble(int offset,const String& summary) {
  if(summary!=lastBubbleMessage){lastBubbleMessage=summary;bubbleHidden=false;}
  if(bubbleHidden||bubbleLayout.moving())return;
  constexpr int width=150;
  int x=bubbleLayout.x(SCREEN_W,width,offset);
  gfx->fillRoundRect(x,20,width,108,12,themeCard());
  if(bubbleLayout.side()==BubbleLayout::RIGHT)
    gfx->fillTriangle(x,62,x-8,71,x,75,themeCard());
  else
    gfx->fillTriangle(x+width,62,x+width+8,71,x+width,75,themeCard());
  String message=millis()<calibrationUntil?"左に戻ったよ":summary;
  JapaneseUI::wrapped(gfx,message,x+11,32,width-22,4,themeText(),21);
}
static void drawQuestion(int offset,const String &text) {
  String lines[32];int count=0;size_t pos=0;
  while(pos<text.length()&&count<32){
    size_t next=JapaneseUI::nextCodepoint(text.c_str(),pos);String cp=text.substring(pos,next);
    if(lines[count].length()&&JapaneseUI::pixelWidth(gfx,lines[count]+cp,true)>QUESTION_W){count++;if(count>=32)break;}
    lines[count]+=cp;pos=next;
  }
  questionLineCount=min(count+1,32);int maxScroll=questionMaxScroll();
  questionScrollPx=constrain(questionScrollPx,0,maxScroll);
  for(int i=0;i<questionLineCount;i++){
    int y=QUESTION_Y+i*QUESTION_LEADING-questionScrollPx;
    if(y>QUESTION_Y-20&&y<QUESTION_BOTTOM)JapaneseUI::draw(gfx,lines[i],offset+QUESTION_X,y,themeText(),true);
  }
  gfx->fillRect(offset,0,ANSWER_X,QUESTION_Y,themeBackground());
  gfx->fillRect(offset,QUESTION_BOTTOM,ANSWER_X,154-QUESTION_BOTTOM,themeBackground());
  if(maxScroll){
    int height=QUESTION_BOTTOM-QUESTION_Y;
    int thumb=max(8,height*QUESTION_LINES/questionLineCount);
    gfx->fillRoundRect(offset+194,QUESTION_Y,3,height,1,darkTheme?rgb565(0x35465D):rgb565(0xDBE3EA));
    gfx->fillRoundRect(offset+194,QUESTION_Y+(height-thumb)*questionScrollPx/maxScroll,3,thumb,1,darkTheme?rgb565(0xAFC7E8):rgb565(0x3675A8));
  }
}

static void drawPage(int index,int offset,const String& summary,const String& info) {
  if(index==0){drawBubble(offset,summary);drawKai(offset);return;}
  if(index==MAX_PAGE) {
    JapaneseUI::selectFont(gfx,true);
    JapaneseUI::draw(gfx,"設定",offset+12,34,themeText(),true);
    JapaneseUI::draw(gfx,"テーマ",offset+12,62,darkTheme?rgb565(0xAAB4C5):rgb565(0x5A6475),true);
    const char *themeLabels[2]={"ノーマル","ダーク"};
    for(int i=0;i<2;i++) {
      int x=offset+12+i*154; bool selected=(darkTheme==(i==1));
      gfx->fillRoundRect(x,78,142,48,12,selected?(darkTheme?rgb565(0x334766):rgb565(0xB9D9F2)):themeCard());
      gfx->drawRoundRect(x,78,142,48,12,selected?(darkTheme?rgb565(0x7DA2D1):rgb565(0x3675A8)):(darkTheme?0x4A56:0xBDD9));
      int tx=x+(142-JapaneseUI::pixelWidth(gfx,String(themeLabels[i]),true))/2;
      JapaneseUI::draw(gfx,String(themeLabels[i]),tx,92,selected?themeText():(darkTheme?rgb565(0xAAB4C5):rgb565(0x5A6475)),true);
    }
    return;
  }
  if(index>=3) {
    String text, status, source, labels[4], ids[4], selected, sending, sendInteraction, sendValue;
    uint8_t count;
    xSemaphoreTake(stateLock,portMAX_DELAY);
    text=interactionText;status=interactionStatus;source=interactionSource;
    drawnInteractionId=interactionId;
    count=choiceCount;selected=selectedChoice;sending=choiceSendStatus;
    sendInteraction=choiceSendInteraction;sendValue=choiceSendValue;
    if((sending=="queued"||sending=="sending"||sending=="retry")&&choiceSendInteraction==interactionId)selected=choiceSendValue;
    for(int i=0;i<4;i++){labels[i]=choiceLabels[i];ids[i]=choiceIds[i];}
    xSemaphoreGive(stateLock);
    if(!count) {
      JapaneseUI::draw(gfx,"返答",offset+16,18,themeText());
      JapaneseUI::wrapped(gfx,"選択肢が届くと、ここから返せます。",offset+16,54,288,3,themeText());
      return;
    }
    drawQuestion(offset,text);
    int first=(index-3)*2;
    for(int i=first;i<count&&i<first+2;i++) {
      int x=offset+ANSWER_X;
      int y=ANSWER_Y+(i-first)*ANSWER_STEP;
      int h=ANSWER_H;
      bool chosen=selected==ids[i];
      // A recorded answer remains visible on revisit.  Treat the selected
      // choice as answered even while the bridge is reflecting the receipt,
      // so the other cards stay visibly and functionally disabled.
      bool answered=selected.length()&&(status=="selected"||sending=="recorded");
      bool selectedBusy=chosen&&(sending=="queued"||sending=="sending"||sending=="retry")&&
        sendInteraction==drawnInteractionId&&sendValue==ids[i];
      bool pressed=index==targetPage&&fingerDown&&!dragging&&!textDragging&&!interruptedSlide&&
        (chosen&&(answered||selectedBusy)||(status=="pending"&&!answered&&!selectedBusy&&
        sending!="queued"&&sending!="sending"&&sending!="retry"))&&
        startTouchX>=ANSWER_X&&startTouchX<ANSWER_X+ANSWER_W&&startTouchY>=y&&startTouchY<y+h&&
        lastFingerX>=ANSWER_X&&lastFingerX<ANSWER_X+ANSWER_W&&lastFingerY>=y&&lastFingerY<y+h;
      uint16_t bg=pressed?(darkTheme?rgb565(0x4E7590):rgb565(0xA9CEE8)):
        (chosen?(darkTheme?rgb565(0x345C55):rgb565(0xCEEBDD)):
          (answered?(darkTheme?rgb565(0x1A2433):rgb565(0xEEF1F4)):themeCard()));
      if(pressed){y+=2;h-=4;}
      gfx->fillRoundRect(x,y,ANSWER_W,h,10,bg);
      gfx->drawRoundRect(x,y,ANSWER_W,h,10,(chosen||pressed)?rgb565(0x70BFA1):(darkTheme?rgb565(0x415571):rgb565(0xCBD5E0)));
      if(chosen) {
        // The filled marker remains legible without relying on a check glyph
        // that may be absent from the bundled Japanese font.
        gfx->fillCircle(x+12,y+h/2,4,rgb565(0x70BFA1));
      }
      // Up to eight characters fit as two centered lines at native 20 px.
      String labelLines[2];int row=0;size_t pos=0;
      while(pos<labels[i].length()){
        size_t next=JapaneseUI::nextCodepoint(labels[i].c_str(),pos);
        String cp=labels[i].substring(pos,next);
        if(row==0&&JapaneseUI::pixelWidth(gfx,labelLines[row]+cp,true)>ANSWER_W-16)row=1;
        labelLines[row]+=cp;pos=next;
      }
      for(int r=0;r<=row;r++){
        int labelWidth=ANSWER_W-(chosen?22:0);
        int tx=x+(chosen?18:0)+(labelWidth-JapaneseUI::pixelWidth(gfx,labelLines[r],true))/2;
        uint16_t labelColor=answered&&!chosen?(darkTheme?rgb565(0x718096):rgb565(0x8995A3)):themeText();
        JapaneseUI::draw(gfx,labelLines[r],tx,y+(h-(row+1)*24)/2+r*24+2,labelColor,true);
      }
    }
    return;
  }
  const char *labels[2][2]={{"予定","メッセージ"},{"承認待ち","作業状況"}};
  drawButton(offset+12,12,142,106,labels[index-1][0],(index-1)*2);
  drawButton(offset+166,12,142,106,labels[index-1][1],(index-1)*2+1);
  JapaneseUI::wrapped(gfx,info,offset+10,122,300,1,darkTheme?rgb565(0xAAB4C5):0x2945,20);
}
static String statusLabel(const String& s) {
  if(s=="completed")return "完了";
  if(s=="pending_agent")return "連携待ち";
  if(s=="queued")return "待機中";
  if(s=="sending")return "送信中";
  if(s=="failed")return "失敗";
  if(s=="unknown")return "確認が必要";
  if(s=="unavailable")return "未設定";
  return "状況";
}
static int codepointCount(const String& text) {
  int count=0;size_t pos=0;
  while(pos<text.length()){pos=JapaneseUI::nextCodepoint(text.c_str(),pos);count++;}
  return count;
}
static String compactAnswer(const String& label,const char *suffix) {
  return codepointCount(label)<=8&&label.length()?label+suffix:String("回答")+suffix;
}
static String compactReceipt(const String& label) {
  return codepointCount(label)<=8&&label.length()?String("「")+label+"」で回答うけとったよ":"回答うけとったよ";
}
static void render() {
  uint32_t begin=micros();
  String summary,bs,cs,cm,answerState,answerLabel,receiptDisplay;
  bool waitingChoice=false,answeredWaiting=false,eventDelivered=false;
  wl_status_t wifiStatus=WiFi.status();
  const bool wifiConnected=wifiStatus==WL_CONNECTED;
  xSemaphoreTake(stateLock,portMAX_DELAY);
  summary=bridgeSummary;receiptDisplay=directReceiptDisplay;bs=bridgeStatus;cs=commandStatus;cm=commandSummary;
  answerState=choiceSendStatus;eventDelivered=answerEventDelivered;
  answeredWaiting=interactionStatus=="selected"&&!interactionReceived;
  String feedbackChoice=(answerState=="queued"||answerState=="sending"||answerState=="retry")?choiceSendValue:selectedChoice;
  for(int i=0;i<choiceCount;i++)if(choiceIds[i]==feedbackChoice)answerLabel=choiceLabels[i];
  waitingChoice=choiceCount>0&&interactionStatus=="pending"&&answerState!="queued"&&answerState!="sending"&&answerState!="retry";
  xSemaphoreGive(stateLock);
  if(waitingChoice)summary="質問があるよ\nタップして回答";
  else if(answerState=="queued"||answerState=="sending")summary=answerLabel.length()?String("「")+answerLabel+"」を返したよ":"回答を返したよ";
  else if(answerState=="retry")summary=answerLabel.length()?String("「")+answerLabel+"」を返したよ":"回答を返したよ";
  else if(answeredWaiting)
    summary=answerLabel.length()?String("「")+answerLabel+"」を返したよ":"回答を返したよ";
  if(receiptDisplay.length()) summary=receiptDisplay;
  gfx->fillScreen(themeBackground());gfx->setTextWrap(false);
  String info=cs.length()?statusLabel(cs)+"："+cm:"";
  for(int index=0;index<PAGE_COUNT;index++) {
    int offset=(int)lroundf(index*SCREEN_W-scrollX);
    if(offset>-SCREEN_W&&offset<SCREEN_W)drawPage(index,offset,summary,info);
  }
  // Pagination and the compact Wi-Fi indicator stay legible while content follows the finger.
  gfx->fillRect(0,154,SCREEN_W,18,themeBackground());
  for(int i=0;i<PAGE_COUNT;i++)gfx->fillCircle(136+i*12,163,2,darkTheme?rgb565(0x52627A):0xC638);
  float dot=constrain(scrollX/SCREEN_W,0.0f,(float)MAX_PAGE);
  gfx->fillRoundRect((int)lroundf(133+dot*12),160,7,5,2,darkTheme?rgb565(0xAFC7E8):0x2945);
  const uint16_t statusMuted=darkTheme?rgb565(0x415571):rgb565(0xB7C1CC);
  const uint16_t statusGood=rgb565(0x70BFA1),statusBad=rgb565(0xD77B7B);
  const int signalLevel=wifiConnected?(WiFi.RSSI()>=-60?3:(WiFi.RSSI()>=-72?2:1)):0;
  // All footer elements share y=163 as their optical center.
  gfx->fillCircle(246,168,1,wifiConnected?statusGood:statusBad);
  for(int level=1;level<=3;level++) {
    int radius=level*3;
    uint16_t color=level<=signalLevel?statusGood:statusMuted;
    gfx->drawLine(246-radius,168-radius+2,246-radius/2,168-radius,color);
    gfx->drawLine(246-radius/2,168-radius,246+radius/2,168-radius,color);
    gfx->drawLine(246+radius/2,168-radius,246+radius,168-radius+2,color);
  }
  drawText("KAI",269,160,darkTheme?rgb565(0xAFC7E8):rgb565(0x52627A),1);
  gfx->fillCircle(296,163,3,wifiConnected&&bs=="online"?statusGood:statusBad);
  if(targetPage>=3&&targetPage<MAX_PAGE){
    String receipt;
    xSemaphoreTake(stateLock,portMAX_DELAY);
    if(interactionStatus=="selected")receipt="回答済み";
    else if(choiceSendStatus=="queued"||choiceSendStatus=="sending")receipt="送信中";
    else if(choiceSendStatus=="retry")receipt="再送中";
    else if(choiceSendStatus=="stale")receipt="更新あり";
    bool demo=interactionSource=="simulation";
    xSemaphoreGive(stateLock);
    if(receipt.length())JapaneseUI::draw(gfx,receipt,12,155,themeText());
    else if(demo)drawText("TEST",12,158,darkTheme?rgb565(0xAAB4C5):rgb565(0x586879),1);
  }
  gfx->flush();frameCount++;lastRenderUs=micros()-begin;maxRenderUs=max(maxRenderUs,lastRenderUs);
}
static void handleSwipe(int dx,int dy,bool isSimulated) {
  if(abs(dx)<35||abs(dx)<abs(dy))return;
  simulated=isSimulated;lastTouchMs=millis();gestureCount++;
  slideTo(constrain((int)targetPage+(dx<0?1:-1),0,(int)MAX_PAGE));
}
static void handleTap(int x,int y,bool isSimulated) {
  simulated=isSimulated;lastTouchMs=millis();gestureCount++;
  if(settling||dragging)return;
  if(page==SETTINGS) {
    if(y>=78&&y<=126&&x>=12&&x<=308&&!(x>154&&x<166)) {
      bool nextDark=x>=166;
      if(darkTheme!=nextDark){darkTheme=nextDark;preferences.putBool("dark",darkTheme);render();}
    }
    return;
  }
  if(page==HOME){
    xSemaphoreTake(stateLock,portMAX_DELAY);bool hasChoices=choiceCount>0 && interactionStatus=="pending";xSemaphoreGive(stateLock);
    if(hasChoices&&!bubbleLayout.moving()&&bubbleLayout.contains(x,y,SCREEN_W,150,20,108))slideTo(3);
    else if(bubbleLayout.moving()&&bubbleLayout.contains(x,y,SCREEN_W,150,20,108))return;
    else if(bubbleLayout.contains(x,y,SCREEN_W,150,20,108)){
      bubbleHidden=!bubbleHidden;render();
    }
    else waveUntil=millis()+1500;return;
  }
  if(targetPage>=3&&targetPage<MAX_PAGE) {
    bool accepted=false,returnHome=false;
    xSemaphoreTake(stateLock,portMAX_DELAY);
    int i=-1;
    if(x>=ANSWER_X&&x<ANSWER_X+ANSWER_W) {
      if(y>=ANSWER_Y&&y<ANSWER_Y+ANSWER_H)i=(targetPage-3)*2;
      else if(y>=ANSWER_Y+ANSWER_STEP&&y<ANSWER_Y+ANSWER_STEP+ANSWER_H)i=(targetPage-3)*2+1;
    }
    if(i>=0&&i<choiceCount&&interactionId==drawnInteractionId) {
      // Re-tapping the answer already shown on the receipt screen is a
      // navigation gesture.  It must never enqueue a second transport
      // request, including while the first request is still in flight.
      bool selectedRecorded=interactionStatus=="selected"&&selectedChoice==choiceIds[i];
      bool selectedInFlight=(choiceSendStatus=="queued"||choiceSendStatus=="sending"||choiceSendStatus=="retry")&&
        choiceSendInteraction==interactionId&&choiceSendValue==choiceIds[i];
      if(selectedRecorded||selectedInFlight) {
        returnHome=true;
      }
    }
    if(!returnHome&&i>=0&&i<choiceCount&&interactionId==drawnInteractionId&&interactionStatus=="pending"&&choiceSendStatus!="queued"&&choiceSendStatus!="sending"&&choiceSendStatus!="retry") {
      choiceSendInteraction=interactionId;choiceSendValue=choiceIds[i];
      choiceSendId=String((uint32_t)esp_random(),HEX)+"-"+String(millis());
      accepted=true;
      choiceSendStatus="queued";choiceRetryAt=0;
      choiceQueuedAt=millis();choiceQueueMs=choiceHttpMs=choiceTotalMs=choiceAttempts=0;
      if(bridgeTaskHandle)xTaskNotifyGive(bridgeTaskHandle);
    }
    xSemaphoreGive(stateLock);
    if(accepted||returnHome){setPageIndex(0);scrollX=0;settling=dragging=textDragging=false;render();}
    return;
  }
  if(y<12||y>118||x<12||x>308||(x>154&&x<166))return;
  const char *ids[]={"schedule","messages","approvals","progress"};
  xSemaphoreTake(stateLock,portMAX_DELAY);
  if(menuPage==1&&x<154&&choiceCount>0&&interactionStatus=="pending"){xSemaphoreGive(stateLock);slideTo(3);return;}
  if(pendingCommand.length()==0&&commandStatus!="sending") {
    pendingCommand=ids[menuPage*2+(x>=166)];
    commandStatus="queued";commandSummary="Macへの接続待ち";commandAt=millis();
  }
  xSemaphoreGive(stateLock);
}
static void setNeutral() {
  motion.reset(KAI_W/2+4,77);
  bubbleLayout.reset(KAI_W/2+4,SCREEN_W/2.0f);
  calibrationUntil=millis()+1800;
}
static void pointerDown(int x,int y,bool isSimulated) {
  simulated=isSimulated;fingerDown=true;dragging=false;textDragging=false;questionDragStart=questionScrollPx;
  interruptedSlide=settling;settling=false;
  dragOrigin=scrollX;dragPage=constrain((int)lroundf(scrollX/SCREEN_W),0,(int)MAX_PAGE);
  startTouchX=lastFingerX=x;startTouchY=lastFingerY=y;
  fingerStart=fingerLast=lastTouchMs=millis();fingerVelocity=0;
}
static void pointerMove(int x,int y) {
  uint32_t now=millis();int dx=x-startTouchX,dy=y-startTouchY;
  bool replyPage=targetPage>=3&&targetPage<MAX_PAGE;
  bool inQuestion=replyPage&&startTouchX<ANSWER_X&&startTouchY<154;
  if(!dragging&&inQuestion&&abs(dy)>8&&abs(dy)*2>abs(dx))textDragging=true;
  if(textDragging){
    questionScrollPx=constrain(questionDragStart-dy,0,questionMaxScroll());
    lastFingerX=x;lastFingerY=y;fingerLast=lastTouchMs=now;return;
  }
  if(!dragging&&abs(dx)>(inQuestion?24:8)&&abs(dx)>abs(dy)*(inQuestion?2:1))dragging=true;
  if(now>fingerLast)fingerVelocity=.55f*fingerVelocity+.45f*(x-lastFingerX)*1000.0f/(now-fingerLast);
  if(dragging) {
    scrollX=dragOrigin-dx;
    if(scrollX<0)scrollX*=.22f;
    if(scrollX>MAX_PAGE*SCREEN_W)scrollX=MAX_PAGE*SCREEN_W+(scrollX-MAX_PAGE*SCREEN_W)*.22f;
  }
  lastFingerX=x;lastFingerY=y;fingerLast=lastTouchMs=now;
}
static void pointerUp() {
  if(!fingerDown)return;
  fingerDown=false;lastTouchMs=millis();
  int dx=lastFingerX-startTouchX,dy=lastFingerY-startTouchY;
  if(textDragging){textDragging=false;gestureCount++;return;}
  if(dragging) {
    if(millis()-fingerLast>100)fingerVelocity=0;
    int next=dragPage;
    if(abs(dx)>SCREEN_W/5||(abs(dx)>18&&fabsf(fingerVelocity)>420))next+=dx<0?1:-1;
    dragging=false;gestureCount++;slideTo(constrain(next,0,(int)MAX_PAGE));
  } else if(interruptedSlide)slideTo(dragPage);
  else if(abs(dx)<18&&abs(dy)<18) {
    if(page==HOME&&millis()-fingerStart>650){setNeutral();gestureCount++;}
    else handleTap(lastFingerX,lastFingerY,simulated);
  }
}

static void serialScreenshot() {
  // Exact framebuffer just flushed to the panel, not a reconstructed preview.
  Serial.printf("FRAME_BEGIN %d %d\n",SCREEN_W,SCREEN_H);
  uint16_t* fb=gfx->getFramebuffer();
  char row[SCREEN_W*5+1];
  for(int y=0;y<SCREEN_H;y++) {
    for(int x=0;x<SCREEN_W;x++) snprintf(row+x*5,6,"%04X ",fb[y*SCREEN_W+x]);
    Serial.println(row);delay(1);
  }
  Serial.println("FRAME_END");
}

static String jsonField(const String &body,const char *key) {
  // Decode escaped Unicode and quotes; byte slicing corrupts Japanese JSON text.
  JsonDocument filter;filter[key]=true;
  JsonDocument value;
  if(deserializeJson(value,body,DeserializationOption::Filter(filter)))return "";
  return value[key].is<const char*>()?value[key].as<String>():String();
}

static int bridgeRequest(const String &url,const String &payload,String *response=nullptr) {
  static NetworkClient client;
  static HTTPClient request;
  request.setReuse(true);request.setConnectTimeout(2500);request.setTimeout(3500);
  if(!request.begin(client,url))return -1;
  request.addHeader("Authorization",String("Bearer ")+BRIDGE_TOKEN);
  int code;
  if(payload.length()){request.addHeader("Content-Type","application/json");code=request.POST(payload);}
  else code=request.GET();
  if(code>0){
    int expected=request.getSize();String body=request.getString();
    if(expected>=0&&(int)body.length()!=expected)code=-11;
    if(response)*response=body;
  }
  request.end();if(code<=0)client.stop();return code;
}

static void sendQueuedChoice(const String &base) {
    String sendId,sendInteraction,sendValue;
    xSemaphoreTake(stateLock,portMAX_DELAY);
    if(choiceSendStatus=="queued"||(choiceSendStatus=="retry" && millis()-choiceRetryAt>=3000)) {
      sendId=choiceSendId;sendInteraction=choiceSendInteraction;sendValue=choiceSendValue;choiceSendStatus="sending";
      choiceQueueMs=millis()-choiceQueuedAt;choiceAttempts++;
    }
    xSemaphoreGive(stateLock);
    if(sendId.length()) {
      JsonDocument payload;payload["request_id"]=sendId;payload["interaction_id"]=sendInteraction;payload["choice_id"]=sendValue;
      String encoded;serializeJson(payload,encoded);
      uint32_t started=millis();
      int result=bridgeRequest(base+"/choice",encoded);
      xSemaphoreTake(stateLock,portMAX_DELAY);
      if(choiceSendId==sendId) {
        choiceRetryAt=millis();choiceHttpMs=millis()-started;choiceTotalMs=millis()-choiceQueuedAt;
        if(result==200){choiceSendStatus="recorded";interactionStatus="selected";selectedChoice=sendValue;}
        else if(result==409||result==400){choiceSendStatus="stale";}
        else choiceSendStatus="retry";
      }
      xSemaphoreGive(stateLock);
    }
}

#if KAI_DIRECT
static DirectMCP directMCP;
static KaiDirectTunnel *directTunnel=nullptr;
static void directRefresh() {
  JsonVariantConst q=directMCP.state["question"];
  xSemaphoreTake(stateLock,portMAX_DELAY);
  String id=q["id"]|"";
  if(id.length()) {
    if(id!=interactionId){interactionArrived=q["status"]=="pending";choiceSendStatus="";choiceSendId="";}
    interactionId=id;interactionText=q["text"].as<String>();interactionStatus=q["status"].as<String>();interactionSource="real";
    selectedChoice=q["selected_choice_id"].as<String>();interactionReceived=!q["receipt_id"].isNull();
    JsonArrayConst choices=q["choices"].as<JsonArrayConst>();choiceCount=min((int)choices.size(),4);
    for(int i=0;i<choiceCount;i++){choiceIds[i]=choices[i]["id"].as<String>();choiceLabels[i]=choices[i]["label"].as<String>();}
  }
  String summary=directMCP.state["summary"]|"KAIへ直接接続しています";
  String displayKind=directMCP.state["display_kind"]|"";
  if(id.length()&&interactionReceived&&displayKind!="summary") {
    String selectedLabel;
    for(int i=0;i<choiceCount;i++)if(choiceIds[i]==selectedChoice){selectedLabel=choiceLabels[i];break;}
    directReceiptDisplay=selectedLabel.length()?String("「")+selectedLabel+"」を返したよ":"回答を返したよ";
  } else if(displayKind=="summary") directReceiptDisplay="";
  else directReceiptDisplay="";
  JsonVariantConst currentAnswer=directMCP.state["answer"];
  answerEventDelivered=directMCP.events.delivered(id,selectedChoice,currentAnswer["request_id"].as<String>());
  bridgeSummary=summary;
  xSemaphoreGive(stateLock);
}
static void directTask() {
  configTime(0,0,"time.google.com","pool.ntp.org");
  directMCP.begin(DIRECT_CA,DIRECT_SUB);
  directRefresh();
  directTunnel=new KaiDirectTunnel("https://api.openai.com",DIRECT_KEY,DIRECT_ID,DIRECT_CA,measurementBootId);
  uint32_t wifiAttempt=millis(),lastDiagnostic=0;
  for(;;) {
    String rid,qid,cid;
    xSemaphoreTake(stateLock,portMAX_DELAY);
    if(choiceSendStatus=="queued") {rid=choiceSendId;qid=choiceSendInteraction;cid=choiceSendValue;}
    if(pendingCommand.length()){pendingCommand="";commandStatus="unavailable";commandSummary="直接接続の質問・回答を試験中です";}
    xSemaphoreGive(stateLock);
    if(rid.length()) {
      bool saved=directMCP.select(qid,cid,rid);
      xSemaphoreTake(stateLock,portMAX_DELAY);
      if(choiceSendId==rid){choiceSendStatus=saved?"recorded":"stale";choiceTotalMs=millis()-choiceQueuedAt;}
      xSemaphoreGive(stateLock);directRefresh();
    }
    if(WiFi.status()!=WL_CONNECTED) {
      if(!WiFi.STA.connected()&&millis()-wifiAttempt>15000){
        bool reconnectStarted=WiFi.reconnect();
        xSemaphoreTake(stateLock,portMAX_DELAY);
        ++wifiReconnectAttempts;if(!reconnectStarted)++wifiReconnectFailedCalls;
        xSemaphoreGive(stateLock);
        wifiAttempt=millis();
      }
      xSemaphoreTake(stateLock,portMAX_DELAY);bridgeStatus="offline";xSemaphoreGive(stateLock);
      vTaskDelay(pdMS_TO_TICKS(500));continue;
    }
    wifiAttempt=millis();
    if(time(nullptr)<1700000000){vTaskDelay(pdMS_TO_TICKS(500));continue;}
    xSemaphoreTake(stateLock,portMAX_DELAY);
    if(!firstValidClockMs)firstValidClockMs=millis();
    xSemaphoreGive(stateLock);
    JsonVariantConst answer=directMCP.state["answer"];
    if(!answer.isNull()&&answer["receipt_id"].isNull())directMCP.events.enqueue(answer["interaction_id"].as<String>(),answer["choice_id"].as<String>(),answer["request_id"].as<String>(),answer["selected_at"].as<int64_t>());
    directMCP.events.pump();
    directRefresh();
    bool answerPending=!answer.isNull()&&answer["receipt_id"].isNull();
    bool questionPending=directMCP.state["question"]["status"]=="pending";
    bool ok=directTunnel->pollOnce([](JsonVariantConst rpc){String answer=directMCP.handle(rpc);directRefresh();return answer;},(questionPending||answerPending)?1000:5000);
    auto status=directTunnel->status();
    xSemaphoreTake(stateLock,portMAX_DELAY);
    lastHttpCode=status.httpCode;
    if(ok){lastBridgeMs=millis();if(!firstTunnelPollMs)firstTunnelPollMs=lastBridgeMs;bridgeStatus="online";stateSuccesses++;}
    else {stateFailures++;bridgeStatus=(lastBridgeMs&&millis()-lastBridgeMs<15000)?"online":"offline";}
    xSemaphoreGive(stateLock);
    directRefresh();
    if(millis()-lastDiagnostic>10000){lastDiagnostic=millis();Serial.printf("{\"type\":\"direct\",\"http\":%d,\"polls\":%lu,\"commands\":%lu,\"responses\":%lu,\"failures\":%lu,\"heap\":%u,\"min_heap\":%u}\n",status.httpCode,(unsigned long)status.polls,(unsigned long)status.commands,(unsigned long)status.delivered,(unsigned long)status.failures,ESP.getFreeHeap(),ESP.getMinFreeHeap());}
    ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(ok?100:3000));
  }
}
#endif

static void bridgeTask(void *) {
#if KAI_DIRECT
  directTask();
  return;
#endif
  uint32_t wifiAttempt=millis(),lastMeasurementSend=0;
  for (;;) {
    if(WiFi.status()!=WL_CONNECTED) {
      if(!WiFi.STA.connected() && millis()-wifiAttempt>15000){
        measurementSample("reconnect");
        bool reconnectStarted=WiFi.reconnect();
        xSemaphoreTake(stateLock,portMAX_DELAY);
        ++wifiReconnectAttempts;if(!reconnectStarted)++wifiReconnectFailedCalls;
        xSemaphoreGive(stateLock);
        wifiAttempt=millis();
      }
      xSemaphoreTake(stateLock,portMAX_DELAY);bridgeStatus="offline";xSemaphoreGive(stateLock);
      vTaskDelay(pdMS_TO_TICKS(500));continue;
    }
    wifiAttempt=millis();
    String base=String("http://")+BRIDGE_HOST+":"+BRIDGE_PORT;
    sendQueuedChoice(base);

    // Snapshot the journal under the same mutex used by the UI and loop. New
    // samples can continue while the request is in flight; they are not part
    // of this acknowledgement and therefore cannot be lost.
    DiagnosticMeasurement outgoing[MEASUREMENT_CAPACITY];
    uint8_t outgoingCount = 0;
    xSemaphoreTake(stateLock, portMAX_DELAY);
    outgoingCount = measurementCount;
    for (uint8_t i = 0; i < outgoingCount; ++i) outgoing[i] = measurementJournal[i];
    xSemaphoreGive(stateLock);
    if (outgoingCount && millis()-lastMeasurementSend>=10000) {
      lastMeasurementSend=millis();
      JsonDocument payload;
      JsonArray values = payload["samples"].to<JsonArray>();
      for (uint8_t i = 0; i < outgoingCount; ++i) {
        JsonObject item = values.add<JsonObject>();
        item["boot_id"] = outgoing[i].bootId;
        item["seq"] = outgoing[i].seq;
        item["uptime_ms"] = outgoing[i].uptimeMs;
        item["battery_mv"] = outgoing[i].batteryMv;
        item["min_battery_mv"] = outgoing[i].minBatteryMv;
        item["wifi_status"] = outgoing[i].wifiStatus;
        item["rssi"] = outgoing[i].rssi;
        item["http_code"] = outgoing[i].httpCode;
        item["reset_reason"] = outgoing[i].resetReason;
        item["stage"] = outgoing[i].stage;
      }
      String body; serializeJson(payload, body);
      int measurementCode=bridgeRequest(base+"/device/measurements",body);
      if(measurementCode==200) {
        xSemaphoreTake(stateLock, portMAX_DELAY);
        uint8_t write=0;
        for(uint8_t i=0;i<measurementCount;++i) {
          bool acknowledged=false;
          for(uint8_t j=0;j<outgoingCount;++j) if((measurementJournal[i].seq == outgoing[j].seq && measurementJournal[i].bootId == outgoing[j].bootId)) {acknowledged=true;break;}
          if(!acknowledged) measurementJournal[write++]=measurementJournal[i];
        }
        measurementCount=write;
        xSemaphoreGive(stateLock);
      }
    }
    sendQueuedChoice(base);
    String stateUrl=base+"/state?compact=1&uptime_ms="+String(millis())+
      "&reset_reason="+String((int)esp_reset_reason())+
      "&wifi_rssi="+String(WiFi.RSSI());
    String body;int code=bridgeRequest(stateUrl,"",&body);
    JsonDocument incoming;bool valid=code==200&&!deserializeJson(incoming,body)&&incoming["summary"].is<const char*>();
    xSemaphoreTake(stateLock,portMAX_DELAY);
    lastHttpCode=code;
    if(valid){stateSuccesses++;lastBridgeMs=millis();bridgeStatus="online";}
    else {stateFailures++;bridgeStatus=(lastBridgeMs&&millis()-lastBridgeMs<15000)?"online":"offline";}
    if(valid){
      {
        JsonObject value=incoming["interaction"];
        // Keep the current answered question visible so its receipt does not remove
        // the page beneath the user's finger. Restore the latest answer on boot.
        String incomingId=value["id"].as<String>();
        bool currentAnswer=value["status"]=="selected"&&incomingId.length()&&(!interactionId.length()||incomingId==interactionId);
        bool retainAnswered=value.isNull()&&interactionStatus=="selected"&&interactionId.length()&&selectedChoice.length();
        if((value.isNull()&&!retainAnswered)||(!value.isNull()&&((value["source"]!="real"&&!incoming["demo_enabled"].as<bool>())||(value["status"]!="pending"&&!currentAnswer)))) {interactionId="";interactionText="";choiceCount=0;interactionStatus="";interactionArrived=false;selectedChoice="";interactionReceived=false;}
        else if(!value.isNull()) {
          String id=incomingId;
          if(id!=interactionId){interactionArrived=value["status"]=="pending";choiceSendStatus="";choiceSendId="";}
          interactionId=id;interactionText=value["text"].as<String>();
          interactionStatus=value["status"].as<String>();interactionSource=value["source"].as<String>();
          selectedChoice=value["selected_choice_id"].as<String>();
          interactionReceived=value["receipt_id"].is<const char*>()&&strlen(value["receipt_id"].as<const char*>())>0;
          JsonArray choices=value["choices"].as<JsonArray>();choiceCount=min((int)choices.size(),4);
          for(int i=0;i<choiceCount;i++){choiceIds[i]=choices[i]["id"].as<String>();choiceLabels[i]=choices[i]["label"].as<String>();}
        }
      }
      lastBridgeMs=millis();String m=jsonField(body,"summary");if(m.length())bridgeSummary=m;
      if(commandId.length() && jsonField(body,"reply_request_id")==commandId){commandStatus=jsonField(body,"reply_status");commandSummary=jsonField(body,"reply_summary");}
    }
    String cmd=pendingCommand;
    if(cmd.length()){pendingCommand="";commandStatus="sending";commandSummary="Macに問い合わせ中";}
    xSemaphoreGive(stateLock);
    sendQueuedChoice(base);
    if(cmd.length()) {
      char rid[40];snprintf(rid,sizeof(rid),"%08lx-%08lx",(unsigned long)esp_random(),(unsigned long)millis());
      String reply;
      int result=bridgeRequest(base+"/command",String("{\"id\":\"")+cmd+"\",\"request_id\":\""+rid+"\"}",&reply);
      xSemaphoreTake(stateLock,portMAX_DELAY);
      lastHttpCode=result;
      commandId=rid;commandAt=millis();
      commandStatus=result==200?jsonField(reply,"status"):"unknown";
      commandSummary=result==200?jsonField(reply,"summary"):"応答未確認。Macを確認してください";
      xSemaphoreGive(stateLock);
      Serial.printf("{\"type\":\"command\",\"request_id\":\"%s\",\"http\":%d}\n",rid,result);
    }
    ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(1200));
  }
}

static void serialCommand(String line) {
  line.trim(); if (!line.length()) return;
  if(line=="home"){setPageIndex(0);scrollX=0;settling=dragging=fingerDown=false;simulated=false;injectedUntil=0;render();return;}
  if(line=="power") {
    Serial.printf("{\"type\":\"power\",\"tx_power_qdbm\":%d,\"backlight_pwm\":%lu,\"battery_mv\":%lu}\n",(int)WiFi.getTxPower(),(unsigned long)ledcRead(GFX_BL),(unsigned long)analogReadMilliVolts(0)*3);
    return;
  }
  if(line=="link") {
    xSemaphoreTake(stateLock,portMAX_DELAY);
    Serial.printf("{\"type\":\"link\",\"wifi_sleep\":%d,\"successes\":%lu,\"failures\":%lu,\"age_ms\":%lu,\"http\":%d,\"heap\":%u}\n",(int)WiFi.getSleep(),(unsigned long)stateSuccesses,(unsigned long)stateFailures,(unsigned long)(lastBridgeMs?millis()-lastBridgeMs:0),lastHttpCode,ESP.getFreeHeap());
    xSemaphoreGive(stateLock);return;
  }
  if(line=="interaction") {
    xSemaphoreTake(stateLock,portMAX_DELAY);
    JsonDocument d;d["type"]="interaction";d["id"]=interactionId;d["status"]=interactionStatus;d["count"]=choiceCount;d["selected_choice_id"]=selectedChoice;d["send_status"]=choiceSendStatus;d["queue_ms"]=choiceQueueMs;d["http_ms"]=choiceHttpMs;d["total_ms"]=choiceTotalMs;d["attempts"]=choiceAttempts;d["scroll_px"]=questionScrollPx;d["text_lines"]=questionLineCount;serializeJson(d,Serial);Serial.println();
    xSemaphoreGive(stateLock);return;
  }
  if(line=="measurements") { serialMeasurements(); return; }
  if(line=="health") {
    xSemaphoreTake(stateLock,portMAX_DELAY);
    wl_status_t wifiStatus=WiFi.status();
    Serial.printf("{\"type\":\"health\",\"page\":%u,\"menu\":%u,\"theme\":\"%s\",\"dark\":%s,\"wifi\":%d,\"wifi_status\":%d,\"wifi_disconnect_reason\":%u,\"wifi_disconnect_count\":%lu,\"wifi_last_disconnect_ms\":%lu,\"wifi_first_connected_ms\":%lu,\"wifi_first_got_ip_ms\":%lu,\"first_valid_clock_ms\":%lu,\"first_tunnel_poll_ms\":%lu,\"wifi_reconnect_attempts\":%lu,\"wifi_reconnect_failed_calls\":%lu,\"min_heap\":%u,\"rssi\":%d,\"imu\":%d,\"touch\":%d,\"touch_samples\":%lu,\"gestures\":%lu,\"x\":%.1f,\"heap\":%u,\"uptime_ms\":%lu,\"reset_reason\":%d,\"last_http\":%d,\"bridge_task_created\":%s,\"bridge\":\"%s\",\"command_status\":\"%s\",\"request_id\":\"%s\",\"simulated\":%s}\n",page,menuPage,darkTheme?"dark":"normal",darkTheme?"true":"false",wifiStatus==WL_CONNECTED,wifiStatus,(unsigned)wifiLastDisconnectReason,(unsigned long)wifiDisconnectCount,(unsigned long)wifiLastDisconnectMs,(unsigned long)wifiFirstConnectedMs,(unsigned long)wifiFirstGotIpMs,(unsigned long)firstValidClockMs,(unsigned long)firstTunnelPollMs,(unsigned long)wifiReconnectAttempts,(unsigned long)wifiReconnectFailedCalls,ESP.getMinFreeHeap(),wifiStatus==WL_CONNECTED?WiFi.RSSI():0,imuReady,touchReady,(unsigned long)touchSamples,(unsigned long)gestureCount,characterX,ESP.getFreeHeap(),(unsigned long)millis(),(int)esp_reset_reason(),lastHttpCode,bridgeTaskCreated?"true":"false",bridgeStatus.c_str(),commandStatus.c_str(),commandId.c_str(),simulated?"true":"false");
    xSemaphoreGive(stateLock);return;
  }
  if (line == "screenshot") { serialScreenshot(); return; }
  if (line.startsWith("touch ")) { int x, y; if (sscanf(line.c_str(), "touch %d %d", &x, &y) == 2) handleTap(x, y, true); return; }
  if (line.startsWith("swipe ")) { int dx; if (sscanf(line.c_str(), "swipe %d", &dx) == 1) handleSwipe(dx, 0, true); return; }
  if(line=="neutral"){setNeutral();return;}
  if(line.startsWith("tilt ")){float x;if(sscanf(line.c_str(),"tilt %f",&x)==1){injectedGravity=constrain(x,-1.0f,1.0f);injectedUntil=millis()+6000;simulated=true;}return;}
  if(line.startsWith("down ")){int x,y;if(sscanf(line.c_str(),"down %d %d",&x,&y)==2)pointerDown(x,y,true);return;}
  if(line.startsWith("move ")){int x,y;if(fingerDown&&sscanf(line.c_str(),"move %d %d",&x,&y)==2)pointerMove(x,y);return;}
  if(line=="up"){pointerUp();return;}
  if(line=="motion"){
    Serial.printf("{\"type\":\"motion\",\"x\":%.2f,\"y\":%.2f,\"vx\":%.2f,\"vy\":%.2f,\"gx\":%.3f,\"gy\":%.3f,\"neutral_x\":%.3f,\"neutral_y\":%.3f,\"scroll\":%.2f,\"target\":%u,\"settling\":%s,\"frames\":%lu,\"render_us\":%lu,\"max_render_us\":%lu,\"simulated\":%s}\n",motion.x,motion.y,motion.vx,motion.vy,motion.gx,motion.gy,neutralX,neutralY,scrollX,targetPage,settling?"true":"false",(unsigned long)frameCount,(unsigned long)lastRenderUs,(unsigned long)maxRenderUs,simulated?"true":"false");return;
  }
}

void setup() {
  Serial.begin(115200); Serial.setTimeout(30); delay(100);
  preferences.begin("kai-ui", false); darkTheme=preferences.getBool("dark", true);
  measurementPreferences.begin("kai-meas", false);
  measurementBootId = String((uint32_t)esp_random(), HEX) + String((uint32_t)esp_random(), HEX);
  if (measurementBootId.length() > 64) measurementBootId.remove(64);
  stateLock = xSemaphoreCreateMutex();
  measurementLoad();
  ++measurementBootCounter;
  measurementBootId = String(measurementBootCounter) + "-" + measurementBootId;
  // Sequence numbers are scoped to the boot id; retained older boots keep
  // their original values for bridge deduplication.
  measurementSeq = 0;
  // Capture reset context before radio startup. The first two records are
  // immediately durable so a brownout during Wi-Fi init still leaves proof.
  measurementSample("boot", true);
  panel->begin(); lcdRegInit(); panel->setRotation(ROTATION); if(!gfx->begin(GFX_SKIP_OUTPUT_BEGIN)){Serial.println("FRAMEBUFFER_FAILED");while(true)delay(1000);} // Bound display load while Wi-Fi is transmitting on battery power.
  ledcAttach(GFX_BL, 5000, 8); ledcWrite(GFX_BL, 128);
  Wire.begin(TOUCH_SDA, TOUCH_SCL); Wire.setClock(400000);
  bsp_touch_init(&Wire, TOUCH_RST, TOUCH_INT, ROTATION, SCREEN_W, SCREEN_H);
  Wire.beginTransmission(AXS5106L_ADDR); touchReady=Wire.endTransmission()==0;
  imuReady = imu.init(calib, IMU_ADDRESS) == 0;
  motion.reset(KAI_W/2+4,77);
  bubbleLayout.reset(KAI_W/2+4,SCREEN_W/2.0f);
  motionUs=micros(); render();
  // Start the radio without association, then cap TX before the first connection.
  // Keep brownout protection enabled; reduce demand instead of hiding supply dips.
  measurementSample("before_wifi", true);
  WiFi.onEvent(wifiEvent);
  WiFi.STA.begin(false);
  WiFi.setTxPower(WIFI_POWER_13dBm);
  // Interactive replies need prompt receive; modem sleep adds AP buffering latency.
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  bridgeTaskCreated=xTaskCreatePinnedToCore(bridgeTask, "bridge", KAI_DIRECT?16384:8192, nullptr, 1, &bridgeTaskHandle, 0)==pdPASS;
  Serial.printf("{\"type\":\"diagnostics\",\"event\":\"boot\",\"uptime_ms\":%lu,\"reset_reason\":%d,\"wifi_status\":%d,\"bridge_task_created\":%s}\n",(unsigned long)millis(),(int)esp_reset_reason(),(int)WiFi.status(),bridgeTaskCreated?"true":"false");
}

void loop() {
  if (Serial.available()) serialCommand(Serial.readStringUntil('\n'));
  uint32_t now=millis();
  xSemaphoreTake(stateLock,portMAX_DELAY);bool arrived=interactionArrived;uint8_t nextPages=choiceCount?(choiceCount>2?6:5):4;interactionArrived=false;xSemaphoreGive(stateLock);
  if(PAGE_COUNT!=nextPages){PAGE_COUNT=nextPages;MAX_PAGE=PAGE_COUNT-1;setPageIndex(0);scrollX=0;}
  if(arrived){bubbleHidden=false;questionScrollPx=0;textDragging=false;fingerDown=dragging=false;slideTo(3);lastTouchMs=now;}
  if(imuReady&&now-sensorMs>=10){sensorMs=now;imu.update();imu.getAccel(&accelData);imu.getGyro(&gyroData);}
  if(now-measurementLastSampleMs>=1000){measurementLastSampleMs=now;measurementSample("sample");}
  measurementCheckpointIfDue();
  uint32_t tick=micros();float dt=(tick-motionUs)*.000001f;motionUs=tick;
  bool injecting=(int32_t)(injectedUntil-now)>0;
  ScreenGravity gravity=screenGravity(accelData.accelX,accelData.accelY);
  float gx=withHomeReturn(injecting?injectedGravity:gravity.right);
  float gy=injecting?0:gravity.down;
  motion.update(gx,gy,dt,KAI_W/2+4,SCREEN_W-KAI_W/2-4,70,88);
  bubbleLayout.update(motion.x,motion.vx,motion.vy,SCREEN_W/2.0f);
  characterX=motion.x;
  static uint32_t touchPoll=0;static bool hardwareDown=false;
  if(touchReady&&now-touchPoll>=10){
    touchPoll=now;uint8_t d[6]={0};
    Wire.beginTransmission(AXS5106L_ADDR);Wire.write(AXS5106L_TOUCH_DATA_REG);
    bool valid=Wire.endTransmission()==0&&Wire.requestFrom(AXS5106L_ADDR,(uint8_t)6)==6;
    if(valid){
      Wire.readBytes(d,6);bool pressed=d[1]>0&&d[1]<=2&&(d[2]>>6)!=1;
      if(pressed){
        int x=((d[4]&15)<<8)|d[5],y=((d[2]&15)<<8)|d[3];
        if(x<SCREEN_W&&y<SCREEN_H){
          touchSamples++;
          if(!hardwareDown){pointerDown(x,y,false);hardwareDown=true;}else pointerMove(x,y);
        }
      }else if(hardwareDown){hardwareDown=false;pointerUp();}
    }
  }
  if(page!=HOME&&!(targetPage>=3&&targetPage<MAX_PAGE)&&!fingerDown&&!settling&&(uint32_t)(millis()-lastTouchMs)>15000)slideTo(0);
  updateSlide();
  if(now-lastFrameMs>=25){lastFrameMs=now;render();}
  if (millis() - lastTelemetryMs > 3000) { lastTelemetryMs = millis(); Serial.printf("{\"type\":\"telemetry\",\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.3f,\"gy\":%.3f,\"gz\":%.3f,\"simulated\":%s}\n", accelData.accelX, accelData.accelY, accelData.accelZ, gyroData.gyroX, gyroData.gyroY, gyroData.gyroZ, simulated ? "true" : "false"); }
  delay(1);
}
