import pathlib, diagrams

LOGO = pathlib.Path("logo.b64").read_text().strip()
CSS = pathlib.Path("style.css").read_text()


def fig(name, caption):
    svg = getattr(diagrams, "fig_" + name)()
    return f'<figure>{svg}<figcaption>{caption}</figcaption></figure>'


PAGES = []

# cover
PAGES.append(f'''<div class="cover">
<img src="data:image/png;base64,{LOGO}" alt="">
<h1>Phantom PJ<br>Empty Leg Alerts</h1>
<div class="sub">Technical documentation for the Telegram to Slack alert bridge:
architecture, server layout, external service configuration, deployment and operations.</div>
<div class="meta">
<b>Repository</b> &nbsp; github.com/phantomstay/tg-alert-slack &nbsp;&middot;&nbsp; public<br>
<b>Host</b> &nbsp; tg-alert.phantomstay.com &nbsp;&middot;&nbsp; 159.89.92.61 &nbsp;&middot;&nbsp; DigitalOcean NYC1<br>
<b>Destination</b> &nbsp; Slack #flight-pj-alerts<br>
<b>Revised</b> &nbsp; 3 September 2026
</div></div>''')

# contents
PAGES.append('''<h2>Contents</h2>
<div class="toc">
<div><b>1 &nbsp; System overview</b> <span>&mdash; what it does and why it works this way</span></div>
<div><b>2 &nbsp; How a message becomes a card</b> <span>&mdash; parsing, filtering, dedupe, pacing</span></div>
<div><b>3 &nbsp; Server anatomy</b> <span>&mdash; accounts, paths, privilege boundaries</span></div>
<div><b>4 &nbsp; External services</b> <span>&mdash; GoDaddy, Slack, Resend, DigitalOcean, Telegram, GitHub</span></div>
<div><b>5 &nbsp; Deployment</b> <span>&mdash; the pipeline and why it pulls rather than pushes</span></div>
<div><b>6 &nbsp; Monitoring</b> <span>&mdash; health checks and where failures go</span></div>
<div><b>7 &nbsp; Configuration reference</b> <span>&mdash; every environment variable</span></div>
<div><b>8 &nbsp; Operations</b> <span>&mdash; day to day commands</span></div>
<div><b>9 &nbsp; Security model</b></div>
<div><b>10 &nbsp; Known limits and open items</b></div>
</div>

<h3 style="margin-top:22pt">The short version</h3>
<p>A private Telegram channel posts private jet empty leg deals. This service reads that
channel with a logged-in user account, turns each post into a formatted Slack card with a
photo of the aircraft, and posts it into <code>#flight-pj-alerts</code> within a second or two
of it appearing.</p>
<p>It runs continuously on a small DigitalOcean droplet, deploys itself when you push to
<code>main</code>, and emails a named address when any part of it breaks. It does not email
anyone when things are working.</p>

<div class="note"><strong>Why not a Telegram bot.</strong> A bot cannot read a channel unless
the channel owner promotes it to admin. This channel is invite-only, the owner is not our
client, and they declined. The only remaining route is a real user session over MTProto.
That has a consequence that shapes everything else: the session token can read
<em>everything</em> on the account it belongs to, so it is treated as a high-value secret
throughout.</div>''')

# 1 system
PAGES.append(f'''<h2>1 &nbsp; System overview</h2>
{fig("system", "The whole system. Solid lines carry flight alerts, the dashed line carries failure notices and is silent when everything works.")}
<p>Four moving parts, all on one host.</p>
<h3>tg-alert.service</h3>
<p>A long-running Python process holding an authenticated MTProto connection to Telegram.
It receives new channel messages as events, parses each one, and posts the ones that are
flight alerts to Slack. It restarts automatically on failure and catches up on anything it
missed while down.</p>
<h3>state.db</h3>
<p>SQLite, one table, one row per message id already posted. This is what makes restarts,
catch-up and manual backfills safe to repeat: the same alert cannot reach Slack twice.</p>
<h3>Caddy</h3>
<p>Serves the aircraft photographs over HTTPS with an automatically renewed Let's Encrypt
certificate. This exists because of a Slack constraint: an <code>image_url</code> in a Block
Kit card is fetched by <em>Slack's own servers</em>, not the browser. A local file path or a
Slack-hosted file will not render. The image must be publicly reachable over HTTPS.</p>
<h3>Resend</h3>
<p>Delivers health failure emails over HTTPS. Covered in section 6, along with the reason
SMTP is not an option on this host.</p>''')

# 2 lifecycle
PAGES.append(f'''<h2>2 &nbsp; How a message becomes a card</h2>
{fig("lifecycle", "A message runs this gauntlet in a worker thread. Three gates can discard it before it reaches Slack.")}
<h3>Parsing</h3>
<p>Alerts follow a fixed shape, so <code>alerts.py</code> pulls named fields out with regular
expressions: route, date, aircraft type, seats and price. Anything that does not match the
shape is not an alert and is ignored, which is how ordinary chatter in the channel is
filtered out for free.</p>
<h3>Choosing the photo</h3>
<p><code>aircraft_images.json</code> maps aircraft name fragments to image URLs, and the
<em>longest</em> matching fragment wins, so <code>global 7500</code> beats a generic
<code>global</code> entry. If nothing matches, <code>ALERT_IMAGE_URL</code> is used. If that is
unset, the card posts without a photo rather than failing.</p>
<div class="note"><strong>A bad image URL kills the whole card.</strong> Slack rejects the
entire message with <code>invalid_blocks</code> if it cannot fetch the image, so an unreachable
URL means no alert at all, not an alert without a picture. The health check verifies the image
host returns <code>200</code> and an image content type for exactly this reason.</div>
<h3>Why the work happens on a thread</h3>
<p>Posting to Slack is blocking and deliberately paced at about one message per second,
because incoming webhooks rate limit above that. Doing that inline inside the Telegram event
handler would stall Telethon's event loop for the entire length of a bulk drop. Twenty-five
alerts arriving at once would freeze the connection for half a minute, long enough for
Telegram to drop it.</p>
<p>So the handler does one thing: put the message on a queue and return. A single worker
thread drains that queue. Order is preserved, the connection stays responsive, and a burst
of any size is handled without risking the session.</p>
<h3>Bulk drops</h3>
<p>Every alert in a burst is posted. There is no cap, no batching and no summarising. Twenty
five alerts means twenty five cards over roughly thirty seconds.</p>''')

# 3 server
PAGES.append(f'''<h2>3 &nbsp; Server anatomy</h2>
<p>Ubuntu 24.04 LTS, 1 vCPU, 458&nbsp;MB of RAM and a 1&nbsp;GB swap file, in DigitalOcean's
NYC1 region. The region is not arbitrary: a user session connecting from a datacenter in a
different country to the account's phone number is exactly what Telegram's anti-fraud systems
look for.</p>
{fig("privilege", "Three privilege domains. Secrets are readable only by root, and the process that uses them never runs as root.")}
<h3>Accounts</h3>
<table><tr><th>Account</th><th>Shell</th><th>Purpose</th></tr>
<tr><td><code>deploy</code></td><td><code>/bin/bash</code></td><td>the only account permitted to log in over SSH, has sudo</td></tr>
<tr><td><code>tgalert</code></td><td><code>nologin</code></td><td>runs the service, no home directory, cannot log in</td></tr>
<tr><td><code>caddy</code></td><td><code>nologin</code></td><td>runs the web server</td></tr>
<tr><td><code>root</code></td><td>&mdash;</td><td>direct login disabled entirely</td></tr></table>
<h3>Paths</h3>
<table><tr><th>Path</th><th>Owner</th><th>Mode</th><th>Holds</th></tr>
<tr><td><code>/opt/tg-alert</code></td><td>deploy</td><td>755</td><td>the git checkout and virtualenv</td></tr>
<tr><td><code>/etc/tg-alert/env</code></td><td>root</td><td>600</td><td>every secret</td></tr>
<tr><td><code>/var/lib/tg-alert</code></td><td>tgalert</td><td>750</td><td>state.db, the only writable path</td></tr>
<tr><td><code>/var/www/tg-alert</code></td><td>root</td><td>755</td><td>aircraft photos served by Caddy</td></tr>
<tr><td><code>/usr/local/bin/tg-alert</code></td><td>root</td><td>755</td><td>the operator wrapper</td></tr>
<tr><td><code>/usr/local/bin/tg-alert-deploy</code></td><td>root</td><td>755</td><td>the only command CI can run</td></tr></table>
<div class="note"><strong>How secrets reach an unprivileged process.</strong> systemd reads
<code>EnvironmentFile</code> as root, <em>before</em> applying <code>User=tgalert</code>. So the
env file stays <code>600 root:root</code> and unreadable by the service account, while the
service still receives its contents. The <code>tgalert</code> user cannot read its own
credentials from disk.</div>''')

# 4 external services
PAGES.append(f'''<h2>4 &nbsp; External services</h2>
<p>Six accounts outside the repository hold state this project depends on.</p>
<h3>GoDaddy DNS</h3>
{fig("dns", "The phantomstay.com zone. Company email lives at the apex and was left alone; everything added for this project sits on separate names.")}
<table><tr><th>Type</th><th>Host</th><th>Value</th><th>Why it exists</th></tr>
<tr><td>A</td><td><code>tg-alert</code></td><td><code>159.89.92.61</code></td><td>Slack fetches card images from a public host, so the photos need a real HTTPS address</td></tr>
<tr><td>TXT</td><td><code>resend._domainkey.send</code></td><td>DKIM public key</td><td>lets Resend sign mail as the domain, required before it will send to anyone</td></tr></table>
<p>The apex <code>MX</code> records and apex SPF <code>TXT</code> belong to Google Workspace and
were deliberately not touched. Resend was configured on the <code>send.</code> subdomain
specifically so that a mistake in mail sending configuration cannot take down company email.</p>
<div class="warn"><strong>Open item.</strong> Resend also asks for an <code>MX</code> record and
an SPF <code>TXT</code> on <code>send.phantomstay.com</code>. Neither is present, verified
directly against GoDaddy's authoritative nameserver. Mail sends today because DKIM alone is
enough to authorise it, but without SPF alignment deliverability is weaker and bounces are not
tracked. Adding both is low risk, they only affect the subdomain.</div>
<h3>Slack</h3>
<ul>
<li>App <b>Phantom PJ Empty Leg Alerts</b>. Twenty-seven characters, because Slack caps app names at thirty-five</li>
<li>Icon 1024&times;1024 PNG, background colour <code>#0c212c</code></li>
<li>One <b>incoming webhook</b> bound to <code>#flight-pj-alerts</code>, scope <code>incoming-webhook</code></li>
<li>Installation required workspace admin approval; the developer account is not an admin</li>
</ul>
<p>The webhook URL is simultaneously the credential and the channel binding. Anyone holding it
can post to that channel, and it cannot be pointed elsewhere. Changing channel means issuing a
new webhook. It lives only in <code>/etc/tg-alert/env</code>.</p>
<h3>Resend, DigitalOcean, Telegram, GitHub</h3>
<table><tr><th>Service</th><th>What is configured</th></tr>
<tr><td>Resend</td><td>domain <code>send.phantomstay.com</code>, DKIM verified, API key in the server env file</td></tr>
<tr><td>DigitalOcean</td><td>the droplet; outbound ports 25, 465 and 587 are blocked at the platform level and cannot be opened from inside</td></tr>
<tr><td>Telegram</td><td><code>api_id</code> and <code>api_hash</code> from my.telegram.org, registered against the account holding the session and not portable to another account. Access is revocable at any time under Settings &rarr; Devices</td></tr>
<tr><td>GitHub</td><td>public repository. Four secrets drive deployment: <code>SSH_HOST</code>, <code>SSH_USER</code>, <code>SSH_PRIVATE_KEY</code>, <code>SSH_KNOWN_HOSTS</code></td></tr>
</table>''')

# 5 deployment
PAGES.append(f'''<h2>5 &nbsp; Deployment</h2>
{fig("deploy", "Push to main and this runs. The deploy fails loudly rather than leaving a dead service behind.")}
<p>Continuous integration lints the code, runs an assertion test that parses a real
PJX-shaped alert and checks the resulting card, and fails the build if a tracked
<code>.env</code> file or a committed webhook URL is found. Only then does it deploy.</p>
<h3>Why it pulls instead of pushing</h3>
<p>CI never copies files to the server. It opens one SSH connection and sends no command at
all. The key it uses is pinned in <code>authorized_keys</code> to a single forced command,
<code>tg-alert-deploy</code>, which pulls <code>main</code>, restarts the service, and waits up
to sixty seconds for the log line confirming it is listening. If that line does not appear, the
script exits non-zero and the deploy is marked failed.</p>
<p>The consequence is that a leaked deploy key can do exactly one thing: deploy the current
contents of <code>main</code>. It cannot read the environment file, open a shell, or copy
files off the box. This was verified by attempting all four.</p>
<div class="note"><strong>systemd units are installed by hand, on purpose.</strong> They are
kept in the repository for reference but the deploy script never touches them. If deployment
installed unit files, then push access to a public GitHub repository would be a path to running
arbitrary code as root.</div>
<h3>Host key pinning</h3>
<p><code>SSH_KNOWN_HOSTS</code> pins the server's host key in CI, so a hijacked DNS record
cannot cause the workflow to hand its private key to a different machine.</p>''')

# 6 monitoring
PAGES.append(f'''<h2>6 &nbsp; Monitoring</h2>
{fig("routing", "Two destinations, deliberately kept apart. Health output cannot reach the channel the client reads.")}
<p>A systemd timer runs a health check every six hours, and again ten minutes after boot. It
checks six things and prints a line for each.</p>
<pre><code>telegram session  OK    logged in as Alex (id 8448749313)
channel access    OK    'PJ Flight Alerts', latest post id 390
feed activity     OK    last post 51.1h ago
slack webhook     OK    400 invalid_payload (reachable)
alert image       OK    200 image/png .../assets/global-express.png
dedupe db         OK    /var/lib/tg-alert/state.db, 40 alerts recorded</code></pre>
<h3>The check that matters</h3>
<p>Five of these fail loudly on their own. <b>Feed activity</b> is the one that earns its
keep. A session revoked by Telegram, a channel that quietly stops delivering, or an account
locked out looks identical from the outside to a genuinely quiet week. Without this check the
service could sit there, healthy in every measurable way, delivering nothing, indefinitely.</p>
<p><code>STALE_HOURS</code> controls the threshold. It ships at 48 and production runs 96,
because this channel routinely goes two days without posting.</p>
<h3>Why mail goes over HTTPS</h3>
<p>DigitalOcean blocks outbound SMTP on this droplet. Every provider times out:</p>
<pre><code>smtp.gmail.com:587        TimeoutError
smtp.resend.com:587       TimeoutError
smtp-relay.brevo.com:587  TimeoutError
api.resend.com:443        OK</code></pre>
<div class="warn"><strong>The error message is misleading.</strong> The failure surfaces as
<code>[Errno 101] Network is unreachable</code>, which points at IPv6. That is real, the droplet
has no IPv6 route, but it is not the problem. Python tries the IPv6 address last, so its error
is the one that surfaces, hiding the IPv4 timeout underneath. Anyone debugging this from the
error text alone will spend an hour on the wrong thing.</div>
<p>Mail therefore goes through the Resend API over port 443. The SMTP settings remain in the
code and work on any host that permits outbound SMTP.</p>
<h3>Notification discipline</h3>
<p>Repeat notices are suppressed for <code>NOTIFY_COOLDOWN_HOURS</code>, twelve by default, so
a week-long outage produces one email rather than twenty-eight. Health output never goes to
<code>SLACK_WEBHOOK_URL</code>; there is no fallback path to it. Ops noise in a deals channel
teaches people to scroll past the channel.</p>''')

# 7 config
PAGES.append('''<h2>7 &nbsp; Configuration reference</h2>
<p>All configuration is environment variables, in <code>/etc/tg-alert/env</code> on the server
and <code>.env</code> locally. The template is <code>.env.example</code>.</p>
<h4>Telegram</h4>
<table><tr><th>Key</th><th>Default</th><th>Meaning</th></tr>
<tr><td><code>TG_API_ID</code><br><code>TG_API_HASH</code></td><td>required</td><td>from my.telegram.org, tied to one account</td></tr>
<tr><td><code>TG_SESSION</code></td><td>required</td><td>Telethon StringSession, full account access</td></tr>
<tr><td><code>TG_CHANNEL_ID</code></td><td>required</td><td>negative id of the source channel</td></tr></table>
<h4>Slack and presentation</h4>
<table><tr><th>Key</th><th>Default</th><th>Meaning</th></tr>
<tr><td><code>SLACK_WEBHOOK_URL</code></td><td>required</td><td>one webhook posts to one channel</td></tr>
<tr><td><code>ALERT_IMAGE_URL</code></td><td>none</td><td>fallback photo when no aircraft name matches</td></tr>
<tr><td><code>MAX_PRICE</code> <code>MIN_SEATS</code></td><td>none</td><td>drop alerts outside these bounds</td></tr></table>
<h4>State and recovery</h4>
<table><tr><th>Key</th><th>Default</th><th>Meaning</th></tr>
<tr><td><code>STATE_DB</code></td><td><code>state.db</code></td><td>absolute path under systemd</td></tr>
<tr><td><code>CATCHUP</code></td><td>20</td><td>posts read on a first ever run</td></tr>
<tr><td><code>CATCHUP_MAX</code></td><td>200</td><td>ceiling when resuming from the last posted id</td></tr></table>
<h4>Health and alerting</h4>
<table><tr><th>Key</th><th>Default</th><th>Meaning</th></tr>
<tr><td><code>STALE_HOURS</code></td><td>48</td><td>how long the channel may be quiet before that counts as a failure</td></tr>
<tr><td><code>NOTIFY_COOLDOWN_HOURS</code></td><td>12</td><td>minimum gap between repeat notices</td></tr>
<tr><td><code>OPS_EMAIL_TO</code></td><td>none</td><td>where health failures go</td></tr>
<tr><td><code>OPS_EMAIL_FROM</code></td><td><code>SMTP_USER</code></td><td>must be on a verified domain</td></tr>
<tr><td><code>RESEND_API_KEY</code></td><td>none</td><td>send over HTTPS, required on DigitalOcean</td></tr>
<tr><td><code>SMTP_HOST</code> <code>SMTP_PORT</code><br><code>SMTP_USER</code> <code>SMTP_PASS</code></td><td>none</td><td>only usable on a host that permits outbound SMTP</td></tr>
<tr><td><code>SLACK_OPS_WEBHOOK_URL</code></td><td>none</td><td>alternative to email, a separate channel</td></tr></table>''')

# 8 operations
PAGES.append('''<h2>8 &nbsp; Operations</h2>
<p>Everything runs through the <code>tg-alert</code> wrapper, which re-execs under the service
account with the production environment loaded. Running <code>run.py</code> directly will not
have the credentials.</p>
<h3>Checking on it</h3>
<pre><code>ssh deploy@tg-alert.phantomstay.com

sudo tg-alert --health          # every dependency, as a table
sudo systemctl status tg-alert  # is it running
sudo journalctl -u tg-alert -f  # live log
systemctl list-timers tg-alert-health.timer</code></pre>
<h3>Proving the chain works</h3>
<pre><code>sudo tg-alert --test-post    # one card marked "test, not a real flight"
sudo tg-alert --test-notify  # one email to the ops address</code></pre>
<p><code>--test-post</code> exercises Telegram authentication, parsing, the image host and the
Slack webhook in a single command. <code>--test-notify</code> ignores the cooldown and runs
before the Telegram client is even constructed, so you can still test your alerting when the
Telegram session is the thing that is broken.</p>
<h3>Changing the Slack channel</h3>
<p>Create a new incoming webhook for the target channel in the Slack app, then:</p>
<pre><code>sudo nano /etc/tg-alert/env      # replace SLACK_WEBHOOK_URL
sudo systemctl restart tg-alert
sudo tg-alert --test-post</code></pre>
<p>The old webhook keeps working until revoked, so both channels can run during a switchover.
If the new channel is private, the app must be invited to it before a webhook can be created.</p>
<h3>Seeding a channel with recent alerts</h3>
<pre><code>sudo tg-alert --backfill 20 --send --force</code></pre>
<p><code>--force</code> is required because setup ran <code>--mark-seen</code>, which put
existing message ids in the dedupe database. Without it, backfill prints "already sent,
skipping" and posts nothing. Backfill posts oldest first so the channel reads in real order,
and paces itself to stay under the webhook rate limit.</p>
<h3>Adding an aircraft photo</h3>
<p>Drop the image in <code>assets/</code>, add a lowercase name fragment and its public URL to
<code>aircraft_images.json</code>, push, then copy the file to <code>/var/www/tg-alert/assets/</code>
on the server. The longest matching fragment wins.</p>''')

# 9 + 10
PAGES.append('''<h2>9 &nbsp; Security model</h2>
<h3>Access to the host</h3>
<ul>
<li>Root login disabled, password authentication disabled, <code>deploy</code> is the only permitted SSH user</li>
<li>ufw: port 22 rate limited, 80 and 443 open, everything else denied inbound</li>
<li>fail2ban watching the sshd journal</li>
<li>Unattended security upgrades enabled</li>
</ul>
<p>The hardening was sequenced so lockout was impossible: the <code>deploy</code> account was
created and its login <em>and</em> sudo verified working before root was disabled, and port 22
was allowed in ufw before the firewall was enabled.</p>
<h3>Containment of the service</h3>
<ul>
<li>Runs as <code>tgalert</code>, which has no shell and no home directory</li>
<li><code>ProtectSystem=strict</code>, an empty capability bounding set, a syscall filter, and
<code>ReadWritePaths</code> limited to <code>/var/lib/tg-alert</code></li>
<li>Capped at 256&nbsp;MB, on a host with 458&nbsp;MB, so a leak cannot take the box down</li>
</ul>
<h3>Secrets</h3>
<ul>
<li>Nothing sensitive is in the repository, which is public</li>
<li><code>.gitignore</code> excludes <code>.env.*</code>, not just <code>.env</code></li>
<li>CI fails the build if a tracked env file or a committed webhook URL appears</li>
<li>The deploy key is locked to a single forced command</li>
</ul>
<div class="warn"><strong>Standing risk outside this system.</strong> API keys for this
project's wider programme are pinned in a Slack channel readable by external vendors. The
Telegram session token must never be posted there. It grants full read access to the account,
not just to this one channel.</div>

<h2 style="margin-top:22pt">10 &nbsp; Known limits and open items</h2>
<table><tr><th>Item</th><th>Detail</th></tr>
<tr><td>Missing SPF and MX on <code>send.</code></td><td>mail sends on DKIM alone; adding them improves deliverability and enables bounce tracking</td></tr>
<tr><td>No cap on bulk drops</td><td>every alert in a burst posts, about one per second, with no summarising</td></tr>
<tr><td>Backfilled alerts look live</td><td>they are real past deals and carry no expiry marker</td></tr>
<tr><td>One webhook, one channel</td><td>changing destination means issuing a new webhook</td></tr>
<tr><td>Resend sandbox sender</td><td><code>onboarding@resend.dev</code> only delivers to the Resend account owner; a verified domain is needed to send elsewhere</td></tr>
<tr><td>Ops email goes to a personal address</td><td>should become a shared inbox at handover; one line in the env file</td></tr>
<tr><td>Single host</td><td>no redundancy. The droplet is the whole system</td></tr>
</table>''')

body = "".join(f'<div class="page">{p}</div>' for p in PAGES)
html = ('<!doctype html><html><head><meta charset="utf-8">'
        '<title>Phantom PJ Empty Leg Alerts</title>'
        f'<style>{CSS}</style></head><body>{body}</body></html>')
pathlib.Path("doc.html").write_text(html)
print("doc.html", len(html), "bytes,", len(PAGES), "sections")
