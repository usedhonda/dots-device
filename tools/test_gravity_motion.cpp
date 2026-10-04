#include "../firmware/kai_companion/gravity_motion.h"
#include "../firmware/kai_companion/tilt_input.h"
#include <cassert>
#include <cmath>
#include <iostream>

static void step(GravityMotion& m, float gx, float gy, float seconds, float dt) {
  for (float t = 0.0f; t < seconds - 1e-6f; t += dt)
    m.update(gx, gy, std::min(dt, seconds - t), 0, 320, 0, 240);
}

int main() {
  // Small noise must not make a resting body creep.
  GravityMotion still(160, 120);
  step(still, 0.01f, -0.01f, 2.0f, 1.0f / 30.0f);
  assert(std::fabs(still.x - 160.0f) < 0.1f && std::fabs(still.y - 120.0f) < 0.1f);

  // A slope accelerates downhill, and keeps inertia when the slope is removed.
  GravityMotion slope(160, 120);
  step(slope, 0.30f, 0.0f, 0.50f, 1.0f / 60.0f);
  const float speedOnSlope = slope.vx;
  assert(speedOnSlope > 80.0f && slope.x > 160.0f);
  step(slope, 0.0f, 0.0f, 0.20f, 1.0f / 60.0f);
  assert(slope.vx > 0.0f && slope.vx < speedOnSlope);
  step(slope, -0.30f, 0.0f, 0.60f, 1.0f / 60.0f);
  assert(slope.vx < 0.0f);

  // Bounds confine the body without boundary jitter, regardless of frame rate.
  GravityMotion bounded(10, 10);
  step(bounded, -1.0f, -1.0f, 3.0f, 1.0f / 30.0f);
  assert(bounded.x >= 0.0f && bounded.y >= 0.0f);
  assert(std::fabs(bounded.vx) < 1.0f && std::fabs(bounded.vy) < 1.0f);

  GravityMotion a(160, 120), b(160, 120);
  step(a, 0.22f, 0.14f, 0.8f, 1.0f / 30.0f);
  step(b, 0.22f, 0.14f, 0.8f, 1.0f / 120.0f);
  assert(std::fabs(a.x - b.x) < 1.0f && std::fabs(a.y - b.y) < 1.0f);
  // Booting on a steep slope cannot alter the absolute gravity reference.
  auto bootTilt = screenGravity(.294f, .707f);
  assert(bootTilt.right == -.707f);
  auto right = screenGravity(0, -.35f);
  auto left = screenGravity(0, .35f);
  assert(std::fabs(withHomeReturn(right.right) + withHomeReturn(left.right)) < .001f);
  GravityMotion rawRight(76, 86);
  for (int i=0;i<120;i++)
    rawRight.update(withHomeReturn(right.right),0,1.0f/60,76,244,82,96);
  assert(rawRight.x > 240);
  // Captured near-flat sensor reading and either sign of small hardware bias.
  for (float ay : {-.046f, -.10f, 0.0f, .10f}) {
    rawRight.reset(244,86);
    auto flat = screenGravity(.065f, ay);
    for (int i=0;i<210;i++)
      rawRight.update(withHomeReturn(flat.right),flat.down,1.0f/60,76,244,82,96);
    assert(rawRight.x <= 76.1f);
  }
  std::cout << "gravity motion, symmetric slopes, tilted boot and flat return passed\n";
}
