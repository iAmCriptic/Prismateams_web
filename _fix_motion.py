import pathlib
tag_bad = "<" + "m" + "o" + "t" + "i" + "o" + "n" + " "
tag_good = "<" + "d" + "i" + "v" + " "
root = pathlib.Path(r"c:\Users\ermat\Documents\GitHub\Prismateams_web")
for p in root.rglob("*"):
    if p.suffix not in {".html", ".js"}:
        continue
    t = p.read_text(encoding="utf-8")
    if tag_bad not in t:
        continue
    p.write_text(t.replace(tag_bad, tag_good), encoding="utf-8")
    print("fixed", p)
