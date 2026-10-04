#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <esp_system.h>
#include <mbedtls/base64.h>
#include <mbedtls/md.h>
#include <time.h>

// One subscription and one durable event. enqueue() returns false while the
// slot is occupied; callers must retain their answer and retry enqueue later.
// NVS contains webhook secrets: never dump this namespace to serial/logs.
class DirectEvents {
 public:
  bool begin(const char *ca) {
    ca_ = ca;
    ready_ = ca && *ca && prefs_.begin("kai-events", false);
    if (!ready_) return false;
    String saved = prefs_.getString("state", "");
    if (saved.length() && deserializeJson(state_, saved)) {
      ready_ = false; // Do not overwrite malformed durable state.
      return false;
    }
    return true;
  }

  // Trusted local provisioning imports an already verified Python subscription.
  // A saved empty/revoked state takes precedence over the initial provisioning.
  bool provision(JsonVariantConst sub) {
    if (!ready_) return false;
    if (prefs_.isKey("state")) return true;
    if (!validSubscription(sub) || String(sub["id"].as<const char *>()) != subscriptionId(sub["url"].as<String>())) return false;
    state_["subscription"].set(sub);
    state_.remove("outbox");
    return save();
  }

  bool subscribe(JsonVariantConst params, JsonObject result) {
    if (!ready_ || !clockReady() || !validParams(params) || !params["cursor"].isNull()) return false;
    JsonVariantConst delivery = params["delivery"];
    String url = delivery["url"].as<String>(), secret = delivery["secret"].as<String>();
    int64_t ttl = params["ttlMs"].isNull() ? 86400000 : params["ttlMs"].as<int64_t>();
    if ((!params["ttlMs"].isNull() && !params["ttlMs"].is<int64_t>()) || ttl < 60000 || ttl > 2592000000LL || !allowedUrl(url) || !validSecret(secret)) return false;
    String sid = subscriptionId(url), challenge = randomId(24);
    JsonDocument verification, response;
    verification["challenge"] = challenge;
    verification["type"] = "verification";
    String body;
    serializeJson(verification, body);
    int code = post(url, secret, sid, "ver_" + randomId(16), body, response, false);
    if (code < 200 || code >= 300 || !response["challenge"].is<String>() || response["challenge"].as<String>() != challenge) return false;
    JsonVariant old = state_["subscription"];
    String oldId = old["id"].as<String>(), oldSecret = old["secret"].as<String>();
    String previous = old["previousSecret"].as<String>();
    double rotationUntil = old["rotationUntil"] | 0.0;
    if (oldId.length() && oldId != sid && activeOutbox()) return false;
    JsonObject sub = state_["subscription"].to<JsonObject>();
    sub["id"] = sid; sub["url"] = url; sub["secret"] = secret;
    sub["expiresAt"] = double(time(nullptr)) + double(ttl) / 1000.0;
    if (oldId == sid && oldSecret != secret) {
      sub["previousSecret"] = oldSecret;
      sub["rotationUntil"] = double(time(nullptr)) + 60;
    } else if (oldId == sid && previous.length() && rotationUntil > time(nullptr)) {
      sub["previousSecret"] = previous; sub["rotationUntil"] = rotationUntil;
    }
    if (!save()) return false;
    result["id"] = sid; result["refreshBefore"] = isoTime(time(nullptr) + ttl / 1000);
    result["cursor"] = nullptr; result["truncated"] = false;
    return true;
  }

  bool unsubscribe(JsonVariantConst params) {
    if (!ready_ || !validParams(params)) return false;
    String url = params["delivery"]["url"].as<String>();
    if (!allowedUrl(url)) return false;
    if (state_["subscription"]["id"].as<String>() == subscriptionId(url)) {
      state_.remove("subscription");
      if (activeOutbox()) state_["outbox"]["status"] = "revoked";
    }
    return save();
  }

  bool enqueue(const String &interactionId, const String &choiceId,
               const String &requestId, int64_t selectedAt) {
    return enqueue(interactionId, choiceId, requestId,
                   selectedAt > 0 ? isoTime(static_cast<time_t>(selectedAt)) : String());
  }

  bool enqueue(const String &interactionId, const String &choiceId,
               const String &requestId, const String &selectedAt) {
    if (!ready_ || !clockReady() || !interactionId.length() || !choiceId.length() ||
        interactionId.length() > 512 || choiceId.length() > 512 || requestId.length() > 512 || selectedAt.length() > 64 ||
        !validSubscription(state_["subscription"]) || double(state_["subscription"]["expiresAt"]) <= time(nullptr)) return false;
    String aid = interactionId + ":" + choiceId + ":" + requestId;
    if (state_["outbox"]["payload"]["data"]["answerId"].as<String>() == aid) return true;
    if (activeOutbox()) return false;
    String sid = state_["subscription"]["id"].as<String>();
    JsonObject item = state_["outbox"].to<JsonObject>();
    item["subscription"] = sid; item["attempts"] = 0;
    item["nextAt"] = double(time(nullptr)); item["status"] = "pending";
    // Lexical key insertion matches events.py sort_keys=True canonical bytes.
    JsonObject payload = item["payload"].to<JsonObject>();
    payload["cursor"] = nullptr;
    JsonObject data = payload["data"].to<JsonObject>();
    data["answerId"] = aid; data["choiceId"] = choiceId;
    data["questionId"] = interactionId;
    if (requestId.length()) data["requestId"] = requestId;
    else data["requestId"] = nullptr;
    data["summary"] = nullptr;
    payload["eventId"] = "evt_" + digest(sid, aid).substring(0, 32);
    payload["name"] = "device.answer";
    payload["timestamp"] = selectedAt.length() ? selectedAt : isoTime(time(nullptr));
    return save();
  }

  // Call from a network worker, not the animation/render task: TLS can block.
  void pump() {
    if (!ready_ || !clockReady() || !activeOutbox()) return;
    JsonVariant item = state_["outbox"], sub = state_["subscription"];
    if (!validSubscription(sub) || double(sub["expiresAt"]) <= time(nullptr) || item["subscription"].as<String>() != sub["id"].as<String>()) {
      item["status"] = "revoked"; save(); return;
    }
    unsigned attempts = item["attempts"] | 0U;
    if (attempts >= 5) { item["status"] = "terminal"; save(); return; }
    if (double(item["nextAt"]) > time(nullptr)) return;
    item["attempts"] = ++attempts; item["status"] = "unknown";
    if (!save()) return; // Persist attempt before transmitting, including resets.
    String body; serializeJson(item["payload"], body);
    JsonDocument response;
    int code = post(sub["url"].as<String>(), sub["secret"].as<String>(), sub["id"].as<String>(), item["payload"]["eventId"].as<String>(), body, response, true);
    state_["lastHttp"] = code;
    if (code >= 200 && code < 300) {
      item["status"] = "sent";
      state_["sent"] = (state_["sent"] | 0U) + 1;
    } else if (attempts >= 5 || code == 410 || code == 413 || (code >= 400 && code < 500 && code != 408 && code != 429)) {
      item["status"] = "terminal";
      state_["failed"] = (state_["failed"] | 0U) + 1;
    } else {
      item["status"] = "pending"; item["nextAt"] = double(time(nullptr)) + (1U << attempts);
    }
    save();
  }

  bool delivered(const String &questionId, const String &choiceId, const String &requestId) const {
    return state_["outbox"]["status"] == "sent" &&
      state_["outbox"]["payload"]["data"]["answerId"].as<String>() == questionId + ":" + choiceId + ":" + requestId;
  }

  void status(JsonObject result) const {
    result["ready"] = ready_; result["subscribed"] = !state_["subscription"].isNull();
    result["sent"] = state_["sent"] | 0U; result["failed"] = state_["failed"] | 0U;
    result["attempts"] = state_["outbox"]["attempts"] | 0U;
    result["outbox"] = state_["outbox"]["status"] | "empty";
    result["lastHttp"] = state_["lastHttp"] | 0;
  }

 private:
  class BoundedResponse : public Stream {
   public:
    String body;
    size_t write(uint8_t value) override {
      if (body.length() >= 4096) return 0;
      body += static_cast<char>(value); return 1;
    }
    size_t write(const uint8_t *data, size_t count) override {
      if (count > 4096 - body.length()) return 0;
      return body.concat(reinterpret_cast<const char *>(data), count) ? count : 0;
    }
    int available() override { return 0; }
    int read() override { return -1; }
    int peek() override { return -1; }
    void flush() override {}
  };
  Preferences prefs_;
  JsonDocument state_;
  const char *ca_ = nullptr;
  bool ready_ = false;
  bool save() {
    String raw; serializeJson(state_, raw);
    if (prefs_.putString("state", raw) != raw.length()) { ready_ = false; return false; }
    return true;
  }
  static bool clockReady() { return time(nullptr) >= 1700000000; }
  bool activeOutbox() const {
    String s = state_["outbox"]["status"] | "";
    return s == "pending" || s == "unknown";
  }
  static bool allowedUrl(const String &url) {
    // Exact hostname, implicit HTTPS port 443; never credentials/redirects.
    if (!url.startsWith("https://connectors.api.openai.com/") || url.length() > 2048) return false;
    for (size_t i = 0; i < url.length(); ++i)
      if (url[i] <= 32 || url[i] == 127 || url[i] == '#' || url[i] == '\\') return false;
    return true;
  }
  static bool validParams(JsonVariantConst p) {
    return p.is<JsonObjectConst>() && p["name"].as<String>() == "device.answer" &&
      (p["arguments"].isNull() || (p["arguments"].is<JsonObjectConst>() && p["arguments"].size() == 0)) &&
      p["delivery"].is<JsonObjectConst>() && p["delivery"]["mode"].as<String>() == "webhook" && p["delivery"]["url"].is<String>();
  }
  static bool validSecret(const String &secret) {
    uint8_t key[64]; size_t n = 0;
    return decodeSecret(secret, key, n);
  }
  static bool decodeSecret(const String &secret, uint8_t *key, size_t &n) {
    if (!secret.startsWith("whsec_") || secret.length() > 94) return false;
    return mbedtls_base64_decode(key, 64, &n, reinterpret_cast<const uint8_t *>(secret.c_str() + 6), secret.length() - 6) == 0 && n >= 24 && n <= 64;
  }
  static bool validSubscription(JsonVariantConst sub) {
    return sub.is<JsonObjectConst>() && sub["id"].is<String>() && sub["url"].is<String>() && sub["secret"].is<String>() &&
      sub["expiresAt"].is<double>() && allowedUrl(sub["url"].as<String>()) && validSecret(sub["secret"].as<String>());
  }
  static String digest(const String &prefix, const String &suffix) {
    uint8_t hash[32]; mbedtls_md_context_t ctx; mbedtls_md_init(&ctx);
    const auto *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (mbedtls_md_setup(&ctx, info, 0)) { mbedtls_md_free(&ctx); return ""; }
    const uint8_t zero = 0;
    mbedtls_md_starts(&ctx); mbedtls_md_update(&ctx, reinterpret_cast<const uint8_t *>(prefix.c_str()), prefix.length());
    mbedtls_md_update(&ctx, &zero, 1); mbedtls_md_update(&ctx, reinterpret_cast<const uint8_t *>(suffix.c_str()), suffix.length());
    mbedtls_md_finish(&ctx, hash); mbedtls_md_free(&ctx);
    char hex[65]; for (unsigned i = 0; i < 32; ++i) snprintf(hex + 2 * i, 3, "%02x", hash[i]);
    return String(hex);
  }
  static String subscriptionId(const String &url) { return "sub_" + digest("device.answer", url).substring(0, 32); }
  static String randomId(size_t count) {
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    String s; for (size_t i = 0; i < count; ++i) s += alphabet[esp_random() & 63]; return s;
  }
  static String isoTime(time_t value) {
    struct tm utc; gmtime_r(&value, &utc); char text[24]; strftime(text, sizeof(text), "%Y-%m-%dT%H:%M:%SZ", &utc); return String(text);
  }
  static String signature(const String &secret, const String &eid, time_t timestamp, const String &body) {
    uint8_t key[64], hash[32]; size_t n = 0;
    if (!decodeSecret(secret, key, n)) return "";
    String signedBody = eid + "." + String(static_cast<unsigned long>(timestamp)) + "." + body;
    int rc = mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, n, reinterpret_cast<const uint8_t *>(signedBody.c_str()), signedBody.length(), hash);
    memset(key, 0, sizeof(key));
    if (rc) return "";
    uint8_t encoded[48]; size_t len = 0;
    if (mbedtls_base64_encode(encoded, sizeof(encoded), &len, hash, sizeof(hash))) return "";
    encoded[len] = 0; return "v1," + String(reinterpret_cast<char *>(encoded));
  }
  int post(const String &url, const String &secret, const String &sid, const String &eid,
           const String &body, JsonDocument &response, bool rotate) {
    if (!allowedUrl(url) || !ca_ || !clockReady() || body.length() > 8192) return 599;
    time_t now = time(nullptr); String sig = signature(secret, eid, now, body);
    if (!sig.length()) return 599;
    if (rotate && double(state_["subscription"]["rotationUntil"]) > now) {
      String previous = signature(state_["subscription"]["previousSecret"].as<String>(), eid, now, body);
      if (previous.length()) sig += " " + previous;
    }
    NetworkClientSecure client; client.setCACert(ca_); client.setHandshakeTimeout(10);
    HTTPClient http; http.setConnectTimeout(10000); http.setTimeout(10000);
    http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    if (!http.begin(client, url)) return 599;
    http.addHeader("Content-Type", "application/json"); http.addHeader("webhook-id", eid);
    http.addHeader("webhook-timestamp", String(static_cast<unsigned long>(now)));
    http.addHeader("webhook-signature", sig); http.addHeader("X-MCP-Subscription-Id", sid);
    int code = http.POST(body);
    // Verification requires a bounded response. Delivery never needs its body.
    if (!rotate && code >= 200 && code < 300 && http.getSize() <= 4096) {
      BoundedResponse bounded;
      if (http.writeToStream(&bounded) >= 0) deserializeJson(response, bounded.body);
    }
    http.end(); return code < 0 ? 599 : code;
  }
};
