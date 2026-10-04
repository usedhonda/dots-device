#pragma once

// Small, Arduino-independent 2-D integrator for the screen-space character.
// screenGx/screenGy are acceleration components in units of g (not velocity).

#include <algorithm>
#include <cmath>

class GravityMotion {
public:
  float x = 0.0f;
  float y = 0.0f;
  float vx = 0.0f;
  float vy = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;

  explicit GravityMotion(float startX = 0.0f, float startY = 0.0f) {
    reset(startX, startY);
  }

  void reset(float startX, float startY) {
    x = startX;
    y = startY;
    vx = vy = 0.0f;
    gx = gy = 0.0f;
  }

  void update(float screenGx, float screenGy, float dt,
              float minX, float maxX, float minY, float maxY) {
    if (!(dt > 0.0f) || !std::isfinite(dt)) return;
    if (minX > maxX) std::swap(minX, maxX);
    if (minY > maxY) std::swap(minY, maxY);

    // Time-based low pass: approximately 40 ms response, independent of loop rate.
    const float filterDt = std::min(dt, 0.1f);
    const float alpha = 1.0f - std::exp(-filterDt / 0.040f);
    const float targetGx = std::isfinite(screenGx) ? screenGx : 0.0f;
    const float targetGy = std::isfinite(screenGy) ? screenGy : 0.0f;
    gx += (targetGx - gx) * alpha;
    gy += (targetGy - gy) * alpha;

    float remaining = std::min(dt, 0.1f);
    while (remaining > 0.0f) {
      const float h = std::min(remaining, 1.0f / 120.0f);
      integrate(h, minX, maxX, minY, maxY);
      remaining -= h;
    }
  }

private:
  static constexpr float kGravity = 850.0f;
  static constexpr float kStaticG = 0.025f;
  static constexpr float kKineticFriction = 20.0f;
  static constexpr float kDamping = 1.2f;
  static constexpr float kMaxSpeed = 450.0f;
  static constexpr float kRestitution = 0.08f;

  void integrate(float dt, float minX, float maxX, float minY, float maxY) {
    const float inputMag = std::sqrt(gx * gx + gy * gy);
    float ax = gx * kGravity;
    float ay = gy * kGravity;
    const float speed = std::sqrt(vx * vx + vy * vy);

    // Static friction holds a body at rest under small sensor noise. Once moving,
    // kinetic friction opposes velocity and therefore permits inertial coasting.
    if (speed < 0.01f && inputMag <= kStaticG) {
      ax = ay = 0.0f;
      vx = vy = 0.0f;
    } else if (speed > 0.01f) {
      const float friction = kKineticFriction / speed;
      ax -= vx * friction;
      ay -= vy * friction;
    }

    const float damp = std::exp(-kDamping * dt);
    vx = (vx + ax * dt) * damp;
    vy = (vy + ay * dt) * damp;
    const float newSpeed = std::sqrt(vx * vx + vy * vy);
    if (newSpeed > kMaxSpeed) {
      const float scale = kMaxSpeed / newSpeed;
      vx *= scale;
      vy *= scale;
    }

    x += vx * dt;
    y += vy * dt;
    collide(x, vx, minX, maxX);
    collide(y, vy, minY, maxY);
  }

  static void collide(float& p, float& v, float lo, float hi) {
    if (p < lo) {
      p = lo;
      if (v < 0.0f) v = (std::fabs(v) < 8.0f) ? 0.0f : -v * kRestitution;
    } else if (p > hi) {
      p = hi;
      if (v > 0.0f) v = (std::fabs(v) < 8.0f) ? 0.0f : -v * kRestitution;
    }
  }
};
