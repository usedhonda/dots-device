#include "../firmware/kai_companion/bubble_layout.h"
#include <cassert>
#include <iostream>

int main() {
  BubbleLayout layout;
  layout.reset(76.0f, 160.0f);
  assert(layout.side() == BubbleLayout::RIGHT);
  assert(layout.x(320, 150) == 160);
  assert(layout.contains(200, 40, 320, 150));

  // A brief center crossing does not flip the side; a clear move does.
  layout.update(170.0f, 0.0f, 0.0f, 160.0f);
  assert(layout.side() == BubbleLayout::RIGHT);
  layout.update(180.0f, 0.0f, 0.0f, 160.0f);
  assert(layout.side() == BubbleLayout::LEFT);
  assert(layout.x(320, 150) == 10);
  assert(layout.contains(20, 40, 320, 150));
  assert(!layout.contains(200, 40, 320, 150));

  // Motion hides the bubble, and the lower threshold reveals it after rest.
  layout.update(180.0f, 25.0f, 0.0f, 160.0f);
  assert(layout.moving());
  layout.update(180.0f, 10.0f, 0.0f, 160.0f);
  assert(layout.moving());
  layout.update(180.0f, 8.0f, 0.0f, 160.0f);
  assert(!layout.moving());
  std::cout << "bubble side, bounds, and movement hysteresis passed\n";
}
