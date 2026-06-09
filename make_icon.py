"""Generate civicdiag.ico — a simple gauge icon for the app."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# dark dial face with red rim
d.ellipse((8, 8, SIZE - 8, SIZE - 8), fill=(20, 24, 32, 255),
          outline=(204, 34, 34, 255), width=10)

# tick marks around the upper 270 degrees
cx = cy = SIZE / 2
for i in range(9):
    ang = math.radians(135 + i * 33.75)
    x1 = cx + math.cos(ang) * 92
    y1 = cy + math.sin(ang) * 92
    x2 = cx + math.cos(ang) * 76
    y2 = cy + math.sin(ang) * 76
    d.line((x1, y1, x2, y2), fill=(230, 230, 230, 255), width=7)

# needle pointing upper-right (like high RPM)
ang = math.radians(-45)
d.line((cx, cy, cx + math.cos(ang) * 80, cy + math.sin(ang) * 80),
       fill=(255, 70, 50, 255), width=12)
d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=(230, 230, 230, 255))

img.save(Path(__file__).with_name("civicdiag.ico"),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
print("icon written")
