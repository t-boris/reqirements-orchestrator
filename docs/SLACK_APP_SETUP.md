# Slack App Setup - MARO Bot

## Required Event Subscriptions

Navigate to: **Event Subscriptions** → **Subscribe to bot events**

Add these event subscriptions:

| Event Name | Purpose | Phase |
|------------|---------|-------|
| `app_mention` | Bot responds when @mentioned | 1 |
| `message.channels` | Bot sees messages in channels | 4 |
| `message.groups` | Bot sees messages in private channels | 4 |
| `message.im` | Bot sees DMs | 4 |
| `message.mpim` | Bot sees multi-person DMs | 4 |
| `member_joined_channel` | **Bot posts welcome when joining channel** | **12** |

### Missing Event Symptom

If `member_joined_channel` is NOT subscribed:
- Event will never fire
- No logs will show "member_joined_channel event received"
- Welcome message won't post when bot joins channels

## Required Bot Token Scopes

Navigate to: **OAuth & Permissions** → **Bot Token Scopes**

| Scope | Purpose | Phase |
|-------|---------|-------|
| `app_mentions:read` | Read @mentions | 1 |
| `channels:history` | Read channel messages | 4 |
| `channels:read` | List channels | 4 |
| `chat:write` | Send messages | 1 |
| `commands` | Handle slash commands | 6 |
| `groups:history` | Read private channel messages | 4 |
| `im:history` | Read DM messages | 4 |
| `mpim:history` | Read multi-person DM messages | 4 |
| `pins:write` | **Pin welcome messages** | **12** |
| `users:read` | Read user info | 7 |

### Missing Scope Symptom

If `pins:write` is missing:
- Welcome message will post successfully
- Pin attempt will fail with permission error
- Log: "Could not pin welcome message: missing_scope"

## Testing Welcome Message

### 1. Remove bot from test channel
```
In Slack: /remove @maro
```

### 2. Check deployment logs are ready
```bash
gcloud compute ssh maro-server --zone=us-central1-a \
  --command='cd /opt/maro && docker-compose logs -f bot'
```

### 3. Re-invite bot to channel
```
In Slack: /invite @maro
```

### 4. Expected logs
```
INFO - member_joined_channel event received
INFO - Bot joined channel, posting quick-reference
INFO - Building welcome blocks
INFO - Posting welcome message to channel
INFO - Welcome message posted successfully
INFO - Attempting to pin welcome message
INFO - Pinned welcome message successfully
```

### 5. Expected Slack behavior
- Message appears in **channel root** (not in a thread)
- Message is **pinned** at top of channel
- Message contains:
  - "MARO is active in this channel"
  - Usage examples
  - Command reference

## Troubleshooting

### Event never fires
**Symptom:** No logs at all when bot joins channel
**Cause:** `member_joined_channel` not in Event Subscriptions
**Fix:** Add event subscription, reinstall app to workspace

### Message posts but not pinned
**Symptom:** Log shows "Could not pin welcome message: missing_scope"
**Cause:** `pins:write` scope missing
**Fix:** Add scope, reinstall app to workspace

### Message posts to thread instead of channel
**Symptom:** Message appears in thread, not channel root
**Cause:** Handler code incorrectly includes thread_ts
**Fix:** Code already correct (no thread_ts in chat_postMessage call)

## After Configuration Changes

1. **Reinstall app:** Changes to events/scopes require reinstalling to workspace
2. **Restart bot:** `docker-compose restart bot`
3. **Test:** Remove and re-add bot to test channel
