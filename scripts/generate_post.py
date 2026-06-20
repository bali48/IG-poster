import os
import json
import re
import hashlib
import hmac
import base64
import time
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"
POSTS_DIR.mkdir(exist_ok=True)
STATE_PATH = ROOT / "scripts" / "state.json"
TOPICS_PATH = ROOT / "scripts" / "topics.json"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

REQUIRED_ENV = [
    "GITHUB_REPOSITORY", "APPROVAL_SECRET", "WORKER_BASE_URL",
    "SMTP_USER", "SMTP_PASS", "EMAIL_TO", "OPENAI_API_KEY",
]


def require_env():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        print(f"Missing required environment variables/secrets: {missing}")
        sys.exit(1)


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"last_index": -1}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def pick_topic():
    topics = json.loads(TOPICS_PATH.read_text())
    state = load_state()
    idx = (state["last_index"] + 1) % len(topics)
    state["last_index"] = idx
    save_state(state)
    return topics[idx]


def clean_text(text):
    text = text.replace("—", " - ").replace("–", "-")
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def generate_content(topic):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = f"""Write Instagram content for a full stack software engineer's tech account.
Topic: {topic['title']}
Angle: {topic['angle']}

Return ONLY valid JSON, no markdown, no code fences, with exactly these keys:
- "headline": a short punchy title for an image card, max 6 words
- "image_body": 1-2 sentences, max 28 words total, the core insight, plain text
- "caption": a full Instagram caption, 60-120 words, friendly and specific (not generic motivational fluff), end with 3-5 relevant hashtags on their own line

Rules: never use an em dash anywhere, use plain hyphens or rewrite the sentence instead. At most 1-2 emoji total, only in the caption, none in headline or image_body. Do not invent specific employer or client names."""

    resp = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content.strip()
    data = json.loads(text)
    return {k: clean_text(v) for k, v in data.items()}


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for w in words:
        trial = (current + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _icon_server(d, cx, cy, s, c):
    bar_h, gap = s * 0.22, s * 0.08
    total = 3 * bar_h + 2 * gap
    y = cy - total / 2
    for _ in range(3):
        d.rounded_rectangle([cx - s / 2, y, cx + s / 2, y + bar_h], radius=10, outline=c, width=8)
        d.ellipse([cx - s / 2 + 18, y + bar_h / 2 - 8, cx - s / 2 + 34, y + bar_h / 2 + 8], fill=c)
        y += bar_h + gap


def _icon_database(d, cx, cy, s, c):
    rx, ry = s / 2, s * 0.11
    ys = [cy - s * 0.32, cy, cy + s * 0.32]
    for y in ys:
        d.ellipse([cx - rx, y - ry, cx + rx, y + ry], outline=c, width=8)
    d.line([cx - rx, ys[0], cx - rx, ys[-1]], fill=c, width=8)
    d.line([cx + rx, ys[0], cx + rx, ys[-1]], fill=c, width=8)


def _icon_container(d, cx, cy, s, c):
    half, depth = s / 2, s * 0.22
    d.rectangle([cx - half, cy - half + depth, cx + half - depth, cy + half], outline=c, width=8)
    d.line([cx - half, cy - half + depth, cx - half + depth, cy - half], fill=c, width=8)
    d.line([cx - half + depth, cy - half, cx + half, cy - half], fill=c, width=8)
    d.line([cx + half, cy - half, cx + half - depth, cy - half + depth], fill=c, width=8)
    d.line([cx - half + depth, cy - half, cx - half + depth, cy + half - depth], fill=c, width=8)


def _icon_code(d, cx, cy, s, c):
    half = s / 2
    gap = s * 0.16
    lx = cx - gap
    d.line([lx, cy - half * 0.5, lx - half * 0.45, cy], fill=c, width=14)
    d.line([lx - half * 0.45, cy, lx, cy + half * 0.5], fill=c, width=14)
    rx = cx + gap
    d.line([rx, cy - half * 0.5, rx + half * 0.45, cy], fill=c, width=14)
    d.line([rx + half * 0.45, cy, rx, cy + half * 0.5], fill=c, width=14)


def _icon_cloud(d, cx, cy, s, c):
    r = s * 0.22
    d.ellipse([cx - s * 0.45, cy - r * 0.4, cx - s * 0.05, cy + r * 1.2], outline=c, width=8)
    d.ellipse([cx - s * 0.15, cy - r * 1.1, cx + s * 0.25, cy + r * 0.9], outline=c, width=8)
    d.ellipse([cx + s * 0.05, cy - r * 0.4, cx + s * 0.45, cy + r * 1.2], outline=c, width=8)
    d.rectangle([cx - s * 0.4, cy + r * 0.5, cx + s * 0.4, cy + r * 1.2], outline=c, width=8)


def _icon_network(d, cx, cy, s, c):
    pts = [
        (cx, cy - s * 0.4), (cx - s * 0.4, cy + s * 0.25),
        (cx + s * 0.4, cy + s * 0.25), (cx, cy),
    ]
    for a in pts:
        for b in pts:
            d.line([a, b], fill=c, width=4)
    for p in pts:
        d.ellipse([p[0] - 16, p[1] - 16, p[0] + 16, p[1] + 16], outline=c, width=8)


def _icon_pipeline(d, cx, cy, s, c):
    n, w, gap = 3, s * 0.26, s * 0.13
    total = n * w + (n - 1) * gap
    x = cx - total / 2
    for i in range(n):
        d.rounded_rectangle([x, cy - s * 0.13, x + w, cy + s * 0.13], radius=10, outline=c, width=8)
        if i < n - 1:
            mx = x + w + gap / 2
            d.line([mx - 14, cy, mx + 14, cy], fill=c, width=8)
            d.line([mx + 4, cy - 12, mx + 14, cy], fill=c, width=8)
            d.line([mx + 4, cy + 12, mx + 14, cy], fill=c, width=8)
        x += w + gap


def _icon_lock(d, cx, cy, s, c):
    body_w, body_h = s * 0.6, s * 0.42
    d.rounded_rectangle([cx - body_w / 2, cy - body_h * 0.1, cx + body_w / 2, cy + body_h * 0.9],
                         radius=14, outline=c, width=8)
    d.arc([cx - body_w * 0.32, cy - body_h * 0.75, cx + body_w * 0.32, cy + body_h * 0.05],
          start=180, end=360, fill=c, width=8)
    d.ellipse([cx - 12, cy + body_h * 0.2, cx + 12, cy + body_h * 0.44], fill=c)


def _icon_globe(d, cx, cy, s, c):
    r = s * 0.42
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=8)
    d.ellipse([cx - r * 0.45, cy - r, cx + r * 0.45, cy + r], outline=c, width=6)
    d.line([cx - r, cy, cx + r, cy], fill=c, width=6)
    d.line([cx - r, cy - r * 0.5, cx + r, cy - r * 0.5], fill=c, width=4)
    d.line([cx - r, cy + r * 0.5, cx + r, cy + r * 0.5], fill=c, width=4)


def _icon_money(d, cx, cy, s, c):
    r = s * 0.38
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=8)
    d.line([cx, cy - r * 1.15, cx, cy + r * 1.15], fill=c, width=8)
    d.line([cx - r * 0.35, cy - r * 0.4, cx + r * 0.35, cy - r * 0.4], fill=c, width=8)
    d.line([cx - r * 0.35, cy + r * 0.4, cx + r * 0.35, cy + r * 0.4], fill=c, width=8)


def _icon_mobile(d, cx, cy, s, c):
    w, h = s * 0.42, s * 0.78
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=22, outline=c, width=8)
    d.line([cx - w * 0.18, cy - h / 2 + 16, cx + w * 0.18, cy - h / 2 + 16], fill=c, width=6)
    d.ellipse([cx - 12, cy + h / 2 - 30, cx + 12, cy + h / 2 - 6], outline=c, width=6)


def _icon_chart(d, cx, cy, s, c):
    heights = [0.3, 0.55, 0.4, 0.75]
    n, w, gap = len(heights), s * 0.16, s * 0.07
    total = n * w + (n - 1) * gap
    x = cx - total / 2
    base = cy + s * 0.4
    for hfrac in heights:
        bar_h = s * 0.8 * hfrac
        d.rectangle([x, base - bar_h, x + w, base], outline=c, width=6)
        x += w + gap
    d.line([cx - total / 2, base, cx + total / 2, base], fill=c, width=6)


def _icon_briefcase(d, cx, cy, s, c):
    w, h = s * 0.8, s * 0.5
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=12, outline=c, width=8)
    d.line([cx - w / 2, cy, cx + w / 2, cy], fill=c, width=6)
    d.rounded_rectangle([cx - w * 0.15, cy - h / 2 - h * 0.22, cx + w * 0.15, cy - h / 2 + 6],
                         radius=8, outline=c, width=8)


ICON_DRAWERS = {
    "server": _icon_server,
    "database": _icon_database,
    "container": _icon_container,
    "code": _icon_code,
    "cloud": _icon_cloud,
    "network": _icon_network,
    "pipeline": _icon_pipeline,
    "lock": _icon_lock,
    "globe": _icon_globe,
    "money": _icon_money,
    "mobile": _icon_mobile,
    "chart": _icon_chart,
    "briefcase": _icon_briefcase,
}


def draw_topic_icon(base_img, icon_name, accent_rgb):
    """Draws a large, low-opacity themed icon in the lower-right area of the card."""
    drawer = ICON_DRAWERS.get(icon_name)
    if drawer is None:
        return base_img
    W, H = base_img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    faint = (*accent_rgb, 40)  # low opacity, ~16%
    drawer(odraw, cx=W * 0.74, cy=H * 0.72, s=420, c=faint)
    return Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")



def make_image(headline, body, icon_name, out_path):
    W, H = 1080, 1080
    bg = (15, 23, 42)
    accent = (52, 211, 153)
    fg = (241, 245, 249)

    img = Image.new("RGB", (W, H), bg)
    img = draw_topic_icon(img, icon_name, accent)
    draw = ImageDraw.Draw(img)

    label_font = ImageFont.truetype(FONT_BOLD, 36)
    headline_font = ImageFont.truetype(FONT_BOLD, 64)
    body_font = ImageFont.truetype(FONT_REG, 40)
    footer_font = ImageFont.truetype(FONT_REG, 28)

    draw.rectangle([(0, 0), (14, H)], fill=accent)
    draw.text((80, 90), "TECH TIP", font=label_font, fill=accent)

    y = 180
    for line in wrap_text(draw, headline, headline_font, W - 160):
        draw.text((80, y), line, font=headline_font, fill=fg)
        y += 76

    y += 40
    for line in wrap_text(draw, body, body_font, W - 160):
        draw.text((80, y), line, font=body_font, fill=(203, 213, 225))
        y += 54

    draw.text((80, H - 90), "@bilal_balimalik   bilalawan.dev", font=footer_font, fill=(100, 116, 139))
    img.save(out_path, "JPEG", quality=92)


def make_token(date_str, decision, secret):
    expiry = int(time.time()) + 60 * 60 * 48  # 48 hour window to approve
    payload = f"{date_str}|{decision}|{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def send_email(headline, caption, image_url, approve_url, reject_url):
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    email_to = os.environ["EMAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Approve today's Instagram post? - {headline}"
    msg["From"] = smtp_user
    msg["To"] = email_to

    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto">
      <h2>{headline}</h2>
      <img src="{image_url}" style="width:100%;border-radius:8px" />
      <p style="white-space:pre-wrap">{caption}</p>
      <p>
        <a href="{approve_url}" style="background:#22c55e;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;margin-right:12px">Approve &amp; post</a>
        <a href="{reject_url}" style="background:#ef4444;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none">Skip today</a>
      </p>
      <p style="color:#888;font-size:12px">This link expires in 48 hours.</p>
    </div>"""
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [email_to], msg.as_string())


def git_commit_and_push(date_str):
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "ig-auto-poster-bot"], check=True)
    subprocess.run(["git", "add", "posts/", "scripts/state.json"], check=True)
    result = subprocess.run(["git", "commit", "-m", f"draft: {date_str}"])
    if result.returncode != 0:
        print("Nothing new to commit (already ran today?), continuing anyway.")
        return
    subprocess.run(["git", "push"], check=True)


def main():
    require_env()
    repo = os.environ["GITHUB_REPOSITORY"]
    secret = os.environ["APPROVAL_SECRET"]
    worker_base_url = os.environ["WORKER_BASE_URL"].rstrip("/")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topic = pick_topic()
    content = generate_content(topic)

    image_path = POSTS_DIR / f"{date_str}.jpg"
    make_image(content["headline"], content["image_body"], topic["icon"], image_path)

    draft = {
        "date": date_str,
        "topic": topic["title"],
        "headline": content["headline"],
        "caption": content["caption"],
        "image_path": f"posts/{date_str}.jpg",
    }
    (POSTS_DIR / f"{date_str}.json").write_text(json.dumps(draft, indent=2))

    git_commit_and_push(date_str)

    image_url = f"https://raw.githubusercontent.com/{repo}/master/posts/{date_str}.jpg"
    approve_url = f"{worker_base_url}/respond?token={make_token(date_str, 'approve', secret)}"
    reject_url = f"{worker_base_url}/respond?token={make_token(date_str, 'reject', secret)}"

    send_email(content["headline"], content["caption"], image_url, approve_url, reject_url)
    print(f"Draft created and approval email sent for {date_str}")


if __name__ == "__main__":
    main()
