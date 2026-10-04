#pragma once
#include <time.h>
#include "direct_tools.h"
#include "direct_events.h"

// One durable question and answer. Never replace an unreceipted answer.
class DirectMCP {
 public:
  Preferences storage;
  JsonDocument state;
  DirectEvents events;
  void begin(const char *ca, const char *subscription) {
    storage.begin("kai-direct", false);
    String saved=storage.getString("state", "{}");
    if(deserializeJson(state,saved))state.clear();
    events.begin(ca);
    JsonDocument sub; if(!deserializeJson(sub,subscription))events.provision(sub.as<JsonVariantConst>());
  }
  bool save(){String value;serializeJson(state,value);return storage.putString("state",value)==value.length();}
  bool restore(const String &snapshot) {
    state.clear();
    return !deserializeJson(state, snapshot);
  }
  static bool validChoices(JsonArrayConst choices) {
    String ids[4];
    size_t index = 0;
    for (JsonObjectConst choice : choices) {
      if (!choice["id"].is<const char*>() || !choice["label"].is<const char*>()) return false;
      String id = choice["id"].as<String>(), label = choice["label"].as<String>();
      if (!id.length() || id.length() > 48 || !label.length() || label.length() > 128) return false;
      for (size_t previous = 0; previous < index; ++previous) if (ids[previous] == id) return false;
      ids[index++] = id;
    }
    return true;
  }
  static size_t unicodeCodepointCount(const String &text) {
    size_t count = 0;
    for (size_t i = 0; i < text.length();) {
      uint8_t byte = static_cast<uint8_t>(text[i]);
      size_t width = (byte < 0x80) ? 1 : ((byte & 0xE0) == 0xC0 ? 2 : ((byte & 0xF0) == 0xE0 ? 3 : ((byte & 0xF8) == 0xF0 ? 4 : 1)));
      if (i + width > text.length()) width = 1;
      i += width;
      ++count;
    }
    return count;
  }
  bool select(const String &qid,const String &cid,const String &rid) {
    String snapshot;serializeJson(state,snapshot);
    JsonObject q=state["question"].as<JsonObject>();
    if(q["id"]!=qid||q["status"]!="pending")return false;
    bool found=false;for(JsonObject c:q["choices"].as<JsonArray>())if(c["id"]==cid)found=true;
    if(!found)return false;
    q["status"]="selected";q["selected_choice_id"]=cid;
    const time_t selectedAt=time(nullptr);
    JsonObject a=state["answer"].to<JsonObject>();
    a["interaction_id"]=qid;a["choice_id"]=cid;a["request_id"]=rid;
    a["origin_request_id"]=qid;a["source"]="real";
    a["selected_at"]=selectedAt>=1700000000?(int64_t)selectedAt:(int64_t)0;
    a["receipt_id"]=nullptr;a["receipt_summary"]=nullptr;
    if(!save()){restore(snapshot);return false;}
    events.enqueue(qid,cid,rid,selectedAt>=1700000000?(int64_t)selectedAt:(int64_t)0);
    return true;
  }
  String handle(JsonVariantConst rpc) {
    String method=rpc["method"]|"";
    if(method.startsWith("notifications/"))return "";
    JsonDocument out;out["jsonrpc"]="2.0";out["id"]=rpc["id"];
    JsonObject result=out["result"].to<JsonObject>();
    JsonVariantConst p=rpc["params"];
    int error=0;const char *message="Invalid request";
    if(method=="initialize") {
      result["protocolVersion"]="2026-07-28";
      result["capabilities"]["tools"]["listChanged"]=false;
      result["capabilities"]["events"].to<JsonObject>();
      result["serverInfo"]["name"]="kai-device";result["serverInfo"]["version"]="1.1.0";
    } else if(method=="ping"){}
    else if(method=="server/discover") {
      result["resultType"]="complete";result["supportedVersions"].to<JsonArray>().add("2026-07-28");
      result["capabilities"]["tools"].to<JsonObject>();result["capabilities"]["events"].to<JsonObject>();
    } else if(method=="tools/list") {JsonDocument tools;deserializeJson(tools,DIRECT_TOOLS);result["tools"]=tools;}
    else if(method=="events/list") {
      JsonObject event=result["events"].to<JsonArray>().add<JsonObject>();
      event["name"]="device.answer";event["description"]="A new real answer was selected on the KAI device.";
      event["delivery"].to<JsonArray>().add("webhook");
      event["inputSchema"]["type"]="object";event["inputSchema"]["properties"].to<JsonObject>();event["inputSchema"]["additionalProperties"]=false;
      event["payloadSchema"]["type"]="object";
      JsonArray required=event["payloadSchema"]["required"].to<JsonArray>();
      for(const char *key:{"answerId","questionId","choiceId"}){event["payloadSchema"]["properties"][key]["type"]="string";required.add(key);}
      result["nextCursor"]=nullptr;
    } else if(method=="events/subscribe") {if(!events.subscribe(p,result)){error=-32015;message="CallbackEndpointError";}}
    else if(method=="events/unsubscribe") {if(!events.unsubscribe(p)){error=-32602;message="Invalid unsubscribe request";}}
    else if(method=="tools/call") {
      String name=p["name"]|"";JsonVariantConst args=p["arguments"];
      JsonObject value=result["structuredContent"].to<JsonObject>();
      if(name=="device_status") {
        value["status"]="online";value["transport"]="esp32-direct";value["wifi_rssi"]=WiFi.RSSI();value["uptime_ms"]=millis();value["free_heap"]=ESP.getFreeHeap();
        events.status(value["events"].to<JsonObject>());
      }else if(name=="device_publish_question") {
        String id=args["question_id"]|"",text=args["text"]|"";JsonArrayConst choices=args["choices"].as<JsonArrayConst>();
        bool valid=id.length()>0&&id.length()<=128&&text.length()>0&&text.length()<=4096&&choices.size()>=1&&choices.size()<=4&&validChoices(choices);
        JsonVariantConst current=state["question"];
        if(!valid){error=-32602;message="Invalid question";}
        else if(current["id"]==id) {
          String oldChoices,newChoices;serializeJson(current["choices"],oldChoices);serializeJson(choices,newChoices);
          if(current["text"]!=text||oldChoices!=newChoices){error=-32602;message="Question ID conflict";}
          else {value["status"]=current["status"];value["interaction"]=current;value["idempotent"]=true;}
        }else if((current["status"]=="selected"&&(state["answer"].isNull()||state["answer"]["receipt_id"].isNull()))||(!state["answer"].isNull()&&state["answer"]["receipt_id"].isNull())){error=-32000;message="Previous answer awaits receipt";}
        else {
          String snapshot;serializeJson(state,snapshot);
          JsonObject q=state["question"].to<JsonObject>();q["id"]=id;q["text"]=text;q["choices"]=choices;q["status"]="pending";q["source"]="real";q["selected_choice_id"]="";q["receipt_id"]=nullptr;
          state["display_kind"]="question";
          if(!save()){restore(snapshot);error=-32000;message="Question persistence failed";}
          else {value["status"]="pending";value["interaction"]=q;}
        }
      }else if(name=="device_publish_summary") {
        String id=args["summary_id"]|"",text=args["text"]|"";
        bool valid=id.length()>0&&id.length()<=128&&text.length()>0&&unicodeCodepointCount(text)<=24;
        JsonVariantConst currentId=state["summary_id"];
        JsonVariantConst currentText=state["summary_text"];
        if(!valid){error=-32602;message="Invalid summary";}
        else if(currentId==id) {
          if(currentText!=text){error=-32602;message="Summary ID conflict";}
          else {
            String snapshot;serializeJson(state,snapshot);
            state["summary"]=text;
            state["display_kind"]="summary";
            if(!save()){restore(snapshot);error=-32000;message="Summary persistence failed";}
            else {value["status"]="shown";value["id"]=id;value["summary_id"]=id;value["idempotent"]=true;}
          }
        } else {
          String snapshot;serializeJson(state,snapshot);
          state["summary_id"]=id;state["summary_text"]=text;state["summary"]=text;state["display_kind"]="summary";
          if(!save()){restore(snapshot);error=-32000;message="Summary persistence failed";}
          else {value["status"]="shown";value["id"]=id;value["summary_id"]=id;}
        }
      }else if(name=="device_read_answer") {
        JsonArray a=value["answers"].to<JsonArray>();
        JsonObjectConst readArgs=args.as<JsonObjectConst>();
        bool hasQuestionId=readArgs.containsKey("question_id");
        String questionId=readArgs["question_id"]|"";
        bool validQuestionId=!hasQuestionId||(readArgs["question_id"].is<const char*>()&&questionId.length()>=1&&questionId.length()<=128);
        if(!validQuestionId){error=-32602;message="Invalid question_id";}
        else if(!state["answer"].isNull()&&(!hasQuestionId||state["answer"]["interaction_id"]==questionId))a.add(state["answer"]);
      }else if(name=="device_record_receipt") {
        JsonObject a=state["answer"].as<JsonObject>();String rid=args["receipt_id"]|"",summary=args["summary"]|"";
        if(a.isNull()||a["interaction_id"]!=args["interaction_id"]||a["choice_id"]!=args["choice_id"]||!rid.length()||!summary.length()) {error=-32602;message="Receipt does not match real answer";}
        else if(!a["receipt_id"].isNull()&&(a["receipt_id"]!=rid||a["receipt_summary"]!=summary)){error=-32000;message="Receipt already recorded";}
        else if(!a["receipt_id"].isNull()) {value["status"]="received";}
        else {
          String snapshot;serializeJson(state,snapshot);
          a["receipt_id"]=rid;a["receipt_summary"]=summary;a["receipt_at"]=(int64_t)time(nullptr);
          JsonObject currentQuestion=state["question"].as<JsonObject>();
          if(!currentQuestion.isNull()&&currentQuestion["id"]==a["interaction_id"]) {
            currentQuestion["receipt_id"]=rid;state["summary"]=summary;
          }
          state["display_kind"]="receipt";
          if(!save()){restore(snapshot);error=-32000;message="Receipt persistence failed";}
          else value["status"]="received";
        }
      }else{error=-32602;message="Unknown tool";}
      JsonObject c=result["content"].to<JsonArray>().add<JsonObject>();c["type"]="text";c["text"]="Device operation completed.";
    }else{error=-32601;message="Method not found";}
    if(error){out.remove("result");out["error"]["code"]=error;out["error"]["message"]=message;}
    String encoded;serializeJson(out,encoded);return encoded;
  }
};
