# Welcome Messages

The welcome system posts a customizable message in a designated channel whenever a new member joins your Discord server. The bot reads the message template, substitutes placeholders, and sends it as a plain message.

This guide covers the 4 admin commands that configure it, the placeholder system, and the typical setup flow.

---

# Overview

- `/forge admin welcome-set-channel #channel` — set the channel new-member greetings go to.
- `/forge admin welcome-set-message` — open a modal editor to write your welcome text (multiline supported).
- `/forge admin welcome-toggle enable|disable` — turn the welcome system on or off.
- `/forge admin welcome-view` — show the current configuration.

All 4 commands live under `/forge admin ...` and require the **Manage Server** permission.

---

# Setup Walkthrough

## Step 1 — Pick a channel

Create a channel where welcome messages will be posted. `#welcome` or `#general` are common choices.

Make sure the bot can **View** and **Send Messages** in that channel.

## Step 2 — Set the channel

```
/forge admin welcome-set-channel #welcome
```

The bot saves the channel id. If a message template already exists, it's preserved. If welcome messages are currently disabled, they stay disabled (you'll enable in step 4).

## Step 3 — Write the message

```
/forge admin welcome-set-message
```

The bot replies with an ephemeral embed showing the current message and an **Edit Message** button. Click it to open a modal with a multi-line text input (up to 2000 characters). The placeholder text shows the default template as a hint.

Submit the modal — the message is saved.

## Step 4 — Enable

```
/forge admin welcome-toggle enable
```

The bot flips the enabled flag. New members joining from this point onward will receive your welcome message in the configured channel.

## Verify

`/forge admin welcome-view` shows the current status, channel, and message — all three should be populated.

---

# 1. /forge admin welcome-set-channel

Set the channel where welcome messages are sent.

```
/forge admin welcome-set-channel #channel
```

- `channel` — text channel the bot will post in.

Behavior:
- If a welcome message template exists, it's preserved.
- If welcome messages are currently enabled, they stay enabled.
- The bot confirms with an ephemeral reply pointing at the new channel.

---

# 2. /forge admin welcome-set-message

Open a modal editor to write the welcome message.

```
/forge admin welcome-set-message
```

The bot replies with an ephemeral embed showing the current message and an **Edit Message** button. Click it to open a multi-line text input modal (max 2000 chars). The placeholder text is `Welcome to {server.name}, {member.mention}!`.

Behavior:
- Requires a channel to already be set (use `welcome-set-channel` first).
- Submitting saves the message and preserves the current enabled flag.

See the Placeholders section below for what you can put in the message.

---

# 3. /forge admin welcome-toggle

Enable or disable welcome messages.

```
/forge admin welcome-toggle enable
```

or

```
/forge admin welcome-toggle disable
```

- `action` — `enable` or `disable`.

Behavior:
- Requires a welcome channel and message to already be configured.
- Toggling only flips the enabled flag — channel and message are preserved.

When disabled, the bot silently skips `on_member_join` events for this guild.

---

# 4. /forge admin welcome-view

Show the current welcome configuration.

```
/forge admin welcome-view
```

The bot replies with an ephemeral embed showing:
- **Status** — Enabled or Disabled.
- **Channel** — the configured channel (mention) or `Unknown channel (<id>)` if it was deleted.
- **Message** — the current message template or `_not set_`.

If nothing is configured, the bot tells you which commands to run.

---

# Placeholders

The welcome message template supports these placeholders. They get replaced with real values when the bot posts the welcome message.

- `{member.mention}` — mentions the new member (`@NewUser`).
- `{member.name}` — the member's username (no mention).
- `{server.name}` — the server's display name.
- `{channel.<channel-name>}` — clickable channel link. For example `{channel.general}` becomes `<#123>` if a channel named `general` exists, or falls back to `#general` (plain text) if not.

**Examples**

A simple welcome:
```
Welcome to {server.name}, {member.mention}! 🎉
```

With a channel pointer:
```
Hey {member.mention}, welcome to {server.name}! 
Start in {channel.rules} and chat in {channel.general}.
```

Roles (no built-in placeholder yet — use Discord's native auto-role or a separate bot for that).

---

# Typical Workflows

**First-time setup**

1. `/forge admin welcome-set-channel #welcome` — pick the channel.
2. `/forge admin welcome-set-message` — write the message.
3. `/forge admin welcome-toggle enable` — turn it on.
4. Verify with `/forge admin welcome-view`.

**Update the welcome message**

1. `/forge admin welcome-set-message` — opens the editor.
2. Click **Edit Message**, change the text, submit.

**Temporarily pause welcomes**

1. `/forge admin welcome-toggle disable` — silent; settings preserved.
2. To resume: `/forge admin welcome-toggle enable`.

**Move welcomes to a different channel**

1. `/forge admin welcome-set-channel #new-channel` — switches instantly.

---

# Troubleshooting

**Welcome message not being sent**
- Check `/forge admin welcome-view` — make sure status is Enabled and Channel is valid.
- Verify the bot can still View + Send Messages in the channel (permissions weren't revoked).
- If you just set the channel, confirm the bot isn't offline (check the bot's status indicator).

**Placeholder shows up literally in the welcome message**
- A typo in the placeholder name. Check spelling — placeholders are case-sensitive: `{server.name}` works, `{Server.Name}` does not.

**`{channel.foo}` shows up as `#foo` instead of a clickable link**
- No channel named `foo` exists in the server. Either create the channel, rename to match, or fix the placeholder name in your message.

**`/forge admin welcome-set-message` says "no channel set yet"**
- Run `/forge admin welcome-set-channel #channel` first. The editor refuses to open until a channel exists.

**`/forge admin welcome-toggle` says "no message configured"**
- Run `welcome-set-channel` then `welcome-set-message` first. The toggle refuses to run without both pieces.

**Bot posts in the wrong channel after a server restructure**
- The channel id was saved. If you deleted and recreated the channel with the same name, the bot can't tell. Run `/forge admin welcome-set-channel #new-channel-id` to update.