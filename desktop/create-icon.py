"""Generate the native multi-resolution icon from Vision's geometric mark."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

root = Path(__file__).resolve().parent.parent
assets = root / 'desktop/assets'
assets.mkdir(exist_ok=True)
image = Image.new('RGBA', (512, 512))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 504, 504), radius=106, fill='#0c0a06')
glow = Image.new('RGBA', image.size)
g = ImageDraw.Draw(glow)
g.ellipse((75, 75, 437, 437), outline='#b98a30', width=8)
image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
draw = ImageDraw.Draw(image)
draw.arc((70, 70, 442, 442), 208, 332, fill='#f6d98b', width=9)
draw.arc((70, 70, 442, 442), 28, 152, fill='#bd8e39', width=9)
draw.arc((89, 89, 423, 423), 228, 312, fill='#a67b30', width=3)
draw.line([(159, 192), (256, 346), (353, 192)], fill='#f5d684', width=27, joint='curve')
draw.line([(192, 192), (256, 294), (320, 192)], fill='#0c0a06', width=8, joint='curve')
image.save(assets / 'vision.png')
image.save(assets / 'vision.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="1" y="1" width="62" height="62" rx="13" fill="#0c0a06"/><g fill="none" stroke-linecap="round"><path d="M11 21a24 24 0 0 1 42 0M11 43a24 24 0 0 0 42 0" stroke="#d8af59" stroke-width="1.4"/><path d="m20 24 12 19 12-19" stroke="#f5d684" stroke-width="3.4"/></g></svg>'''
(root / 'dist/vision-mark.svg').write_text(svg, encoding='utf-8')
