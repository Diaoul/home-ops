"""Wake dev for new comments where Diaoul mentions @Teuzig, read from Teuzig's notifications."""

import contextlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNER = "Diaoul"
# A login can be renamed and then claimed by someone else; the account id cannot.
OWNER_ID = 319220
# Logins are letters, digits and hyphens: @teuzig-bot or an email address is not a mention.
MENTION = re.compile(r"(?<![\w@-])@teuzig(?![\w-])", re.IGNORECASE)
STATE = Path(__file__).resolve().parent.parent / "cron" / "teuzig-mentions.json"
SEEN_LIMIT = 1000
# GitHub bumps a thread's updated_at up to a minute after the comment that caused it.
OVERLAP = timedelta(minutes=10)
FIRST_LOOKBACK = timedelta(days=1)
GH_TIMEOUT = 120
# Each failed run that exits non-zero wakes the agent, so only one per outage does.
REPORT_AFTER_FAILURES = 5

# Repository admins can edit anyone's comment, so authorship alone does not make a body the owner's.
PROVENANCE = """
query($id: ID!) {
  node(id: $id) {
    ... on Comment {
      body
      author { ... on User { databaseId } }
      editor { ... on User { databaseId } }
      userContentEdits(first: 100) { totalCount nodes { editor { ... on User { databaseId } } } }
    }
  }
}
"""


class GhError(Exception):
    pass


def gh(*args):
    try:
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=GH_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as error:
        raise GhError(f"gh api {args[-1]}: timed out") from error
    if result.returncode:
        raise GhError(f"gh api {args[-1]}: {result.stderr.strip()}")
    return result.stdout


def get(path):
    pages = json.loads(gh("--paginate", "--slurp", path))
    return [item for page in pages for item in (page if isinstance(page, list) else [page])]


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def mentions(body):
    # A quoted reply repeats the mention it answers.
    unquoted = "\n".join(line for line in (body or "").splitlines() if not line.lstrip().startswith(">"))
    return MENTION.search(unquoted) is not None


def owned_body(node_id):
    """The body, if only the owner ever wrote or edited it."""
    node = json.loads(gh("graphql", "-f", f"query={PROVENANCE}", "-f", f"id={node_id}"))["data"]["node"]
    edits = node["userContentEdits"]
    if edits["totalCount"] > len(edits["nodes"]):
        return None
    # An editor that is not a user (an app, a deleted account) comes back as {} or null.
    actors = [node["author"], *([node["editor"]] if node["editor"] else []), *(e["editor"] for e in edits["nodes"])]
    if all((actor or {}).get("databaseId") == OWNER_ID for actor in actors):
        return node["body"]
    return None


def candidates(thread, since):
    subject = thread["subject"]
    repo = thread["repository"]["full_name"]
    number = subject["url"].rsplit("/", 1)[1]
    items = [("comment", c) for c in get(f"repos/{repo}/issues/{number}/comments?since={since}")]
    if subject["type"] == "PullRequest":
        items += [("review comment", c) for c in get(f"repos/{repo}/pulls/{number}/comments?since={since}")]
        items += [
            ("review", r) for r in get(f"repos/{repo}/pulls/{number}/reviews") if (r.get("submitted_at") or "") >= since
        ]
    issue = get(f"repos/{repo}/issues/{number}")[0]
    if issue["created_at"] >= since:
        items.append(("description", issue))
    return repo, number, items


def poll(since, seen, unread):
    found = []
    # all=true: a thread marked read by anyone else must not hide its mentions.
    for thread in get(f"notifications?all=true&participating=true&since={since}"):
        if thread["unread"]:
            unread.append(thread["id"])
        subject = thread["subject"]
        if subject["type"] not in ("Issue", "PullRequest") or not subject["url"]:
            continue
        repo, number, items = candidates(thread, since)
        for kind, item in items:
            if (item.get("user") or {}).get("id") != OWNER_ID or item["node_id"] in seen:
                continue
            if not mentions(item.get("body")):
                continue
            body = owned_body(item["node_id"])
            if body is None or not mentions(body):
                continue
            seen.append(item["node_id"])
            found.append((repo, subject["type"], number, kind, item["html_url"], body))
    return found


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    partial = STATE.with_suffix(".tmp")
    partial.write_text(json.dumps(state))
    os.replace(partial, STATE)


state = json.loads(STATE.read_text()) if STATE.exists() else {}
seen = state.get("seen", [])
started = datetime.now(timezone.utc)
last = state.get("last_success")
since = iso(parse(last) - OVERLAP if last else started - FIRST_LOOKBACK)

unread = []
try:
    found = poll(since, seen, unread)
# A traceback exits non-zero, which would wake the agent every minute.
except Exception as error:
    failures = state.get("failures", 0) + 1
    save({**state, "failures": failures})
    if failures == REPORT_AFTER_FAILURES:
        sys.exit(f"{failures} consecutive failed polls, mentions are not being read: {error}")
    print(json.dumps({"wakeAgent": False}))
    sys.exit(0)

save({"seen": seen[-SEEN_LIMIT:], "last_success": iso(started), "failures": 0})

# Only tidies Teuzig's inbox: the cursor, not the read state, decides what is polled.
for thread_id in unread:
    with contextlib.suppress(GhError):
        gh("-X", "PATCH", f"notifications/threads/{thread_id}")

for repo, subject_type, number, kind, url, body in found:
    print(f"## {repo} {subject_type} #{number} ({kind})")
    print(url)
    print(body)
    print()
print(json.dumps({"wakeAgent": bool(found)}))
