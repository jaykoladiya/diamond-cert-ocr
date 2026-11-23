from PIL import Image, ImageDraw, ImageFont
import glob, sys
fp = (glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True) or glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))[0]
fpb = (glob.glob("/usr/share/fonts/**/DejaVuSans-Bold.ttf", recursive=True) or [fp])[0]
F = lambda s, b=False: ImageFont.truetype(fpb if b else fp, s)
W, H = 1700, 1100
im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
d.rectangle([20, 20, W-20, H-20], outline=(60, 60, 60), width=3)
d.text((60, 50), "GIA", font=F(60, True), fill="black")
d.text((230, 70), "NATURAL DIAMOND GRADING REPORT", font=F(30, True), fill="black")
def row(x, y, label, value, w=700, size=24):
    d.text((x, y), label, font=F(size), fill="black")
    lw = d.textlength(label, font=F(size)); vw = d.textlength(value, font=F(size, True))
    dots = "." * int((w - lw - vw - 20) / d.textlength(".", font=F(size)))
    d.text((x + lw + 8, y), dots, font=F(size), fill=(90, 90, 90))
    d.text((x + w - vw, y), value, font=F(size, True), fill="black")
y = 170
d.text((60, y), "March 12, 2025", font=F(24), fill="black"); y += 45
for l, v in [("GIA Report Number", "6452198730"), ("Shape and Cutting Style", "Cushion Modified Brilliant"),
             ("Measurements", "7.02 x 6.51 x 4.38 mm")]:
    row(60, y, l, v); y += 42
y += 20; d.text((60, y), "GRADING RESULTS", font=F(26, True), fill="black"); y += 50
for l, v in [("Carat Weight", "1.71 carat"), ("Color Grade", "H"), ("Clarity Grade", "SI2")]:
    row(60, y, l, v); y += 42
y += 20; d.text((60, y), "ADDITIONAL GRADING INFORMATION", font=F(26, True), fill="black"); y += 50
for l, v in [("Polish", "Very Good"), ("Symmetry", "Good"), ("Fluorescence", "Strong Blue")]:
    row(60, y, l, v); y += 42
d.text((60, y), "Inscription(s): GIA 6452198730", font=F(24), fill="black"); y += 42
d.text((60, y), "Comments: Additional clouds are not shown.", font=F(24), fill="black")
y = 180
d.text((950, y), "PROPORTIONS", font=F(26, True), fill="black"); y += 50
for l, v in [("Depth", "67.3%"), ("Table", "62%"), ("Girdle", "Thin to Medium"), ("Culet", "None")]:
    row(950, y, l, v, w=600); y += 42
d.text((950, 900), "GIA COLOR SCALE  D E F G H I J K L M N", font=F(20), fill="black")
im.save(sys.argv[1])
