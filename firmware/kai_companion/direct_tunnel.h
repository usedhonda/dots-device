#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <functional>

// Wire evidence: tunnel-client/pkg/controlplane/{internal/tunnel_service_client.go,
// internal/roundtripper.go,wiretypes/wire.go}, pkg/version/version.go.
// Caller must supply the actual HTTPS control-plane base URL, CA PEM, key and
// tunnel ID. Synchronize the ESP32 clock before TLS. Call from one task only.
class KaiDirectTunnel {
 public:
  using Handler = std::function<String(JsonVariantConst)>;
  struct Status {
    uint32_t polls=0, commands=0, delivered=0, failures=0, unsupported=0;
    int httpCode=0;
    uint32_t freeHeap=0;
  };
  KaiDirectTunnel(const String& base, const String& key, const String& id,
                  const char* ca, const String& instance)
      : base_(base), key_(key), id_(id), instance_(instance), ca_(ca) {
    while (base_.endsWith("/")) base_.remove(base_.length()-1);
  }
  const Status& status() const { return status_; }
  // Returns false on transport/protocol failure. No credentials or RPC payload
  // are exposed in status. Failed delivery remains pending for the next call.
  bool pollOnce(const Handler& handler) {
    status_.freeHeap=ESP.getFreeHeap();
    if (!pending_.isEmpty()) return deliver();
    if (!handler || !configured()) return fail();
    if (backlog_.isEmpty()) {
    NetworkClientSecure tls; HTTPClient http;
    if (!begin(tls,http,"/poll?limit=1&timeout_ms=5000")) return fail();
    if (!route_.isEmpty()) http.addHeader("X-Tunnel-Shard-Token",route_);
    const char* collected[]={"X-Tunnel-Shard-Token"};
    http.collectHeaders(collected,1);
    ++status_.polls;
    status_.httpCode=http.GET();
    if (status_.httpCode==204) { http.end(); return true; }
    const String correction=http.header("X-Tunnel-Shard-Token");
    if (status_.httpCode!=200 && status_.httpCode!=409) { http.end(); return fail(); }
    BoundedBody body;
    const int bytes=http.writeToStream(&body);
    http.end();
    if (bytes<0 || body.overflow) return fail();
    if (status_.httpCode==200) { backlog_=body.value; nextCommand_=0; }
    else {
    DynamicJsonDocument doc(kJsonCapacity);
    if (deserializeJson(doc,body.value) || doc.overflowed()) return fail();
    if (status_.httpCode==409) {
      JsonObjectConst error=doc["error"];
      uint64_t revision=error["policy_revision"] | UINT64_MAX;
      String copied=error["shard_token"] | correction;
      if (String(error["code"] | "")=="wrong_cluster" &&
          !correction.isEmpty() && correction.length()<=4096 &&
          correction.indexOf('\r')<0 && correction.indexOf('\n')<0 &&
          copied==correction && revision<=9007199254740991ULL && revision>=routeRevision_) {
        route_=correction; routeRevision_=revision;
      }
      return fail(); // Caller retries the same endpoint on its normal schedule.
    }
    }
    }
    DynamicJsonDocument doc(kJsonCapacity);
    if (deserializeJson(doc,backlog_) || doc.overflowed()) return fail();
    JsonArrayConst commands=doc["commands"].as<JsonArrayConst>();
    if (commands.isNull()) return fail();
    // Process every returned command: limit=1 is only a server hint.
    size_t commandIndex=0;
    for (JsonObjectConst command: commands) {
      if (commandIndex++<nextCommand_) continue;
      ++status_.commands;
      const char* type=command["command_type"] | "";
      if (strcmp(type,"jsonrpc")!=0) { ++status_.unsupported; ++nextCommand_; continue; }
      String request=command["request_id"] | "";
      String shard=command["shard_token"] | "";
      String channel=command["channel"] | "";
      JsonVariantConst rpc=command["jsonrpc"];
      if (request.isEmpty() || shard.isEmpty() || channel.isEmpty() || !rpc.is<JsonObjectConst>()) return fail();
      String result=handler(rpc);
      const bool notification=rpc["id"].isNull();
      if (result.length()>kBodyLimit || (result.isEmpty() && !notification)) return fail();
      DynamicJsonDocument wrapper(kJsonCapacity);
      wrapper["request_id"]=request;
      wrapper["channel"]=channel;
      wrapper["resp_type"]=notification && result.isEmpty() ? "notify_ack" : "jsonrpc_response";
      wrapper["resp_code"]=200;
      if (!result.isEmpty()) {
        DynamicJsonDocument response(kJsonCapacity);
        if (deserializeJson(response,result) || response.overflowed() || !response.is<JsonObject>()) return fail();
        wrapper["resp_json"]=response.as<JsonVariantConst>();
      }
      if (wrapper.overflowed() || measureJson(wrapper)>kBodyLimit) return fail();
      serializeJson(wrapper,pending_);
      ++nextCommand_;
      pendingShard_=shard; // Echo the command token, never a learned poll token.
      if (!deliver()) return false;
    }
    backlog_=""; nextCommand_=0;
    return true;
  }
 private:
  static constexpr size_t kBodyLimit=12288, kJsonCapacity=24576;
  // HTTPClient.writeToStream handles chunked framing. Cap its decoded output
  // rather than getString(), which can allocate an unbounded response body.
  class BoundedBody : public Stream {
   public:
    String value; bool overflow=false;
    BoundedBody() { value.reserve(kBodyLimit); }
    size_t write(uint8_t c) override { return write(&c,1); }
    size_t write(const uint8_t* data,size_t length) override {
      if (length>kBodyLimit-value.length()) { overflow=true; return 0; }
      if (!value.concat(reinterpret_cast<const char*>(data),length)) { overflow=true; return 0; }
      return length;
    }
    int available() override { return 0; }
    int read() override { return -1; }
    int peek() override { return -1; }
    void flush() override {}
  };
  bool configured() const {
    return base_.startsWith("https://") && !key_.isEmpty() && !id_.isEmpty()
        && ca_ && ca_[0] && !instance_.isEmpty();
  }
  static String escapeSegment(const String& value) {
    const char hex[]="0123456789ABCDEF"; String out;
    for (size_t i=0;i<value.length();++i) {
      const uint8_t c=value[i];
      if ((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'||c=='~') out+=char(c);
      else { out+='%'; out+=hex[c>>4]; out+=hex[c&15]; }
    }
    return out;
  }
  bool begin(NetworkClientSecure& tls,HTTPClient& http,const String& suffix) {
    if (!configured()) return false;
    tls.setCACert(ca_); // Deliberately no insecure TLS fallback.
    tls.setHandshakeTimeout(15);
    if (!http.begin(tls,base_+"/v1/tunnels/"+escapeSegment(id_)+suffix)) return false;
    http.setConnectTimeout(10000); http.setTimeout(15000);
    http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    http.addHeader("Authorization","Bearer "+key_);
    http.addHeader("Accept","application/json");
    http.addHeader("User-Agent","kai-direct-tunnel/0.1.0");
    http.addHeader("X-Tunnel-Client-Name","kai-direct-tunnel");
    http.addHeader("X-Tunnel-Client-Version","0.1.0");
    http.addHeader("X-Tunnel-Client-Wire-Protocol-Version","2026-08-25");
    http.addHeader("X-Tunnel-Client-Instance-Id",instance_);
    // No capability claim: advanced wrong-cluster routing is not implemented.
    return true;
  }
  bool deliver() {
    NetworkClientSecure tls; HTTPClient http;
    if (!begin(tls,http,"/response")) return fail();
    http.addHeader("Content-Type","application/json");
    http.addHeader("X-Tunnel-Shard-Token",pendingShard_);
    status_.httpCode=http.POST(pending_);
    http.end();
    if (status_.httpCode<200 || status_.httpCode>=300) return fail();
    pending_=""; pendingShard_=""; ++status_.delivered;
    return true;
  }
  bool fail() { ++status_.failures; status_.freeHeap=ESP.getFreeHeap(); return false; }
  String base_,key_,id_,instance_,route_,pending_,pendingShard_,backlog_;
  size_t nextCommand_=0;
  uint64_t routeRevision_=0;
  const char* ca_;
  Status status_;
};
