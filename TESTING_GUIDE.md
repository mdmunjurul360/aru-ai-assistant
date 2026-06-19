# Anti-Spam System - Testing Guide

## Quick Start

### 1. Verify Installation

```bash
cd d:\Botbari\aru-ai

# Check imports
python -c "from modules.anti_spam import AntiSpamManager; print('✓ Anti-spam module OK')"

# Check main.py
python -c "import main; print('✓ Main integration OK')"
```

### 2. Run Aru AI V3

```bash
python main.py
```

**Expected startup output:**
```
=====================
ARU AI v2 ONLINE
Telegram Connected
Groq Connected
Memory System Active
Voice Assistant Ready
Research Agent Ready
Boss Verification Active
=====================
```

---

## Test Scenarios

### Test 1: First Unauthorized Message

**Setup:**
- Use a non-boss Telegram account (create dummy account or ask friend)
- Send message to your bot

**Expected:**
1. Bot sends unauthorized reply (Bengali message)
2. In logs: `[system] AUTO_REPLY_SENT | user_id=123456789...`
3. Cooldown starts (3 hours from now)

**Check DB:**
```bash
sqlite3 database/memory.db "SELECT * FROM user_cooldowns;"
```

### Test 2: Second Message Within 3 Hours

**Setup:**
- Same non-boss account
- Send another message within 3 hours

**Expected:**
1. Bot does NOT reply
2. In logs: `[system] COOLDOWN_ACTIVE | user_id=123456789 message_count=1/100`
3. Message count incremented in DB

**Check DB:**
```bash
sqlite3 database/memory.db "SELECT message_count FROM user_cooldowns WHERE user_id=123456789;"
```
Should show: `1`

### Test 3: Spam Threshold (100+ Messages)

**Setup:**
- Script that sends 100 messages from same non-boss account rapidly

**Expected:**
1. Messages 1-99: Logged as COOLDOWN_ACTIVE
2. Message 100+: Logged as SPAM_THRESHOLD_REACHED
3. No replies sent after message 1
4. message_count reaches 100 in DB

**Script to test:**
```python
import asyncio
from telethon import TelegramClient

async def spam_test():
    async with TelegramClient('test_session', api_id, api_hash) as client:
        bot = client.get_entity(-1001234567890)  # Your bot
        for i in range(101):
            await client.send_message(bot, f"Test message {i+1}")
            await asyncio.sleep(0.5)
```

### Test 4: Cooldown Expiration

**Setup:**
- Wait 3+ hours after Test 1
- Send message from same non-boss account

**Expected:**
1. Bot sends unauthorized reply again
2. In logs: `[system] AUTO_REPLY_SENT | user_id=123456789...`
3. message_count resets to 0 in DB
4. last_reply_at updated to current time

### Test 5: Boss is Always Exempt

**Setup:**
- Send message from boss account (BOSS_TELEGRAM_ID)
- Send multiple messages rapidly

**Expected:**
1. Bot responds to ALL messages normally
2. NO anti-spam logs for boss
3. Boss message count never added to user_cooldowns
4. Processes all commands normally

---

## Check /cooldown Command

### Test 5a: User in Cooldown

**Send:** `/cooldown`

**From non-boss account (in cooldown):**
```
⏳ Your Cooldown Status

User ID: `123456789`
Last Reply: 2026-06-20T14:30:00+00:00
Messages During Cooldown: 45/100
Time Remaining: 2 ঘণ্টা
```

### Test 5b: No Cooldown

**Send:** `/cooldown`

**From non-boss account (not in cooldown):**
```
❌ আপনার কোনো কুলডাউন সক্রিয় নেই।
```

### Test 5c: Cooldown Expired

**Send:** `/cooldown`

**From non-boss account (after 3h):**
```
✅ কুলডাউন শেষ হয়েছে। আপনি এখন আবার মেসেজ করতে পারেন।
```

---

## Database Queries for Testing

### View All Cooldowns

```sql
SELECT user_id, last_reply_at, message_count 
FROM user_cooldowns 
ORDER BY updated_at DESC;
```

### View Active Cooldowns (< 3 hours ago)

```sql
SELECT user_id, message_count, 
       datetime(last_reply_at) as 'Last Reply',
       CAST((julianday('now') - julianday(last_reply_at)) * 24 AS INTEGER) as 'Hours Ago'
FROM user_cooldowns 
WHERE (julianday('now') - julianday(last_reply_at)) * 24 < 3
ORDER BY last_reply_at DESC;
```

### View Spam Offenders (100+ messages)

```sql
SELECT user_id, message_count, updated_at 
FROM user_cooldowns 
WHERE message_count >= 100 
ORDER BY updated_at DESC;
```

### View Activity Log

```sql
SELECT created_at, action, detail 
FROM activity_logs 
WHERE action LIKE 'AUTO_REPLY%' OR action LIKE 'COOLDOWN%'
ORDER BY created_at DESC 
LIMIT 50;
```

---

## Log Monitoring

### Real-time Logs

```bash
# Windows PowerShell:
Get-Content -Path "logs/aru.log" -Tail 20 -Wait

# Linux/Mac:
tail -f logs/aru.log
```

### Search for Anti-Spam Logs

```bash
# Find all anti-spam actions
grep -E "AUTO_REPLY|COOLDOWN|SPAM_THRESHOLD" logs/aru.log

# Count by action
grep -oE "AUTO_REPLY|COOLDOWN|SPAM_THRESHOLD" logs/aru.log | sort | uniq -c
```

---

## Cleanup / Reset

### Clear Cooldown for User (Admin)

**Future feature** (not yet implemented):
```
/cooldown clear <user_id>
```

**For now (manual):**
```bash
sqlite3 database/memory.db "DELETE FROM user_cooldowns WHERE user_id=123456789;"
```

### Clear All Cooldowns

```bash
sqlite3 database/memory.db "DELETE FROM user_cooldowns;"
sqlite3 database/memory.db "DELETE FROM activity_logs WHERE action LIKE 'AUTO_REPLY%' OR action LIKE 'COOLDOWN%';"
```

---

## Success Criteria

✅ **Anti-spam system is working if:**

- [ ] Unauthorized user gets 1 reply, then silence for 3 hours
- [ ] After 100 messages during cooldown, bot stays silent
- [ ] After 3 hours, bot allows 1 new reply
- [ ] Boss never gets cooldown, always gets replies
- [ ] `/cooldown` shows correct status
- [ ] Activity logs show AUTO_REPLY_SENT / COOLDOWN_ACTIVE / SPAM_THRESHOLD_REACHED
- [ ] Database stores cooldown data persistently

---

## Troubleshooting

### Problem: Cooldown not working

**Check:**
1. `user_cooldowns` table exists: `sqlite3 database/memory.db ".tables"`
2. Anti-spam module imported: `python -c "from modules.anti_spam import AntiSpamManager; print('OK')"`
3. No import errors in logs

### Problem: /cooldown command not recognized

**Check:**
1. Command added to boss_only_command list in main.py ✓
2. Command handler imported in main.py ✓
3. Handler called in _process_boss_message ✓

### Problem: Logs show but no database entries

**Check:**
1. Database writable: `sqlite3 database/memory.db "SELECT COUNT(*) FROM user_cooldowns;"`
2. ActivityLogger connected: Check startup logs for "Anti-spam database ready"

---

## Next Steps

1. ✅ Run anti-spam test scenarios above
2. ✅ Verify logs and database
3. ✅ Monitor for 24 hours
4. 📋 Plan Phase 2.1: Browser Automation
5. 📋 Implement other V3 features

---

**Ready to test?** Start with Test 1! 🚀
