# Shared visual language for every diagram in the document.
INK, SLATE, MUTED, LINE, TINT, WARN, OKC = "#1f2a30", "#37424A", "#6b7780", "#c3ccd2", "#f2f5f6", "#a8621a", "#2e6b52"

DEFS = f'''<defs>
<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
  <path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker>
<marker id="aw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
  <path d="M0 0 L10 5 L0 10 z" fill="{WARN}"/></marker>
</defs>'''

def box(x, y, w, h, title, sub=None, fill="#ffffff", stroke=LINE, tc=INK, r=5, dash=None):
    d = f' stroke-dasharray="4 3"' if dash else ""
    o = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{d}/>'
    if sub:
        o += f'<text x="{x+w/2}" y="{y+h/2-3}" text-anchor="middle" font-size="12.5" font-weight="600" fill="{tc}">{title}</text>'
        o += f'<text x="{x+w/2}" y="{y+h/2+12}" text-anchor="middle" font-size="10.5" fill="{tc}" opacity=".72">{sub}</text>'
    else:
        o += f'<text x="{x+w/2}" y="{y+h/2+4.5}" text-anchor="middle" font-size="12.5" font-weight="600" fill="{tc}">{title}</text>'
    return o

def arrow(x1, y1, x2, y2, label=None, dash=False, color=MUTED, mid=None, above=True):
    d = ' stroke-dasharray="5 4"' if dash else ""
    m = "aw" if color == WARN else "a"
    o = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.4" marker-end="url(#{m})"{d}/>'
    if label:
        lx, ly = (mid if mid else ((x1+x2)/2, (y1+y2)/2))
        dy = -6 if above else 14
        o += f'<text x="{lx}" y="{ly+dy}" text-anchor="middle" font-size="10" fill="{MUTED}">{label}</text>'
    return o

def lane(x, y, w, h, label, fill=TINT, stroke=LINE):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.1" stroke-dasharray="6 4"/>'
            f'<text x="{x+11}" y="{y+16}" font-size="10" font-weight="600" fill="{MUTED}" '
            f'letter-spacing=".7">{label}</text>')

def svg(w, h, body):
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Helvetica Neue, Helvetica, Arial, sans-serif">{DEFS}{body}</svg>')
