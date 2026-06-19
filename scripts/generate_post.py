import os
import json
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
    return json.loads(text)


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


def make_image(headline, body, out_path):
    W, H = 1080, 1080
    bg = (15, 23, 42)
    accent = (52, 211, 153)
    fg = (241, 245, 249)

    img = Image.new("RGB", (W, H), bg)
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
    make_image(content["headline"], content["image_body"], image_path)

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
