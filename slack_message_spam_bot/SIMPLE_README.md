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

5. **Notes**
   - Commands from guests / shared-channel contexts are ignored.
   - Shared/external channels can be invite targets if Slack policies allow it.
   - If Slack returns `cant_invite` / scope errors, follow the guidance in the threaded reply.
