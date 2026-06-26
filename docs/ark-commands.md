# ARK Commands

The ARK commands live under `/forge ark ...`. They let you search dinos, recolor them, look up color IDs, and run the Reaper level calculator — all without leaving Discord.

This guide covers each command, what it does, and how the pieces fit together.

---

# Overview

- `/forge ark search` — find a dino and open the recolor builder.
- `/forge ark render` — render a recolored dino directly (power-user, no UI).
- `/forge ark colors` — show the full ASA color palette with swatches.
- `/forge ark reaper` — calculate the level a Reaper will spawn at.
- `/forge ark help` — show this command reference inside Discord.

All commands are slash-only. None of them are ephemeral — the bot posts in the channel where you ran the command unless noted.

---

# 1. /forge ark search

Search for a dino and open an interactive recolor builder.

```
/forge ark search <text>
```

- `text` — substring to match against dino names (case-insensitive).

The bot replies with an embed listing up to 10 matching dinos, each row is a clickable button. Pick a dino to open the recolor builder — a new embed with the dino image and dropdowns for each colorable region.

**What you can do in the builder**

- Pick a color from the dropdown for any region. The image updates with the new color in real time.
- Switch between regions and colors as many times as you like.
- Export the final recolored image to a private channel via the **Export** button.

**Common uses**

- "I want to see what my Rex looks like in different colors."
- "Show me all the dinos that match `rex`."

**Troubleshooting**

- "Backend not ready yet — try again in a moment." — the bot is still warming its cache. Wait a few seconds and retry.
- "No dinos match `xyz`." — try a shorter substring or check spelling.

---

# 2. /forge ark render

Render a recolored dino directly as a single command. Power-user shortcut — bypasses the search + builder flow.

```
/forge ark render <dino> [region0] [region1] [region2] [region3] [region4] [region5]
```

- `dino` — dino name (autocompletes from the cache).
- `region0` through `region5` — color IDs for each paintable region. Optional; if you only set some, the rest use the dino's default.

**Color IDs**

Every paintable region maps to a numeric color ID (0–100+ depending on the palette). Use `/forge ark colors` to see the full list, or `/forge ark search` to pick from a dropdown. Pass IDs as integers.

**Example**

```
/forge ark render Rex region0=12 region1=5 region2=18
```

This recolors Rex with palette colors 12, 5, and 18 for the first three regions, leaving the rest at default.

**When to use this vs. search**

- Use `/forge ark render` when you already know the dino name and the exact color IDs you want.
- Use `/forge ark search` when you're exploring — picking from dropdowns is faster than looking up IDs.

---

# 3. /forge ark colors

Show all available ASA color IDs with swatches in an embed.

```
/forge ark colors
```

The bot replies with an embed listing every paintable color and its numeric ID. Use this as a reference when calling `/forge ark render`.

The list is paginated if there are many colors. Use the arrow buttons to flip through pages.

---

# 4. /forge ark reaper

Calculate the level a Reaper will spawn at based on the queen's level and your character's level. Useful when planning a breeding run.

```
/forge ark reaper <queen_level> <player_level> <extra_levels>
```

- `queen_level` — the Reaper Queen's level at the time of birth.
- `player_level` — your character's level at the time of birth.
- `extra_levels` — `True` if the pregnancy received the maximum XP bonus (the +75 bonus event), `False` otherwise.

**Formula**

```
final_level = int(queen_level * ((player_level + 100) / 250)) + (75 if extra_levels else 0)
```

**Result tiers**

- **500+** — Exceptional. Dark purple embed. Worth the effort.
- **300–499** — Solid. Blue embed.
- **Below 300** — Low yield. Orange embed. Consider higher queen/player levels.

**Example**

```
/forge ark reaper queen_level:120 player_level:95 extra_levels:True
```

---

# 5. /forge ark help

Show the ARK command reference and color palette inside Discord (ephemeral).

```
/forge ark help
```

Equivalent to this document — useful for quick reference without leaving the server.

---

# Typical Workflows

**I want to recolor a dino for fun**

1. `/forge ark search <name>` — find the dino.
2. Pick the dino from the embed buttons — opens the recolor builder.
3. Tweak region colors via the dropdowns.
4. Click **Export** to save the result.

**I want a specific recolor for a screenshot**

1. `/forge ark colors` — look up the color IDs you want.
2. `/forge ark render <dino> region0=... region1=... ...` — render directly.

**I'm planning a Reaper run**

1. `/forge ark reaper <queen_level> <player_level> <extra_levels>` — see the expected Reaper level.
2. Adjust inputs to compare scenarios before committing to the breed.

---

# Troubleshooting

**"Backend not ready yet — try again in a moment."**
- The bot is still warming its cache. Wait a few seconds and retry. If it persists, check that the backend service is healthy.

**Render command returns "Unknown dino"**
- Use `/forge ark search` to confirm the exact spelling. The render command is strict — typos fail silently.

**Color swatch doesn't match what I expected**
- ASA's color palette is large. Always confirm IDs via `/forge ark colors` before using them in `/forge ark render`.

**Search returns no results**
- Try a shorter substring. Names can include extra words like "Aberrant" or "X-Y" prefixes.

**Buttons in the search result embed don't respond**
- The bot may have just restarted and lost the View registration. Click the message once to dismiss, then re-run `/forge ark search`.

---

# Color Reference

The full ASA palette is large — `/forge ark colors` is the canonical reference. The IDs are stable across sessions and are what `/forge ark render` accepts.