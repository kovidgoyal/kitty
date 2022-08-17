#!/usr/bin/env python3
# vim:fileencoding=utf-8

def to_linear(a):
    if a <= 0.04045:
        return a / 12.92
    else:
        return pow((a + 0.055) / 1.055, 2.4)

def generate_srgb_lut():
  values = []
  lines = []

  for i in range(256):
    values.append("{:1.5f}f".format(to_linear(i / 255.0)))

  for i in range(16):
    lines.append(", ".join(values[i * 16:(i + 1) * 16]))

  print(",\n".join(lines))

if __name__ == '__main__':
    generate_srgb_lut()
