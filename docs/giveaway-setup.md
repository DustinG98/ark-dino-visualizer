# Giveaway Setup

This guide walks an admin through setting up the giveaway system in a Discord server. There are two paths: the **UI Setup** (recommended) which uses the persistent admin panel for everything, or the **Setup using commands** if you prefer slash commands.

## Prerequisites

Before you start, create the following Discord channels and category. Each plays a specific role in the giveaway flow:

- `#giveaway-winners` — announcement channel. Where the bot posts the **Winners!** embed and per-winner **Claim** buttons after a giveaway ends.
- `Giveaways` (category) — where the bot creates **per-giveaway channels** (Enter button) and **exchange channels** (winner ↔ host).
- `#public-giveaways` — channel where the public giveaway panel is posted. Members see this and click **Create Giveaway** to start one.
- `#admin-giveaways` — channel where the admin giveaway panel is posted. Only giveaway managers interact with it. Lock this channel to your admin/managers role with Discord permissions.

> The `#public-giveaways` and `#admin-giveaways` channels can be the same channel if you want a single panel visible to both admins and users; in most servers they're separate.

You also need a **Giveaway Managers** role (or similar) with the **Manage Server** permission. Admins with this permission can manage giveaways via the panel and slash commands.

---

# 1. UI Setup (Recommended)

## Step 1 — Post the admin panel

```
/forge admin giveaway-panel #admin-giveaways
```

The bot posts a persistent embed with 6 buttons into `#admin-giveaways`. The message is registered as a Discord View, so it survives bot restarts. If a moderator deletes it, the bot re-posts it automatically within 60 seconds.

The panel has these buttons:

- **Enable / Reconfigure** — pick announcement channel + per-giveaway category via dropdowns
- **Disable** — pause giveaways (settings kept)
- **Set Ping Role** — pick a role to ping in new giveaway channels
- **View Settings** — show the current configuration (ephemeral)
- **Set Public Panel Channel** — pick the channel where the public giveaway panel lives
- **Force-Cancel a Giveaway** — pick from a list of active giveaways to cancel

## Step 2 — Enable giveaways

Click **Enable / Reconfigure** on the admin panel. Two dropdowns appear:

1. Pick the announcement channel (`#giveaway-winners`).
2. Pick the category (`Giveaways`).

Click **Confirm**. The settings persist to the database.

## Step 3 — Set the public panel channel

Click **Set Public Panel Channel** on the admin panel. A dropdown appears. Pick `#public-giveaways` and click **Confirm**.

This saves the public panel channel id to the database. The bot will post the public panel on its next 60s sweep, or you can post it immediately with `/forge admin giveaway-public-panel`.

## Step 4 — Post the public panel

```
/forge admin giveaway-public-panel #public-giveaways
```

The bot posts the public panel into `#public-giveaways`. Members see a **Create Giveaway** button that opens a modal form (title, winners, duration, description, optional cover image).

## Optional — Ping role

If you want a role to be pinged when a new giveaway opens (e.g. `@Giveaway Watchers`), click **Set Ping Role** on the admin panel and pick the role.

## Verify

- `#admin-giveaways` has the admin panel with 6 buttons.
- `#public-giveaways` has the public panel with **Create Giveaway** + **Help** buttons.
- Typing `/forge admin giveaway-view` shows all six settings.

---

# 2. Setup Using Commands

If you'd rather skip the panel UI and use slash commands directly:

## Step 1 — Enable giveaways

```
/forge admin giveaway-enable #giveaway-winners Giveaways
```

Both arguments are **required**. The bot persists the announcement channel and category to the database in one shot.

## Step 2 — Post the admin panel

```
/forge admin giveaway-panel #admin-giveaways
```

Optional — only needed if you want to use the panel UI for day-to-day management.

## Step 3 — Post the public panel

```
/forge admin giveaway-public-panel #public-giveaways
```

This sets the public panel channel (if not already set via the admin panel) and posts the panel embed.

## Optional — Ping role

```
/forge admin giveaway-ping-role @GiveawayWatchers
```

## Verify

`/forge admin giveaway-view` shows all six settings populated.

---

# Optional Settings

**Ping role**
Set via the admin panel's **Set Ping Role** button, or `/forge admin giveaway-ping-role @role`. The bot pings this role in the message content of each new per-giveaway channel.

**Disable giveaways**
Set via the admin panel's **Disable** button, or `/forge admin giveaway-disable`. Pauses new giveaways. Settings are kept; existing active giveaways continue running.

**View settings**
Set via the admin panel's **View Settings** button, or `/forge admin giveaway-view`. Ephemeral embed showing status, channel, category, ping role, admin panel channel, public panel channel.

**Force-cancel a giveaway**
Set via the admin panel's **Force-Cancel a Giveaway**, or `/forge admin giveaway-cancel <id>`. Cancels any giveaway regardless of creator and deletes the per-giveaway channel. No winners are selected — use the **End now (Admin)** button on the per-giveaway channel to end properly with winner selection. Use the giveaway id from `/giveaway list` or from the giveaway channel footer.

**Force-end a giveaway (with winners)**
Admins with **Manage Server** can click **End now (Admin)** in the per-giveaway channel to end the giveaway immediately, pick random winners, post the winners embed in the master announcement channel, and delete the per-giveaway channel. The same flow runs when the creator presses **Cancel Giveaway** in the per-giveaway channel.

**Force-close an exchange**
Admins with **Manage Server** can click **Force Close (Admin)** in an exchange channel to cancel it, post a notice, and delete the channel. Use when a winner is unresponsive and the exchange needs to be cleaned up.

---

# How It Works After Setup

1. **Member** clicks **Create Giveaway** on the public panel → modal opens → they fill in title, winners, duration, description, optional cover image → submit.
2. **Bot** creates a private channel in the `Giveaways` category, posts an embed with an **Enter** button and a **Cancel Giveaway** button (for the creator only).
3. Members click **Enter** to join. The bot tracks entries on each click and updates the embed's entry count.
4. When the timer hits the end time, the bot picks random winners, posts a **Winners!** embed in `#giveaway-winners`, and posts a per-winner **Claim** button.
5. **Winner** clicks their **Claim** button → the bot opens a private exchange channel with the host. Both parties click **Confirm Received** / **Confirm Sent**. After both confirm, the exchange channel deletes and the winner gets marked in the master Winners embed.
6. If a winner never claims, the exchange channel stays open until they do (no auto-close timeout currently).

---

# Command Reference — Admin

All admin commands live under `/forge admin ...` and require the **Manage Server** permission.

## Giveaway setup

- `/forge admin giveaway-panel #channel` — Post (or move) the persistent admin giveaway panel into a channel. Auto-recovers if the message is deleted.
- `/forge admin giveaway-public-panel #channel` — Post (or move) the persistent public giveaway panel into a channel. Auto-recovers if the message is deleted.
- `/forge admin giveaway-enable #channel #category` — Enable giveaways and set the announcement channel plus the category for per-giveaway and exchange channels. Re-run to change the channel or category.
- `/forge admin giveaway-disable` — Disable giveaways for this server (keeps settings).
- `/forge admin giveaway-ping-role @role` — Set the role pinged when a new giveaway opens (in the per-giveaway channel). Leave empty to clear.
- `/forge admin giveaway-view` — Show the current giveaway settings (status, channel, category, ping role, panel channels).
- `/forge admin giveaway-cancel <id>` — Force-cancel an active giveaway by its id. Deletes the giveaway message and the per-giveaway channel. No winners are selected; for that use the **End now (Admin)** button on the per-giveaway channel.

## Welcome messages

- `/forge admin welcome-set-channel #channel` — Set the channel where welcome messages are sent when new members join.
- `/forge admin welcome-set-message` — Set the welcome message text (supports multiline). Opens a modal editor.
- `/forge admin welcome-view` — View the current welcome channel, message, and enabled status.
- `/forge admin welcome-toggle enable|disable` — Enable or disable welcome messages for this server.

## Placeholders

Welcome messages support these placeholders:

- `{member.mention}` — mentions the new member
- `{member.name}` — the member's username
- `{server.name}` — the server name
- `{channel.<channel-name>}` — clickable link to a channel (e.g. `{channel.general}`)

## Help

- `/forge admin help` — Show the full admin command reference in an ephemeral embed.

---

# Command Reference — Users

User-facing commands live under `/giveaway ...` and are available to any member of the server.

- `/giveaway create <title> <winners> <duration> [description] [image]` — Start a new giveaway via slash command. `title` is the giveaway title, `winners` is the number of winners (1–20), `duration` is how long it runs (`30m`, `2h`, `1d`, max 30 days). Optional `description` (max 1000 chars) and `image` (must be `image/*`).
- `/giveaway list` — List up to 10 active giveaways in this server with their id, end time, and entry count.
- `/giveaway cancel <giveaway_id>` — End one of **your** giveaways immediately and select winners. You can only end giveaways you created. (The same behavior is available as a **Cancel Giveaway** button on the per-giveaway channel — creator-only.)
- `/giveaway help` — Show the public command reference in an ephemeral embed.

## Public panel

If admins have set up the public panel in your server, you'll see a persistent message in the designated channel with a **Create Giveaway** button. Clicking it opens a modal form with the same fields as `/giveaway create`, plus a built-in image upload.

## Claiming a prize

When a giveaway you won ends, the bot posts a **Claim** button in the master `#giveaway-winners` channel addressed to you. Click it to open a private exchange channel with the host. Both parties click their confirm button to complete the exchange.

## After a giveaway ends

1. Bot posts a **Winners!** embed in `#giveaway-winners` listing the winner(s), the host, and the entry count.
2. Bot posts a per-winner **Claim** message addressed to each winner.
3. Winner clicks **Claim** → private exchange channel opens with the host.
4. Winner clicks **Confirm Received** when they get the prize.
5. Host clicks **Confirm Sent** when they deliver it.
6. Once both confirmed: exchange channel auto-deletes after 5 seconds, and the winner gets marked in the master Winners embed.

---

# Troubleshooting

**Permission denied** when bot creates per-giveaway channel
- Bot lacks `Manage Channels` + `Manage Roles`. Enable both permissions for the bot role. Drag the bot role **above** all roles it needs to overwrite. Verify the bot has `Manage Channels` in the configured category.

**Giveaway buttons don't respond**
- Bot was restarted and the View lost its registration. Restart the bot — persistent Views are re-registered on startup. If the message itself is missing, the bot re-posts it within 60s.

**Public panel never appears**
- Public panel channel is not set. Run `/forge admin giveaway-public-panel #public-giveaways` or click **Set Public Panel Channel** on the admin panel.

**Cover image missing from giveaway**
- Image wasn't `image/*` MIME. Re-upload with a PNG/JPG/GIF/WEBP file. Discord modal `FileUpload` requires image MIME.

**Members can't see slash commands**
- Discord client cache. Discord caches command lists for up to 1 hour globally. Set `GUILD_ID` in your bot's `.env` for instant per-guild sync during testing.

**`/forge admin giveaway-*` not visible to my role**
- Bot's `default_permissions` is `administrator=True`. Either grant the role the `Administrator` permission, or override per-command visibility in **Server Settings → Integrations → Forge**.