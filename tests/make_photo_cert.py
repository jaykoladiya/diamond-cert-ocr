# Recreates the layout of the user's GIA photo (Diamond Dossier style), then degrades it like a phone shot.
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np, sys
fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
F = lambda s: ImageFont.truetype(fp, s)
W, H = 660, 1280
im = Image.new("RGB", (W, H), (176, 160, 130)); d = ImageDraw.Draw(im)
d.rectangle([60, 230, 550, 1270], fill=(236, 236, 232))
d.rounded_rectangle([195, 45, 415, 185], 10, fill="white")
d.text((222, 75), "8.10+H&A D VVS1", font=F(16), fill="black"); d.text((255, 98), "1189C-201", font=F(16), fill="black")
d.text((255, 160), "2181993704", font=F(15), fill="black")
d.text((85, 225), "GEMOLOGICAL INSTITUTE OF AMERICA", font=F(19), fill=(240, 240, 240))
d.rectangle([92, 250, 400, 282], fill="black")
d.text((92, 288), "100723088474", font=F(17), fill="black"); d.text((92, 318), "JOB: 75949640", font=F(15), fill="black")
d.text((485, 332), "02", font=F(15), fill="black")
d.text((92, 364), "January 08, 2018", font=F(16), fill="black")
def row(y, l, v):
    lw = d.textlength(l, font=F(16)); vw = d.textlength(v, font=F(16))
    n = int((410 - lw - vw) / d.textlength(".", font=F(16)))
    d.text((90, y), l, font=F(16), fill="black"); d.text((92 + lw, y), "." * n, font=F(16), fill=(60, 60, 60))
    d.text((503 - vw, y), v, font=F(16), fill="black")
y = 388
for l, v in [("Report Type", "Diamond Grading Report"), ("GIA Report Number", "2181993704"), ("Shape", "Round Brilliant"),
             ("Measurements", "8.18 - 8.22 x 4.93 mm"), ("Carat Weight", "2.01 carat"), ("Color", "D"), ("Clarity", "VVS1"), ("Cut", "Excellent")]:
    row(y, l, v); y += 25.5
d.text((90, y), "Proportions:", font=F(16), fill="black")
for (x, yy, t) in [(215, 622, "50%"), (305, 622, "59%"), (342, 642, "12.5%"), (397, 640, "32.0°"), (165, 640, "medium"), (165, 652, "(faceted)"),
                   (165, 664, "3.5%"), (322, 668, "60.1%"), (342, 684, "44.0%"), (397, 680, "41.4°"), (262, 735, "80%"), (322, 750, "none")]:
    d.text((x, yy), t, font=F(11), fill="black")
d.polygon([(225, 640), (395, 640), (320, 745)], outline="black")
d.text((222, 780), "Profile to actual proportions", font=F(12), fill="black")
y = 812
for l, v in [("Polish", "Excellent"), ("Symmetry", "Excellent"), ("Fluorescence", "None")]:
    row(y, l, v); y += 25.5
d.text((78, y), "Clarity Characteristics: Pinpoint, Cloud, Feather", font=F(16), fill="black"); y += 25.5
d.text((78, y), "Inscription(s): GIA 2181993704", font=F(16), fill="black")
d.rectangle([80, 1118, 295, 1132], fill="black"); d.text((318, 1117), "1005294801", font=F(14), fill="black")
d.text((175, 1150), "GIA", font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", 72), fill="black")
ROT = float(sys.argv[2]) if len(sys.argv) > 2 else -1.2
im = im.rotate(ROT, resample=Image.BICUBIC, fillcolor=(176, 160, 130), expand=False).filter(ImageFilter.GaussianBlur(0.7))
a = np.asarray(im).astype(np.int16) + np.random.default_rng(0).normal(0, float(sys.argv[3]) if len(sys.argv) > 3 else 7, (H, W, 3)).astype(np.int16)
Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(sys.argv[1], quality=80)
