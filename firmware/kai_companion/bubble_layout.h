#pragma once

#include <cmath>
#include <cstdint>

// Screen-space state for the home speech bubble.  The side is latched with
// hysteresis so a character resting near the center line cannot make the
// bubble jump between sides.
class BubbleLayout {
public:
  enum Side : uint8_t { RIGHT = 0, LEFT = 1 };

  static constexpr float kHideSpeed = 18.0f;
  static constexpr float kRevealSpeed = 8.0f;
  static constexpr float kSideHysteresis = 18.0f;

  void reset(float characterX, float centerX) {
    moving_ = false;
    side_ = characterX > centerX + kSideHysteresis ? LEFT : RIGHT;
  }

  void update(float characterX, float vx, float vy, float centerX) {
    const float speed = std::sqrt(vx * vx + vy * vy);
    if (moving_) {
      if (speed <= kRevealSpeed) moving_ = false;
    } else if (speed >= kHideSpeed) {
      moving_ = true;
    }

    if (side_ == RIGHT) {
      if (characterX > centerX + kSideHysteresis) side_ = LEFT;
    } else if (characterX < centerX - kSideHysteresis) {
      side_ = RIGHT;
    }
  }

  bool moving() const { return moving_; }
  Side side() const { return side_; }

  int x(int screenWidth, int width, int offset = 0) const {
    const int margin = 10;
    return offset + (side_ == RIGHT ? screenWidth - margin - width : margin);
  }

  bool contains(int touchX, int touchY, int screenWidth, int width,
               int top = 20, int height = 108, int offset = 0) const {
    const int left = x(screenWidth, width, offset);
    return touchX >= left && touchX < left + width && touchY >= top &&
           touchY < top + height;
  }

private:
  Side side_ = RIGHT;
  bool moving_ = false;
};
