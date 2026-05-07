import sys, subprocess
text = subprocess.run(['pbpaste'], capture_output=True, text=True).stdout
chars = [c for c in text if not c.isspace()]
if len(chars) == 0:
    sys.exit(1)
cn = sum(1 for c in chars if 0x4e00<=ord(c)<=0x9fff or 0x3400<=ord(c)<=0x4dbf or 0xf900<=ord(c)<=0xfaff or 0x3000<=ord(c)<=0x303f or 0xff00<=ord(c)<=0xffef)
if cn / len(chars) < 2/3:
    sys.exit(1)
sys.exit(0)