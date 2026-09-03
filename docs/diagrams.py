from figs import *

# 1 - system overview
def fig_system():
    b = lane(150, 18, 390, 170, "DIGITALOCEAN DROPLET  \u00b7  159.89.92.61")
    b += box(10, 58, 125, 54, "Telegram", "PJ Flight Alerts", fill=SLATE, tc="#fff", stroke=SLATE)
    b += box(170, 44, 170, 50, "tg-alert.service", "user: tgalert")
    b += box(170, 116, 170, 36, "state.db", "dedupe")
    b += box(360, 116, 165, 40, "Caddy", "https asset host")
    b += box(570, 50, 120, 52, "Slack", "#flight-pj-alerts", fill=SLATE, tc="#fff", stroke=SLATE)
    b += box(400, 212, 180, 44, "dev@phantomstay.com", fill="#fff", stroke=WARN)
    b += arrow(135, 84, 166, 70)
    b += f'<text x="72" y="34" font-size="10" fill="{MUTED}">MTProto user session</text>'
    b += f'<line x1="120" y1="38" x2="150" y2="64" stroke="{LINE}" stroke-width="1"/>'
    b += arrow(255, 94, 255, 112)
    b += arrow(340, 66, 566, 66, "incoming webhook", mid=(453, 60))
    b += arrow(525, 136, 566, 104, "image_url", mid=(560, 132), above=False)
    b += arrow(490, 188, 490, 208, color=WARN, dash=True)
    b += f'<text x="596" y="208" font-size="10" fill="{WARN}">health failures only,</text>'
    b += f'<text x="596" y="222" font-size="10" fill="{WARN}">silent when healthy</text>'
    b += f'<text x="10" y="132" font-size="10" fill="{MUTED}">invite only,</text>'
    b += f'<text x="10" y="146" font-size="10" fill="{MUTED}">no bot allowed</text>'
    return svg(700, 266, b)

# 2 ── message lifecycle
def fig_lifecycle():
    y, h, w = 30, 44, 86
    xs = [8, 108, 208, 308, 408, 508, 604]
    labs = [("message", "arrives"), ("queue", "handler frees"), ("parse", "regex fields"),
            ("filters", "price, seats"), ("dedupe", "msg_id seen?"), ("render", "card + photo"),
            ("POST", "~1/sec")]
    b = ""
    for i, (t, s) in enumerate(labs):
        fill = SLATE if i in (0, 6) else "#ffffff"
        tc = "#fff" if i in (0, 6) else INK
        ww = 80 if i == 6 else w
        b += box(xs[i], y, ww, h, t, s, fill=fill, tc=tc, stroke=SLATE if i in (0, 6) else LINE)
        if i < 6:
            b += arrow(xs[i] + w, y + h/2, xs[i+1] - 4, y + h/2)
    # drop-offs
    for i in (2, 3, 4):
        b += arrow(xs[i] + w/2, y + h, xs[i] + w/2, y + h + 34, color=MUTED, dash=True)
    b += f'<text x="{xs[2]+w/2}" y="{y+h+48}" text-anchor="middle" font-size="10" fill="{MUTED}">not an alert</text>'
    b += f'<text x="{xs[3]+w/2}" y="{y+h+48}" text-anchor="middle" font-size="10" fill="{MUTED}">out of bounds</text>'
    b += f'<text x="{xs[4]+w/2}" y="{y+h+48}" text-anchor="middle" font-size="10" fill="{MUTED}">already sent</text>'
    b += f'<text x="{xs[2]+w/2}" y="{y+h+62}" text-anchor="middle" font-size="10" fill="{MUTED}">discard</text>'
    b += f'<text x="{xs[3]+w/2}" y="{y+h+62}" text-anchor="middle" font-size="10" fill="{MUTED}">discard</text>'
    b += f'<text x="{xs[4]+w/2}" y="{y+h+62}" text-anchor="middle" font-size="10" fill="{MUTED}">discard</text>'
    # thread boundary
    b += f'<line x1="103" y1="14" x2="103" y2="112" stroke="{WARN}" stroke-width="1.2" stroke-dasharray="5 4"/>'
    b += f'<text x="112" y="12" font-size="10" font-weight="600" fill="{WARN}">worker thread, off the event loop &#8594;</text>'
    b += arrow(xs[6] + 40, y + h, xs[6] + 40, y + h + 26, color=OKC)
    b += f'<text x="{xs[6]+40}" y="{y+h+40}" text-anchor="middle" font-size="10" fill="{OKC}">mark sent</text>'
    return svg(700, 130, b)

# 3 ── privilege domains on the server
def fig_privilege():
    b = lane(8, 10, 336, 200, "ROOT ONLY")
    b += box(24, 40, 300, 44, "/etc/tg-alert/env", "600 root:root · every secret", fill="#fff", stroke=WARN)
    b += box(24, 96, 140, 40, "systemd units", "installed by hand")
    b += box(184, 96, 140, 40, "tg-alert-deploy", "forced command")
    b += box(24, 148, 300, 44, "reads env, then drops privileges", "EnvironmentFile is read before User= applies",
             fill=TINT, stroke=LINE)
    b += lane(356, 10, 336, 200, "UNPRIVILEGED")
    b += box(372, 40, 140, 44, "tgalert", "nologin, no home")
    b += box(532, 40, 144, 44, "deploy", "ssh + sudo")
    b += box(372, 96, 304, 40, "/var/lib/tg-alert", "750 tgalert · the only writable path")
    b += box(372, 148, 304, 44, "sandbox", "ProtectSystem=strict · no capabilities · 256MB cap",
             fill=TINT, stroke=LINE)
    b += arrow(324, 170, 370, 118, "runs as")
    return svg(700, 220, b)

# 4 ── dns zone
def fig_dns():
    b = box(250, 10, 200, 44, "phantomstay.com", "GoDaddy zone", fill=SLATE, tc="#fff", stroke=SLATE)
    b += box(10, 118, 190, 50, "MX &#8594; Google", "company email, untouched", fill="#fff", stroke=OKC)
    b += box(232, 118, 190, 50, "A tg-alert", "159.89.92.61", fill="#fff", stroke=SLATE)
    b += box(454, 118, 236, 50, "send. subdomain", "isolated from company mail", fill="#fff", stroke=SLATE)
    b += arrow(300, 54, 105, 114)
    b += arrow(350, 54, 327, 114)
    b += arrow(400, 54, 560, 114)
    b += box(454, 194, 236, 34, "TXT resend._domainkey.send", fill="#fff", stroke=OKC)
    b += box(454, 236, 236, 34, "MX + SPF TXT on send.", fill="#fdf6ef", stroke=WARN, dash=True)
    b += arrow(572, 168, 572, 190)
    b += arrow(572, 228, 572, 232, color=WARN)
    b += f'<text x="446" y="216" text-anchor="end" font-size="10" fill="{OKC}">present</text>'
    b += f'<text x="446" y="258" text-anchor="end" font-size="10" fill="{WARN}">missing</text>'
    b += f'<text x="10" y="196" font-size="10" fill="{MUTED}">Resend was put on a subdomain so a mistake in mail</text>'
    b += f'<text x="10" y="210" font-size="10" fill="{MUTED}">sending config cannot take down company email.</text>'
    return svg(700, 280, b)

# 5 ── deploy pipeline
def fig_deploy():
    b = box(8, 34, 108, 46, "git push", "main", fill=SLATE, tc="#fff", stroke=SLATE)
    b += lane(134, 8, 250, 100, "GITHUB ACTIONS")
    b += box(146, 40, 108, 40, "checks", "lint · parser")
    b += box(266, 40, 106, 40, "secret guard", "blocks .env")
    b += arrow(254, 60, 264, 60)
    b += lane(404, 8, 288, 100, "DROPLET")
    b += box(416, 40, 122, 40, "forced command", "nothing else runs")
    b += box(552, 40, 128, 40, "pull + restart")
    b += arrow(538, 60, 550, 60)
    b += arrow(116, 57, 144, 57)
    b += arrow(384, 57, 414, 57, "one ssh", mid=(399, 51))
    b += box(474, 128, 206, 40, "wait for 'Listening to channel'", fill=TINT, stroke=LINE)
    b += arrow(616, 80, 616, 124)
    b += box(232, 128, 206, 40, "not seen in 60s &#8594; deploy fails", fill="#fdf6ef", stroke=WARN)
    b += arrow(470, 148, 442, 148, color=WARN)
    return svg(700, 180, b)

# 6 ── alert routing
def fig_routing():
    b = box(8, 60, 150, 52, "tg-alert.service", "flight alerts")
    b += box(8, 148, 150, 52, "health timer", "every 6 hours")
    b += box(300, 60, 170, 52, "SLACK_WEBHOOK_URL", "#flight-pj-alerts", fill=SLATE, tc="#fff", stroke=SLATE)
    b += box(300, 148, 170, 52, "Resend API", "https, port 443", fill="#fff", stroke=OKC)
    b += box(516, 148, 176, 52, "dev@phantomstay.com", fill="#fff", stroke=OKC)
    b += arrow(158, 86, 298, 86)
    b += arrow(158, 174, 298, 174)
    b += arrow(470, 174, 514, 174)
    # the forbidden path
    b += f'<line x1="200" y1="170" x2="290" y2="105" stroke="{WARN}" stroke-width="1.4" stroke-dasharray="5 4"/>'
    b += f'<circle cx="245" cy="137" r="11" fill="#fff" stroke="{WARN}" stroke-width="1.6"/>'
    b += f'<path d="M239 131 L251 143 M251 131 L239 143" stroke="{WARN}" stroke-width="1.8"/>'
    b += f'<text x="196" y="222" font-size="10" fill="{WARN}">health output never reaches the deals channel</text>'
    b += box(300, 12, 170, 34, "SMTP 25 / 465 / 587", fill="#fdf6ef", stroke=WARN, dash=True)
    b += f'<text x="484" y="33" font-size="10" fill="{WARN}">blocked by DigitalOcean</text>'
    return svg(700, 236, b)
