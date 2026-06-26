# Role Picker Documentation

## Overview

The Role Picker is a Discord bot feature that allows server members to self-assign roles through an interactive panel. It consists of two panels: an **Admin Panel** for configuration and a **Public Panel** for members to select roles.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Discord Bot                              │
├─────────────────────────────────────────────────────────────────┤
│  Commands (admin)          Views (UI)           Scheduler        │
│  ─────────────────         ──────────           ──────────       │
│  role-picker-admin-panel   RolePickerAdminView  RolePickerScheduler│
│  role-picker-public-panel  RolePickerPublicView                   │
│                            AddRoleModal                          │
│                            EditRoleModal                         │
├─────────────────────────────────────────────────────────────────┤
│                      Backend Client                              │
│                 (bot/app/backend_client.py)                      │
├─────────────────────────────────────────────────────────────────┤
│                         Backend API                              │
│                  (backend/app/api/role_picker.py)                │
├─────────────────────────────────────────────────────────────────┤
│                       Database (SQLAlchemy)                      │
│                RolePickerSettings, RolePickerRole                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### Views

| File | Class | Purpose |
|------|-------|---------|
| `bot/app/views/role_picker_admin.py` | `RolePickerAdminView` | Admin panel with buttons for Set Public Channel, Open Public Panel, Add Role, View Roles, Disable |
| `bot/app/views/role_picker_admin.py` | `AddRoleModal` | Modal dialog for adding new roles |
| `bot/app/views/role_picker_admin.py` | `EditRoleModal` | Modal for editing existing roles |
| `bot/app/views/role_picker_admin.py` | `SetPublicChannelView` | View for selecting the public panel channel |
| `bot/app/views/role_picker_admin.py` | `ViewRolesView` | Ephemeral view for viewing/configured roles |
| `bot/app/views/role_picker_admin.py` | `ConfirmRemoveView` | Confirmation dialog for role removal |
| `bot/app/views/role_picker_public.py` | `RolePickerPublicView` | Public-facing view with toggle buttons for each role |

### Commands

| File | Command | Purpose |
|------|---------|---------|
| `bot/app/commands/admin/role_picker.py` | `/role-picker-admin-panel` | Posts/moves the admin panel to a channel |
| `bot/app/commands/admin/role_picker.py` | `/role-picker-public-panel` | Posts/moves the public panel to a channel |

### Scheduler

**File:** `bot/app/role_picker_scheduler.py`

The `RolePickerScheduler` manages panel persistence and auto-recovery:
- Loads persisted panel messages on bot startup via `load_state_from_db()`
- Scans channel history to recover panels if messages are deleted
- Runs a sweep loop every 60 seconds to re-register views and refresh panels

---

## Database Models

### RolePickerSettings

Stores panel message locations per guild.

| Column | Type | Description |
|--------|------|-------------|
| `guild_id` | BigInteger (PK) | Server ID |
| `admin_panel_channel_id` | BigInteger | Channel where admin panel is posted |
| `admin_panel_message_id` | BigInteger | Message ID of admin panel |
| `public_panel_channel_id` | BigInteger | Channel where public panel is posted |
| `public_panel_message_id` | BigInteger | Message ID of public panel |
| `updated_at` | Integer | Unix timestamp of last update |

### RolePickerRole

Stores individual role options.

| Column | Type | Description |
|--------|------|-------------|
| `guild_id` | BigInteger (PK) | Server ID |
| `position` | Integer (PK) | Display order (1-based) |
| `role_id` | BigInteger | Discord role ID |
| `label` | String(80) | Display label for the role |
| `emoji` | String(64) | Optional emoji |
| `description` | String(100) | Optional description |
| `created_at` | Integer | Unix timestamp |

---

## API Endpoints

Base path: `/api/role-picker`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/roles/{guild_id}` | List all roles for a guild |
| POST | `/roles` | Add a new role (max 25 per guild) |
| PATCH | `/roles/{guild_id}/{position}` | Edit role at position |
| DELETE | `/roles/{guild_id}/{position}` | Remove role at position |
| POST | `/roles/{guild_id}/reorder` | Reorder roles |
| POST | `/settings/admin-panel-channel` | Set admin panel channel |
| POST | `/settings/admin-panel-message` | Set admin panel message ID |
| POST | `/settings/public-panel-channel` | Set public panel channel |
| POST | `/settings/public-panel-message` | Set public panel message ID |
| GET | `/settings/{guild_id}` | Get all settings + roles for guild |

---

## Button IDs

### Admin Panel

| Constant | Value | Purpose |
|----------|-------|---------|
| `SET_PUBLIC_CHANNEL_BTN` | `"rp_admin:set_public_channel"` | Set the public panel channel |
| `OPEN_PANEL_BTN` | `"rp_admin:open_panel"` | Open/post the public panel |
| `ADD_ROLE_BTN` | `"rp_admin:add_role"` | Add a new role |
| `VIEW_ROLES_BTN` | `"rp_admin:view_roles"` | View configured roles |
| `DISABLE_BTN` | `"rp_admin:disable"` | Disable role picker |

### Public Panel

| Constant | Value | Purpose |
|----------|-------|---------|
| `TOGGLE_PREFIX` | `"role_picker:toggle"` | Prefix for role toggle buttons |

---

## Limits

| Limit | Value | Location |
|-------|-------|----------|
| Max roles per guild | 25 | `api/role_picker.py:21` |
| Max label length | 80 characters | `api/role_picker.py:22` |
| Max description length | 100 characters | `api/role_picker.py:23` |

---

## Workflow

### Setting Up Role Picker

1. Use `/role-picker-admin-panel` in the desired channel to post the admin panel
2. Click **Set Public Channel** to select where the public panel will be posted
3. Click **Add Role** to add roles members can assign themselves
4. Click **Open Public Panel** to post the public panel in the configured channel

### Member Role Selection

1. Members see the public panel with toggle buttons for each configured role
2. Clicking a toggle button adds or removes the corresponding role from the member
3. The panel updates to reflect current selections

---

## Persistence & Recovery

On bot startup:
1. `RolePickerScheduler.load_state_from_db()` loads panel locations from database
2. `_recover_admin_panel_message()` scans channel history to find admin panel by button custom_id prefix
3. `_recover_public_panel_message()` scans channel history to find public panel by TOGGLE_PREFIX
4. Views are re-registered with the recovered messages

The sweep loop runs every 60 seconds to ensure panels remain responsive.