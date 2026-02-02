# Phase 2: Slack Integration - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<vision>
## How This Should Work

Build the Slack integration layer exactly as specified in Part 9 of the MARO 2.0 spec. This means:

1. **Slack Bolt App** - Modern async Bolt app as the entry point for all Slack events
2. **SlackClient Wrapper** - Unified client with message type routing (channel/thread/ephemeral)
3. **Rate Limiting** - Built-in rate limiter to respect Slack API limits
4. **Button Handlers** - Route button clicks (approve, object, discuss) to appropriate handlers
5. **Dashboard Manager** - Pinned channel status dashboard showing pending approvals, committed items, active decisions

The integration is pure infrastructure - no business logic, no LLM calls, no intent classification. Those come in Phase 3. This phase establishes the communication layer.

</vision>

<essential>
## What Must Be Nailed

- **All pieces equally important** - Can't ship without message routing, rate limiting, and button handlers all working together
- **Message type routing** - The channel/thread/ephemeral routing determines where responses appear - critical for the "threads propose, channels decide" pattern
- **Button handlers** - Interactive elements must work flawlessly since approvals and objections are core to the lifecycle
- **Rate limiting** - Slack API limits are strict, getting throttling right prevents production issues

</essential>

<specifics>
## Specific Ideas

- **Fresh start** - Build purely from spec, no v1.x patterns to carry over
- Follow spec Part 9 exactly for:
  - `SlackWriteTarget` enum (CHANNEL, THREAD, EPHEMERAL)
  - `WRITE_TARGETS` mapping for message type routing
  - `SlackClient` class with `send()`, `post_to_channel()`, `post_to_thread()`, `post_ephemeral()`, `update_message()`
  - `SlackMessage` dataclass
  - `DashboardManager` for pinned status messages
  - `ButtonHandler` for routing button clicks

### Slash Commands (Skeleton Only)

Include basic `/maro` command infrastructure with `/maro help` working. The full command set will be implemented in later phases as features are built:

- `/maro help` - Show help (implement in Phase 2)
- `/maro status` - Show channel status (defer - needs entity projection)
- `/maro sync` - Check Jira sync status (defer - needs Jira integration)
- `/maro decisions` - List active decisions (defer - needs entity lifecycle)
- `/maro entities` - List all entities (defer - needs entity lifecycle)
- `/maro config` - Channel configuration (defer - needs operational features)

The `CommandHandler` structure and `/maro help` will be implemented. Other commands return "Coming soon" until their dependent features exist.

</specifics>

<notes>
## Additional Context

This phase depends on Phase 1 (Foundation) - specifically the domain types (ChannelId, ThreadTs, UserId, EntityId) which are already implemented.

Phase 3 (Intent & Modes) will add the routing layer that classifies messages and decides what to do. This phase just provides the plumbing.

The spec defines these handlers will be created:
- Button handlers for approve/object/discuss actions
- Message event handlers for incoming messages
- The Dashboard Manager for maintaining the pinned status message

</notes>

---

*Phase: 02-slack-integration*
*Context gathered: 2026-02-02*
