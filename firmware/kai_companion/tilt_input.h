#pragma once
#include <algorithm>
#include <cmath>

struct ScreenGravity { float right; float down; };

// Waveshare ESP32-C6-Touch-LCD-1.47, display rotation 1 (320x172).
// Sensor axes are not display axes: sensor -Y points right, +X points down.
inline ScreenGravity screenGravity(float accelX, float accelY) {
  // Absolute gravity projection: a tilted boot must never become a level offset.
  return {-accelY, accelX};
}

inline float withHomeReturn(float rightG) {
  // Near flat, guarantee a leftward return despite small sensor offsets.
  const float magnitude = std::fabs(rightG);
  if (magnitude <= 0.10f) return -0.18f;
  const float weight = std::max(0.0f, 1.0f - (magnitude - 0.10f) / 0.10f);
  return rightG * (1.0f - weight) - 0.18f * weight;
}
