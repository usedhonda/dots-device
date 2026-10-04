"""Compile and exercise the extracted answer-page branch from the firmware."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "firmware/kai_companion/kai_companion.ino").read_text()
start = source.index('  if(targetPage>=3&&targetPage<MAX_PAGE) {', source.index('static void handleTap('))
end = source.index('  if(y<12||y>118||x<12||x>308', start)
branch = source[start:end]

harness = r'''
#include <cassert>
#include <cstdint>
#include <string>
using std::string;
struct String {
  string v;
  String() = default; String(const char *s):v(s?s:"") {} String(const string &s):v(s) {}
  String(uint32_t n):v(std::to_string(n)) {} String(uint32_t n, int):v(std::to_string(n)) {}
  size_t length() const { return v.length(); }
  String &operator=(const char *s) { v=s?s:""; return *this; }
  String &operator=(const String&) = default;
  bool operator==(const String &o) const { return v==o.v; }
  bool operator==(const char *s) const { return v==(s?s:""); }
  bool operator!=(const char *s) const { return !(*this==s); }
  friend String operator+(const String &a,const String &b){return String(a.v+b.v);}
};
static constexpr int HEX=16, MAX_PAGE=4, portMAX_DELAY=0, ANSWER_X=204, ANSWER_W=104, ANSWER_Y=12, ANSWER_H=60, ANSWER_STEP=72;
using SemaphoreHandle_t=void*;
SemaphoreHandle_t stateLock=nullptr; void *bridgeTaskHandle=nullptr;
uint8_t targetPage=3, page=3, choiceCount=2; bool settling=false, dragging=false, textDragging=false;
bool interruptedSlide=false; int startTouchX=210,startTouchY=20,lastFingerX=210,lastFingerY=20;
bool simulated=false; uint32_t lastTouchMs=0, gestureCount=0; float scrollX=0; int homeCalls=0, renders=0, notifies=0;
String interactionId, drawnInteractionId, interactionStatus, selectedChoice;
String choiceIds[4], choiceSendId, choiceSendInteraction, choiceSendValue, choiceSendStatus;
uint32_t choiceRetryAt=0, choiceQueuedAt=0, choiceQueueMs=0, choiceHttpMs=0, choiceTotalMs=0, choiceAttempts=0;
uint32_t millis(){return 123;} uint32_t esp_random(){return 7;}
void xSemaphoreTake(SemaphoreHandle_t,int){} void xSemaphoreGive(SemaphoreHandle_t){}
void xTaskNotifyGive(void*){notifies++;}
void setPageIndex(uint8_t i){page=i;targetPage=i;if(i==0)homeCalls++;} void render(){renders++;}
void tap(int x,int y) {
'''+branch+r'''
}
void reset(const char *status,const char *selected,const char *sendStatus,const char *sendInteraction,const char *sendValue,const char *drawn="q1") {
  page=targetPage=3; homeCalls=renders=notifies=0; bridgeTaskHandle=(void*)1; interactionId="q1"; drawnInteractionId=drawn;
  interactionStatus=status; selectedChoice=selected; choiceSendStatus=sendStatus;
  choiceSendInteraction=sendInteraction; choiceSendValue=sendValue; choiceSendId="";
  choiceIds[0]="yes"; choiceIds[1]="no";
}
int main(){
  reset("selected","yes","","","", "q1"); tap(210,20); assert(page==0&&homeCalls==1&&choiceSendId.length()==0&&notifies==0);
  reset("pending","","sending","q1","yes"); tap(210,20); assert(page==0&&choiceSendId.length()==0&&notifies==0);
  reset("selected","yes","","","", "q1"); tap(210,92); assert(page==3&&homeCalls==0&&notifies==0);
  reset("pending","","","","", "q1"); tap(210,20); assert(page==0&&choiceSendStatus=="queued"&&choiceSendValue=="yes"&&notifies==1);
  reset("selected","yes","","","", "stale"); tap(210,20); assert(page==3&&homeCalls==0&&choiceSendId.length()==0&&notifies==0);
}
'''

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    cpp = root / "test.cpp"
    exe = root / "test"
    cpp.write_text(harness)
    subprocess.run(["c++", "-std=c++11", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS extracted handleTap branch: selected/in-flight return home, unselected/stale inert, pending queues once")
