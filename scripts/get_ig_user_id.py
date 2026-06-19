"""
Run this once, locally, after connecting Instagram in your own Composio account:

    COMPOSIO_API_KEY=sk_... COMPOSIO_USER_ID=bilal python scripts/get_ig_user_id.py

It prints your Instagram Business Account info, including the numeric ID
to use as the IG_USER_ID GitHub secret.
"""
import os
from composio import Composio

composio = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
result = composio.tools.execute(
    "INSTAGRAM_GET_USER_INFO",
    user_id=os.environ["COMPOSIO_USER_ID"],
    arguments={},
    dangerously_skip_version_check=True,
)
print(result)
