# SlackAdder Bot

SlackAdder is a Slack bot that listens for mention commands and invites the specified bot/user to a set of channels (individual channel IDs, `#channel` names, or predefined channel groups sourced from `channel_groups.json`). It can auto-join public channels before inviting the target bot, and reports any Slack API errors it encounters.

Looking for a fast path? See `SIMPLE_README.md` for the condensed setup checklist.

## Prerequisites

1. **Python 3.10 or newer**
   - On Windows, download the latest Python installer from [python.org/downloads](https://www.python.org/downloads/windows/).
   - During installation, check **Add Python to PATH**.

2. **Slack Workspace Admin Access** (to create the app and grant scopes).

## Install Python on Windows (quick steps)

1. Visit [python.org/downloads/windows](https://www.python.org/downloads/windows/).
2. Download the latest stable release (e.g., Python 3.12.x) installer.
3. Run the installer:
   - Check **Add Python to PATH**.
   - Choose **Install Now** (or customize if you prefer a different directory).
4. After install, open **Command Prompt** and verify: `python --version`.

## Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App ➜ From manifest**.
2. Paste the contents of `slack_app_manifest.yaml`, choose your workspace, and create the app (scopes: `app_mentions:read`, `chat:write`, `channels:manage`, `channels:read`, `channels:join`, `groups:read`, `groups:write`, `users:read`).
3. Under **OAuth & Permissions**, install the app to your workspace. Keep the **Bot User OAuth Token** (`xoxb-…`).
4. Under **Settings ➜ Basic Information**, generate an **App-Level Token** with scope `connections:write` for Socket Mode (`xapp-…`).

## Configure the Bot

1. Clone or download this repository.
2. Copy `.env.example` to `.env` and update:
   - `SLACK_BOT_TOKEN` with the `xoxb-…` token.
   - `SLACK_APP_TOKEN` with the `xapp-…` token (required for Socket Mode).
   - Optional: `CHANNEL_GROUPS_FILE` if you store groups elsewhere.
3. Edit `channel_groups.json` to match your channel groups (names, descriptions, channel IDs/names).
   ```json
   {
     "default": {
       "description": "Channels every teammate joins",
       "channels": ["#general", "#team-updates", "C1234567890"]
     },
     "customers": {
       "description": "Customer support rooms",
       "channels": ["#customer-1", "#customer-2"]
     }
   }
   ```
   - Keys are case-insensitive when you reference them in Slack (`@SlackAdder add … default`).
   - Channel entries can be `#names`, raw IDs (`C…`/`G…`), or a mix.

## Run the Bot

1. In Command Prompt or PowerShell, change into the project directory.
2. Run: `python vevn_bot_run.py`
   - The script ensures `.env` is populated, creates/updates the `slack_adder_env` virtual environment, installs packages from `requirements.txt`, and launches the bot.
3. Keep the process running. Mention the bot inside Slack to run commands from any standard workspace channel:
   - `@SlackAdder list` ➜ lists all channel groups with descriptions.
   - `@SlackAdder add @TargetBot customers #extra-channel` ➜ invites `@TargetBot` to all resolved channels (shared/external channels are allowed as invite targets).
   - `@SlackAdder help` ➜ prints usage details.
   - Only full workspace members can trigger commands; guests and DMs/shared channels are ignored for command invocation. Replies appear as threaded responses to keep channels tidy.

## Troubleshooting

- `not_in_channel` or `cant_invite` ➜ ensure SlackAdder and the target bot are allowed in the channel (private channels require manual invites and adequate permissions).
- `cant_invite` on shared Slack Connect channels ➜ the workspace owner must allow the target app/user in that channel first; Slack’s admin policies override API invites.
- `missing_scope` ➜ reinstall the app after updating `slack_app_manifest.yaml` so new scopes take effect.
- `workspace members only` / `shared channel` guidance ➜ move to a standard, non-shared channel and ensure you’re a full member (the bot needs `users:read` to detect guest accounts).
- Slack API `ratelimited` / retries ➜ Slack throttles `conversations.join` / `conversations.invite` (roughly ~50 requests/min). The bot automatically honors the `Retry-After` header and will pause/retry up to five times per channel. For large batches (200+ channels) keep the process running until completion.
- Want to stop the bot? Press `Ctrl+C` in the terminal running `vevn_bot_run.py`.

## Updating Dependencies

- Modify `requirements.txt` as needed, then rerun `python vevn_bot_run.py`; it will reinstall packages inside the virtual environment.

Feel free to adapt this bot for other workflows that involve channel group automation.
