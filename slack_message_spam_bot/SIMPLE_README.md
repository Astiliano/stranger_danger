# SlackAdder Quick Start

1. **Install & Configure Slack App**
   - Create the app from `slack_app_manifest.yaml` (scopes already set).
   - Install to workspace, grab the `xoxb-` bot token & `xapp-` Socket Mode token.

2. **Clone & Configure**
   - `git clone ...` / copy repo.
   - `cp .env.example .env` and edit:
     ```
     SLACK_BOT_TOKEN=xoxb-...
     SLACK_APP_TOKEN=xapp-...
     ```
   - Adjust `channel_groups.json` (names + channel IDs/#names, descriptions optional).

3. **Run**
   - `python vevn_bot_run.py`
     - Creates `slack_adder_env`, installs deps, launches Socket Mode listener.
   - Keep process running.

4. **Use in Slack** (standard workspace channels only)
   - `@SlackAdder help`
   - `@SlackAdder list`
   - `@SlackAdder add @TargetBot customers #extra-channel`
     - Bot auto-joins public channels, retries on rate limits, batches replies in the thread.
     - Attach UTF-8 text files to include additional channel/group tokens (each whitespace-separated token is processed).
   - Optional env: `ALLOWED_USERS=U123ABC` to lock down who can trigger commands (required if app is installed org-wide).
   - `channel_groups.json` must be valid JSON (no comments/trailing commas). Startup will stop and warn if it isn’t.
   - On startup you’ll see a system check (tokens, scopes, channel_groups.json state) in the console.

5. **Notes**
   - Commands from guests / shared-channel contexts are ignored.
   - Shared/external channels can be invite targets if Slack policies allow it.
   - If Slack returns `cant_invite` / scope errors, follow the guidance in the threaded reply.
