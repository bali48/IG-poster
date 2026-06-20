import os
import json
import sys
from pathlib import Path

from composio import Composio


def main():
    date_str = os.environ["POST_DATE"]
    decision = os.environ["DECISION"]

    root = Path(__file__).resolve().parent.parent
    draft_path = root / "posts" / f"{date_str}.json"

    if not draft_path.exists():
        print(f"No draft found for {date_str}, nothing to do.")
        sys.exit(1)

    draft = json.loads(draft_path.read_text())

    if decision != "approve":
        print(f"Post for {date_str} was rejected/skipped. Not publishing.")
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    image_url = f"https://raw.githubusercontent.com/{repo}/master/{draft['image_path']}"

    composio = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
    user_id = os.environ["COMPOSIO_USER_ID"]
    ig_user_id = os.environ["IG_USER_ID"]

    container = composio.tools.execute(
        "INSTAGRAM_POST_IG_USER_MEDIA",
        user_id=user_id,
        arguments={
            "ig_user_id": ig_user_id,
            "image_url": image_url,
            "caption": draft["caption"],
        },
        dangerously_skip_version_check=True,
    )
    print("RAW CONTAINER RESPONSE:", json.dumps(container, indent=2))
    creation_id = container["data"]["id"]
    print(f"Created media container: {creation_id}")

    published = composio.tools.execute(
        "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH",
        user_id=user_id,
        arguments={"ig_user_id": ig_user_id, "creation_id": creation_id},
        dangerously_skip_version_check=True,
    )
    print(f"Published successfully: {published}")


if __name__ == "__main__":
    main()
