#pragma once
#include <Arduino_GFX_Library.h>

inline uint16_t blendSpritePixel(uint16_t color, uint16_t bg, uint8_t a) {
  if (a == 255) return color;
  if (a == 0) return bg;
  const uint16_t r = (((color >> 11) & 31) * a + ((bg >> 11) & 31) * (255-a) + 127) / 255;
  const uint16_t g = (((color >> 5) & 63) * a + ((bg >> 5) & 63) * (255-a) + 127) / 255;
  const uint16_t b = ((color & 31) * a + (bg & 31) * (255-a) + 127) / 255;
  return (r << 11) | (g << 5) | b;
}

inline void decodeSprite(const uint8_t *data, uint16_t *out, size_t pixels, uint16_t bg) {
  size_t pos = 0;
  while (pos < pixels) {
    uint8_t count = *data++;
    uint16_t color = *data++;
    color |= uint16_t(*data++) << 8;
    uint8_t alpha = *data++;
    uint16_t value = blendSpritePixel(color, bg, alpha);
    for (uint8_t i=0; i<count && pos<pixels; ++i) out[pos++] = value;
  }
}

inline void drawKaiFrame(Arduino_GFX *gfx, uint8_t frame, int16_t x, int16_t y, uint16_t bg) {
  static uint16_t pixels[KAI_W*KAI_H];
  static int lastFrame=-1;
  static uint16_t lastBg=0;
  if (frame != lastFrame || bg != lastBg) {
    decodeSprite(kai_rle + kai_offsets[frame], pixels, KAI_W*KAI_H, bg);
    lastFrame=frame;lastBg=bg;
  }
  gfx->draw16bitRGBBitmap(x,y,pixels,KAI_W,KAI_H);
}

inline void drawActionIcon(Arduino_GFX *gfx, uint8_t icon, int16_t x, int16_t y, uint16_t bg) {
  static uint16_t pixels[ACTION_ICON_SIZE*ACTION_ICON_SIZE];
  decodeSprite(action_icons_rle + action_icons_offsets[icon], pixels, ACTION_ICON_SIZE*ACTION_ICON_SIZE,bg);
  gfx->draw16bitRGBBitmap(x,y,pixels,ACTION_ICON_SIZE,ACTION_ICON_SIZE);
}
