"""Exercise the actual DirectMCP handler with host JSON and fake NVS/network."""
from pathlib import Path
import argparse
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arduinojson', type=Path, default=Path.home() / 'Documents/Arduino/libraries/ArduinoJson/src', help='Installed ArduinoJson src directory')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = (root / "firmware/kai_companion/direct_mcp.h").read_text()
source = source.replace('#pragma once', '').replace('#include "direct_events.h"', '')
source = source.replace('#include "direct_tools.h"', '#include "' + str(root / 'firmware/kai_companion/direct_tools.h') + '"')
stub = r'''
#include <ArduinoJson.h>
#include <string>
#include <cassert>
#include <iostream>
using String=std::string;
#define PROGMEM
#define startsWith starts_with
class Preferences {
 public:
  bool fail=false,openFail=false; String stored;
  bool begin(const char*,bool) {return !openFail;}
  String getString(const char*,const char *fallback) {return stored.empty()?fallback:stored;}
  size_t putString(const char*,const String &s) {if(fail)return 0;stored=s;return s.size();}
};
struct DirectEvents {
  void begin(const char*) {}
  void provision(JsonVariantConst) {}
  void enqueue(const String&,const String&,const String&,int64_t) {}
  bool subscribe(JsonVariantConst,JsonObject) {return true;}
  bool unsubscribe(JsonVariantConst) {return true;}
  void status(JsonObject) const {}
};
struct {int RSSI(){return -60;}} WiFi;
struct {unsigned getFreeHeap(){return 100000;}} ESP;
unsigned millis(){return 100;}
'''
tests = r'''
JsonDocument call(DirectMCP &m,const char *name,JsonDocument &args) {
  JsonDocument rpc,result;
  rpc["id"]=1;rpc["method"]="tools/call";
  rpc["params"]["name"]=name;rpc["params"]["arguments"]=args;
  auto response=m.handle(rpc.as<JsonVariantConst>());
  assert(!deserializeJson(result,response));return result;
}
int main(){
  DirectMCP m;m.begin("","{}");JsonDocument a;
  a["question_id"]="q";a["text"]="続ける？";
  a["choices"][0]["id"]="yes";a["choices"][0]["label"]="はい";
  assert(call(m,"device_publish_question",a)["error"].isNull());
  a.clear();a["summary_id"]="s";a["text"]="進めてるよ";
  assert(call(m,"device_publish_summary",a)["error"].isNull());
  assert(m.state["question"]["status"]=="pending");
  assert(m.select("q","yes","real-request"));
  JsonDocument receipt;
  receipt["interaction_id"]="q";receipt["choice_id"]="yes";
  receipt["receipt_id"]="r";receipt["summary"]="受け取ったよ";
  assert(call(m,"device_record_receipt",receipt)["error"].isNull());
  assert(m.state["display_kind"]=="receipt");
  assert(call(m,"device_publish_summary",a)["result"]["structuredContent"]["idempotent"]==true);
  assert(m.state["summary"]=="進めてるよ");
  assert(m.state["display_kind"]=="summary");
  assert(m.state["answer"]["receipt_id"]=="r");
  JsonDocument diagArgs;
  auto diagDoc=call(m,"device_status",diagArgs);
  auto diag=diagDoc["result"]["structuredContent"].as<JsonObject>();
  // Status polling must not overwrite the last meaningful tool record.
  assert(diag["display_kind"]=="summary");assert(diag["summary_id"]=="s");
  assert(diag["answer_pending_receipt"]==false);
  assert(diag["last_tool"]=="device_publish_summary");assert(diag["last_tool_result"]=="ok");
  assert(diag["successful_summary_count"]==2);assert(diag["last_summary_time_status"]=="known");
  DirectMCP rebooted;rebooted.storage.stored=m.storage.stored;rebooted.begin("","{}");
  auto bootDiag=call(rebooted,"device_status",diagArgs);
  assert(bootDiag["result"]["structuredContent"]["last_summary_time_status"]=="unknown_after_restart");
  assert(bootDiag["result"]["structuredContent"]["last_summary_ms"].isNull());
  a["text"]="別の文";
  assert(call(m,"device_publish_summary",a)["error"]["code"]==-32602);
  String glyphs;for(int i=0;i<24;i++)glyphs+="あ";
  a["summary_id"]="limit";a["text"]=glyphs;
  assert(call(m,"device_publish_summary",a)["error"].isNull());
  a["summary_id"]="over";a["text"]=glyphs+"あ";
  assert(call(m,"device_publish_summary",a)["error"]["code"]==-32602);
  String before;serializeJson(m.state,before);
  m.storage.fail=true;a["summary_id"]="failed";a["text"]="保存失敗";
  assert(call(m,"device_publish_summary",a)["error"]["code"]==-32000);
  String after;serializeJson(m.state,after);assert(before==after);
  for(const char *saved : {"{broken", "[]", "null"}) {
    DirectMCP damaged;damaged.storage.stored=saved;
    damaged.begin("","{}");
    assert(!damaged.ready);
    a.clear();a["question_id"]="replacement";a["text"]="New?";
    a["choices"][0]["id"]="yes";a["choices"][0]["label"]="Yes";
    assert(call(damaged,"device_publish_question",a)["error"]["code"]==-32000);
    assert(call(damaged,"device_read_answer",a)["error"]["code"]==-32000);
    assert(!damaged.select("replacement","yes","req"));
    assert(!damaged.save());assert(damaged.storage.stored==saved);
    assert(call(damaged,"device_status",a)["result"]["structuredContent"]["storage_ready"]==false);
  }
  DirectMCP unavailable;unavailable.storage.openFail=true;
  unavailable.begin("","{}");assert(!unavailable.ready);assert(!unavailable.save());
  std::cout<<"PASS: pending question preserved, receipt/summary precedence, idempotent restore, Unicode limit, persistence rollback\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    test = Path(directory) / "summary.cpp"
    test.write_text(stub + source + tests)
    binary = Path(directory) / "summary"
    subprocess.run(["c++", "-std=c++20", "-I", str(args.arduinojson), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
