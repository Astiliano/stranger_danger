"""Slack bot that invites other bots to specified channels via mention commands."""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

USAGE_HELP = (
    "Usage: `@your_bot add @bot_to_invite customers <#channel-one> team-support>`\n"
    "Use `@your_bot list` to view available channel groups.\n"
    "Channel groups come from channel_groups.json; the `default` group applies when no channels are provided."
)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
ALLOWED_USERS_ENV = os.environ.get("ALLOWED_USERS", "")

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN must be set")

app_kwargs = {"token": SLACK_BOT_TOKEN}
if SLACK_SIGNING_SECRET:
    app_kwargs["signing_secret"] = SLACK_SIGNING_SECRET
elif not SLACK_APP_TOKEN:
    raise RuntimeError(
        "SLACK_SIGNING_SECRET must be set when SLACK_APP_TOKEN is not provided (Socket Mode disabled)"
    )

app = App(**app_kwargs)

MAX_RATE_LIMIT_RETRIES = 5

try:
    auth_info = app.client.auth_test()
    BOT_USER_ID = auth_info["user_id"]
    WORKSPACE_TEAM_ID = auth_info.get("team_id")
    ENTERPRISE_ID = auth_info.get("enterprise_id")
except SlackApiError as exc:  # pragma: no cover - configuration issue
    raise RuntimeError(f"Failed to verify bot credentials: {exc}") from exc

if ENTERPRISE_ID and not WORKSPACE_TEAM_ID:
    if not ALLOWED_USERS_ENV.strip():
        raise RuntimeError(
            "ALLOWED_USERS must be set (comma-separated user IDs) when running as an org-level app."
        )

ALLOWED_USERS: Optional[Set[str]] = None
if ALLOWED_USERS_ENV.strip():
    ALLOWED_USERS = {user.strip().upper() for user in ALLOWED_USERS_ENV.split(",") if user.strip()}

USER_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|[^>]+)?>")

CHANNEL_GROUPS_PATH = Path(os.environ.get("CHANNEL_GROUPS_FILE", "channel_groups.json")).resolve()
_CHANNEL_CACHE: Dict[str, str] = {}
_USER_INFO_CACHE: Dict[str, Dict[str, bool]] = {}
_CHANNEL_INFO_CACHE: Dict[str, Dict[str, bool]] = {}


def _strip_bot_mention(text: str) -> str:
    """Remove the leading mention of this bot from the incoming message."""
    return text.replace(f"<@{BOT_USER_ID}>", "", 1).strip()


def _parse_command_text(text: str) -> Tuple[str, List[str]]:
    cleaned = _strip_bot_mention(text)
    if not cleaned:
        raise ValueError("No command found after mention")

    parts = cleaned.split()
    if not parts:
        raise ValueError("No command found after mention")

    return parts[0].lower(), parts[1:]


def _load_channel_groups() -> Tuple[Dict[str, List[str]], Dict[str, str], Dict[str, str]]:
    try:
        with CHANNEL_GROUPS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.info(
            "Channel groups file '%s' not found; proceeding without groups",
            CHANNEL_GROUPS_PATH,
        )
        return {}, {}, {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Channel groups file '{CHANNEL_GROUPS_PATH}' is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Channel groups file '{CHANNEL_GROUPS_PATH}' must map group names to channel lists"
        )

    groups: Dict[str, List[str]] = {}
    descriptions: Dict[str, str] = {}
    display_names: Dict[str, str] = {}
    for name, raw_group in data.items():
        if not isinstance(name, str):
            logger.warning("Ignoring channel group with non-string name: %r", name)
            continue
        lower_name = name.lower()

        channels_list: Optional[List[str]] = None

        if isinstance(raw_group, dict):
            channels_candidate = raw_group.get("channels")
            if isinstance(channels_candidate, list):
                channels_list = [str(item) for item in channels_candidate if item]
            else:
                logger.warning(
                    "Channel group '%s' ignored because 'channels' is missing or not a list",
                    name,
                )
            description_candidate = raw_group.get("description")
            if isinstance(description_candidate, str):
                descriptions[lower_name] = description_candidate.strip()
        elif isinstance(raw_group, list):
            channels_list = [str(item) for item in raw_group if item]
        else:
            logger.warning(
                "Ignoring channel group '%s' because value must be a dict or list", name
            )
            continue

        if channels_list is not None:
            groups[lower_name] = channels_list
            display_names[lower_name] = name
        else:
            # Ensure group is not silently present without channels
            descriptions.pop(lower_name, None)
            display_names.pop(lower_name, None)
    return groups, descriptions, display_names


def _handle_rate_limit(exc: SlackApiError, attempt: int) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    error = response.get("error") if response else None
    if status == 429 or error == "ratelimited":
        if attempt > MAX_RATE_LIMIT_RETRIES:
            return False
        headers = getattr(response, "headers", {}) or {}
        retry_after_raw = headers.get("Retry-After", "1")
        try:
            wait_time = max(1, int(float(retry_after_raw)))
        except (TypeError, ValueError):
            wait_time = 1
        logger.warning("Rate limit hit; retrying in %s seconds", wait_time)
        time.sleep(wait_time)
        return True
    return False


def _is_guest_user(user_id: str) -> Tuple[bool, Optional[str]]:
    if user_id in _USER_INFO_CACHE:
        cached = _USER_INFO_CACHE[user_id]
        is_guest = cached.get("is_restricted", False) or cached.get("is_ultra_restricted", False) or cached.get("is_stranger", False)
        return is_guest, None

    attempt = 0
    while True:
        attempt += 1
        try:
            response = app.client.users_info(user=user_id)
            user = response.get("user", {})
            flags = {
                "is_restricted": bool(user.get("is_restricted")),
                "is_ultra_restricted": bool(user.get("is_ultra_restricted")),
                "is_stranger": bool(user.get("is_stranger")),
            }
            _USER_INFO_CACHE[user_id] = flags
            return any(flags.values()), None
        except SlackApiError as exc:
            if _handle_rate_limit(exc, attempt):
                continue
            error = exc.response.get("error") if hasattr(exc, "response") else None
            if error == "missing_scope":
                logger.error("users:read scope missing; reinstall SlackAdder with updated manifest")
                return True, "SlackAdder is missing the users:read scope. An admin needs to reinstall the app with the latest manifest."
            logger.error("Unable to fetch user info for %s: %s", user_id, exc)
            return True, "Couldn't verify your account status."


def _is_external_channel(channel_id: str) -> Tuple[bool, Optional[str]]:
    if channel_id.startswith("D"):
        return True, None
    if channel_id in _CHANNEL_INFO_CACHE:
        channel = _CHANNEL_INFO_CACHE[channel_id]
        is_external = bool(channel.get("is_shared") or channel.get("is_ext_shared") or channel.get("is_org_shared"))
        return is_external, None

    attempt = 0
    while True:
        attempt += 1
        try:
            response = app.client.conversations_info(channel=channel_id, include_locale=False)
            channel = response.get("channel", {})
            summary = {
                "is_shared": bool(channel.get("is_shared")),
                "is_ext_shared": bool(channel.get("is_ext_shared")),
                "is_org_shared": bool(channel.get("is_org_shared")),
            }
            _CHANNEL_INFO_CACHE[channel_id] = summary
            return any(summary.values()), None
        except SlackApiError as exc:
            if _handle_rate_limit(exc, attempt):
                continue
            error = exc.response.get("error") if hasattr(exc, "response") else None
            if error == "missing_scope":
                logger.error("channels:read scope missing; reinstall SlackAdder with updated manifest")
                return True, "SlackAdder is missing channel read permissions. Ask an admin to reinstall with the latest manifest."
            logger.error("Unable to fetch channel info for %s: %s", channel_id, exc)
            return True, "Couldn't verify this channel."


def _extract_channel_id_from_mention(token: str) -> Optional[str]:
    token = token.strip()
    if not (token.startswith("<#") and token.endswith(">")):
        return None

    body = token[2:-1]
    if "|" in body:
        body = body.split("|", 1)[0]
    upper_body = body.upper()
    if upper_body.startswith("C") or upper_body.startswith("G"):
        return upper_body
    return None


def _channel_name_to_id(channel_name: str) -> Optional[str]:
    channel_name = channel_name.lstrip("#").lower()
    if not channel_name:
        return None
    if channel_name in _CHANNEL_CACHE:
        return _CHANNEL_CACHE[channel_name]

    cursor = None
    while True:
        try:
            response = app.client.conversations_list(
                limit=200,
                cursor=cursor,
                types="public_channel,private_channel",
            )
        except SlackApiError as exc:
            logger.error("Failed to look up channel '%s': %s", channel_name, exc)
            return None
        for channel in response.get("channels", []):
            _CHANNEL_CACHE[channel["name"].lower()] = channel["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return _CHANNEL_CACHE.get(channel_name)


def _resolve_channel_identifier(token: str) -> Optional[str]:
    token = token.strip()

    mention_id = _extract_channel_id_from_mention(token)
    if mention_id:
        return mention_id

    upper_token = token.upper()
    if upper_token.startswith("C") or upper_token.startswith("G"):
        if len(upper_token) >= 9:
            return upper_token
        return None

    normalized = token.lstrip("#")
    if not normalized:
        return None
    return _channel_name_to_id(normalized)


def _resolve_group_channels(
    group_name: str, channel_groups: Dict[str, List[str]]
) -> Tuple[List[str], List[str]]:
    raw_channels = channel_groups.get(group_name, [])
    resolved: List[str] = []
    missing: List[str] = []
    for entry in raw_channels:
        channel_id = _resolve_channel_identifier(entry)
        if channel_id:
            resolved.append(channel_id)
        else:
            missing.append(entry)

    unique_resolved = list(dict.fromkeys(resolved))
    unique_missing = list(dict.fromkeys(missing))
    return unique_resolved, unique_missing


def _resolve_user_identifier(token: str) -> Optional[str]:
    token = token.strip()
    match = USER_MENTION_RE.fullmatch(token)
    if match:
        return match.group(1)
    if token.upper().startswith("U"):
        return token.upper()
    return None


def _extract_channel_ids(
    raw_tokens: Iterable[str], channel_groups: Dict[str, List[str]]
) -> Tuple[List[str], List[str], List[str], List[str]]:
    channel_ids: List[str] = []
    unknown_tokens: List[str] = []
    empty_groups: List[str] = []
    missing_channels: List[str] = []
    resolved_groups: Dict[str, Tuple[List[str], List[str]]] = {}
    for token in raw_tokens:
        lower_token = token.lower()
        if lower_token in channel_groups:
            if lower_token not in resolved_groups:
                resolved_groups[lower_token] = _resolve_group_channels(lower_token, channel_groups)
            group_channels, missing = resolved_groups[lower_token]
            if group_channels:
                channel_ids.extend(group_channels)
            else:
                empty_groups.append(token)
            if missing:
                missing_channels.append(f"{token} -> {', '.join(missing)}")
            continue

        channel_id = _resolve_channel_identifier(token)
        if channel_id:
            channel_ids.append(channel_id)
        else:
            unknown_tokens.append(token)
    return (
        list(dict.fromkeys(channel_ids)),
        list(dict.fromkeys(unknown_tokens)),
        list(dict.fromkeys(empty_groups)),
        list(dict.fromkeys(missing_channels)),
    )


def _parse_add_arguments(
    args: List[str], channel_groups: Dict[str, List[str]]
) -> Tuple[str, List[str]]:
    if not args:
        raise ValueError("Missing bot user ID to invite")

    target_bot = _resolve_user_identifier(args[0])
    if not target_bot:
        raise ValueError("Couldn't understand which bot to invite. Mention it or provide the user ID.")

    tokens = args[1:]
    if not tokens:
        if "default" in channel_groups:
            tokens = ["default"]
        else:
            raise ValueError("Please name channel group(s) and/or channel names.")

    (
        channel_ids,
        unknown_tokens,
        empty_groups,
        missing_channels,
    ) = _extract_channel_ids(tokens, channel_groups)

    errors: List[str] = []
    if unknown_tokens:
        errors.append(
            "Unknown channel or channel group: " + ", ".join(sorted(unknown_tokens))
        )
    if empty_groups:
        errors.append(
            "Channel groups without any valid channels: " + ", ".join(sorted(empty_groups))
        )
    if missing_channels:
        errors.append(
            "Could not resolve channels within groups: " + ", ".join(sorted(missing_channels))
        )
    if errors:
        raise ValueError("\n".join(errors))
    if not channel_ids:
        raise ValueError("Please name channel group(s) and/or channel names.")

    return target_bot, channel_ids


def _invite_bot_to_channels(target_bot: str, channel_ids: List[str]) -> List[str]:
    results = []
    for channel_id in channel_ids:
        join_error: Optional[str] = None
        attempt = 0
        while True:
            attempt += 1
            join_error = None
            try:
                try:
                    app.client.conversations_join(channel=channel_id)
                except SlackApiError as join_exc:
                    join_error = join_exc.response.get("error")
                    if join_error not in {"method_not_supported_for_channel_type", "already_in_channel"}:
                        if _handle_rate_limit(join_exc, attempt):
                            join_error = None
                            continue
                        results.append(
                            f"❌ <#{channel_id}>: failed to join channel ({join_error})"
                        )
                        break
                app.client.conversations_invite(channel=channel_id, users=target_bot)
                results.append(f"✅ Invited to <#{channel_id}>")
                break
            except SlackApiError as exc:
                if _handle_rate_limit(exc, attempt):
                    continue

                error = exc.response.get("error", "unknown_error")
                if error == "already_in_channel":
                    results.append(f"⚠️ Already in <#{channel_id}>")
                elif error == "cant_invite" and join_error in {
                    "method_not_supported_for_channel_type",
                    "not_in_channel",
                }:
                    results.append(
                        f"❌ <#{channel_id}>: can't invite. Add SlackAdder to the channel first (private channels require a manual invite)."
                    )
                else:
                    results.append(f"❌ <#{channel_id}>: {error}")
                break
    return results


def _send_batched_messages(say, lines: List[str], thread_ts: Optional[str]) -> None:
    if not lines:
        return

    batch: List[str] = []
    char_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if char_count + len(line) + 1 > 3500 or len(batch) >= 40:
            say("\n".join(batch), thread_ts=thread_ts)
            batch = []
            char_count = 0
        batch.append(line)
        char_count += len(line) + 1
    if batch:
        say("\n".join(batch), thread_ts=thread_ts)


@app.event("app_mention")
def handle_app_mention(body, say):  # type: ignore[override]
    event = body.get("event", {})
    text = event.get("text", "")
    user_id = event.get("user")
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not user_id or not channel_id:
        say("Unable to process request: missing user or channel info.", thread_ts=thread_ts)
        return

    if ALLOWED_USERS is not None and user_id.upper() not in ALLOWED_USERS:
        say("Sorry, you're not authorized to use SlackAdder.", thread_ts=thread_ts)
        return

    is_guest, guest_error_message = _is_guest_user(user_id)
    if is_guest:
        say(
            guest_error_message or "Sorry, SlackAdder can only be used by full workspace members.",
            thread_ts=thread_ts,
        )
        return

    is_external_command_channel, channel_error_message = _is_external_channel(channel_id)
    if is_external_command_channel:
        say(
            channel_error_message or "Sorry, SlackAdder cannot be used in shared or external channels.",
            thread_ts=thread_ts,
        )
        return

    try:
        command, args = _parse_command_text(text)
    except ValueError as error:
        say(str(error) + "\n" + USAGE_HELP, thread_ts=thread_ts)
        return

    if command in {"", "help"}:
        say(USAGE_HELP)
        return

    if command == "list":
        try:
            channel_groups, descriptions, display_names = _load_channel_groups()
        except ValueError as error:
            say(str(error), thread_ts=thread_ts)
            return

        if args:
            say("The `list` command does not take any additional arguments.", thread_ts=thread_ts)
            return

        if not display_names:
            say("No channel groups defined in channel_groups.json.", thread_ts=thread_ts)
            return

        lines: List[str] = []
        for key in sorted(display_names):
            display_name = display_names[key]
            description = descriptions.get(key, "").strip() or "(no description provided)"
            lines.append(f"*{display_name}*: {description}")
        _send_batched_messages(say, lines, thread_ts)
        return

    if command == "add":
        try:
            channel_groups, _descriptions, _display_names = _load_channel_groups()
        except ValueError as error:
            say(str(error), thread_ts=thread_ts)
            return

        try:
            target_bot, channel_ids = _parse_add_arguments(args, channel_groups)
        except ValueError as error:
            say(str(error) + "\n" + USAGE_HELP, thread_ts=thread_ts)
            return

        feedback = _invite_bot_to_channels(target_bot, channel_ids)
        _send_batched_messages(say, feedback, thread_ts)
        return

    say(f"Unknown command '{command}'.\n" + USAGE_HELP, thread_ts=thread_ts)


def main() -> None:
    if SLACK_APP_TOKEN:
        SocketModeHandler(app, SLACK_APP_TOKEN).start()
    else:
        port = int(os.environ.get("PORT", "3000"))
        app.start(port=port)


if __name__ == "__main__":
    main()
