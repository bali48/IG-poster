# Daily Instagram auto-poster (with email approval)

Every day a GitHub Action drafts a tech post about your stack (caption + a
branded image card), commits it to this repo, and emails you a preview with
"Approve & post" / "Skip today" buttons. Clicking a button hits a tiny
Cloudflare Worker, which triggers a second GitHub Action that either
publishes to Instagram or does nothing. No post ever goes out without your
click.

## How it fits together

1. **`generate_draft.yml`** (cron, daily) - picks the next topic, asks Claude
   for a headline/body/caption, renders a 1080x1080 image with Pillow,
   commits both to `posts/`, and emails you the preview with two signed
   links (good for 48 hours).
2. **Cloudflare Worker** (`worker/approve-worker.js`) - the only piece that
   isn't GitHub Actions, because Actions can't receive an inbound click from
   an email. It just verifies the link's signature and tells GitHub "run the
   publish workflow with this date and decision."
3. **`publish.yml`** (manual dispatch, triggered by the worker) - if the
   decision is "approve," posts the image + caption to Instagram through
   Composio. If "reject," it logs and exits.

## Before you start

- Your Instagram account must be a **Business or Creator account** linked to
  a Facebook Page. Personal accounts can't be published to via the API.
- You'll need your **own** Composio account and API key at
  [composio.dev](https://composio.dev) - separate from any Composio
  connection used inside Claude.ai - and connect Instagram to it from the
  Composio dashboard.
- A Gmail account with an **App Password** (Settings -> Security -> 2-Step
  Verification -> App passwords) for sending the approval emails.
- A free [Cloudflare](https://dash.cloudflare.com) account for the one small
  Worker.
- An [OpenAI API key](https://platform.openai.com/api-keys) (with billing
  enabled) for caption/image text generation.

## Setup

1. **Create the repo.** Push this folder to a new GitHub repository.

2. **Connect Instagram in your own Composio account.**
   In the Composio dashboard, connect the Instagram toolkit. Then run
   locally:
   ```
   pip install composio
   COMPOSIO_API_KEY=sk_... COMPOSIO_USER_ID=bilal python scripts/get_ig_user_id.py
   ```
   Note the numeric ID from the output - that's your `IG_USER_ID`.
   `COMPOSIO_USER_ID` can be any string you pick (e.g. `bilal`) as long as
   it's the same one you used when connecting the account.

3. **Add GitHub repo secrets** (Settings -> Secrets and variables ->
   Actions):
   - `OPENAI_API_KEY`
   - `COMPOSIO_API_KEY`
   - `COMPOSIO_USER_ID`
   - `IG_USER_ID`
   - `SMTP_USER` (your Gmail address)
   - `SMTP_PASS` (the Gmail App Password)
   - `EMAIL_TO` (where the daily approval email should land)
   - `APPROVAL_SECRET` (run `openssl rand -hex 32` and paste the result)
   - `WORKER_BASE_URL` (added after step 4, e.g.
     `https://ig-auto-poster-approve.YOURNAME.workers.dev`)

4. **Deploy the Cloudflare Worker.**
   ```
   cd worker
   npm install -g wrangler
   wrangler login
   ```
   Edit `wrangler.toml`: set `GH_OWNER` and `GH_REPO` to your GitHub
   username/repo. Then:
   ```
   wrangler deploy
   wrangler secret put APPROVAL_SECRET   # paste the same value as the repo secret
   wrangler secret put GH_PAT            # see next step
   ```
   `wrangler deploy` prints your Worker's URL - put that in the
   `WORKER_BASE_URL` repo secret from step 3.

5. **Create a GitHub token for the Worker.**
   GitHub -> Settings -> Developer settings -> Fine-grained personal access
   tokens -> generate one scoped to this repo only, with **Actions: Read and
   write** permission. Use it as `GH_PAT` in step 4.

6. **Test it manually before trusting the schedule.**
   In the repo's Actions tab, run "Generate daily IG draft" manually (it has
   `workflow_dispatch` enabled). Check the email arrives, the image looks
   right, and clicking "Approve & post" actually publishes. Then leave the
   cron schedule to run on its own.

## How today's topic gets picked

Each day, the script checks three sources in order and uses the first one
that has something:

1. **Manual queue** (optional) - a Google Sheet you publish to the web as
   CSV. If you've added a row there that hasn't been posted yet, it wins,
   no matter what.
2. **Live trend check** - tries Hacker News, then dev.to, for a recent,
   well-received AI/tech story (filtered to a minimum points threshold so
   noise doesn't get through). If found, the model is explicitly asked for
   *your own engineering take* on it, not a summary or reproduction of the
   article, both to stay original and to avoid the account turning into a
   generic AI-news repost feed.
3. **Evergreen rotation** - the 60-topic shuffle-bag from `topics.json`,
   used whenever the above two come up empty (network hiccup, nothing
   relevant trending, no manual queue configured). This is what keeps the
   bot from ever going silent.

Every draft's `posts/{date}.json` now also records a `topic_source` field
(`manual`, `trend`, or `evergreen`) so you can see which path was used on
any given day.

### Setting up the manual queue (optional)

1. Create a Google Sheet with two columns: `topic` and `angle` (angle is
   optional, leave it blank if you just want the model to riff on the
   title freely).
2. File -> Share -> Publish to web -> select CSV format -> Publish.
3. Copy the URL it gives you (looks like
   `https://docs.google.com/spreadsheets/d/e/.../pub?output=csv`).
4. Add it as a GitHub repo secret named `TOPICS_SHEET_CSV_URL`.

That's it, no API key, no service account. Just add rows whenever you think
of something specific you want posted, the bot remembers what it's already
used (by title, tracked in `scripts/state.json`) and works through new rows
in order, oldest first. If you skip this entirely, the bot just runs on
trend-check + evergreen with no manual input at all.

## Customizing

- **Topics:** edit `scripts/topics.json`. It currently cycles through 20
  generic stack-level topics (NestJS, Postgres vs Mongo, Docker, AWS, React,
  auth patterns, etc.) and deliberately avoids naming any client or employer.
  Add, remove, or reorder entries freely - rotation just walks through the
  list in order via `scripts/state.json`. Each topic also has an `icon`
  field (`server`, `database`, `container`, `code`, `cloud`, `network`,
  `pipeline`, `lock`, `globe`, `money`, `mobile`, `chart`, `briefcase`,
  `ai`) that controls the faint background graphic on the image card, see
  below. Manual/trend-sourced topics don't have a preset icon, the model
  picks one from this same list automatically.
- **Background icon:** every card gets a large, low-opacity themed graphic
  (a server rack for backend topics, a cloud for AWS, a padlock for auth,
  etc.) drawn behind the text. The drawing functions live in
  `scripts/generate_post.py` under `ICON_DRAWERS`. To add a new one, write a
  small function that draws with basic shapes (`d.line`, `d.ellipse`,
  `d.rounded_rectangle`, ...) at the given `(cx, cy)` and size `s`, add it to
  `ICON_DRAWERS`, then reference its name in `topics.json`.
- **Posting time:** change the cron line in
  `.github/workflows/generate_draft.yml` (currently `0 9 * * *`, 9:00 UTC).
- **Image style:** colors, fonts, and layout are all in `make_image()`
  inside `scripts/generate_post.py`.
- **Caption voice:** tweak the prompt in `generate_content()` in the same
  file. Em dashes and en dashes are also stripped out automatically after
  generation (`clean_text()`), as a backup in case the model ignores the
  prompt instruction.
- **Footer links:** the three rows at the bottom of each card (Instagram,
  website, GitHub) are set in `make_image()`'s call to `draw_footer()` in
  `scripts/generate_post.py`. Edit the handles/labels there directly. The
  small icons next to each are drawn generically (a simple camera shape, a
  globe, a branch/fork glyph) rather than copying the actual Instagram or
  GitHub logos, to stay clear of trademark issues.

## Notes

- Instagram's API allows up to 25 published posts per 24 hours - irrelevant
  at one post a day, just worth knowing if you ever batch-test.
- The approval link expires after 48 hours, after which `publish.yml` simply
  won't be triggered for that draft.
- Nothing in this repo posts automatically without your click. If you don't
  respond to a day's email, that day is simply skipped.
