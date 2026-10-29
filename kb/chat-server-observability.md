# Chat server with Prometheus metrics (M-A, step 1)

Multi-client Java chat server (thread per client, rooms, private messages,
register/login) with a `/metrics` endpoint for Prometheus. No dependencies:
builds with plain `javac` (JDK 17+).

```bash
javac -d out src/*.java
java -cp out ChatServer                 # chat on :5000, metrics on :9100
java -cp out ChatClient                 # in another terminal

curl localhost:9100/metrics
curl localhost:9100/healthz             # liveness  (used by Kubernetes later)
curl localhost:9100/readyz              # readiness: 200 once the chat port is bound
```

Settings (environment variables): `CHAT_PORT` (5000), `METRICS_PORT` (9100),
`CHAT_LOG_MESSAGES` (`true`; set `false` under load so console printing doesn't
distort latency).

Tests (no framework yet; 28 checks, starts the real server on free ports):

```bash
javac -d out src/*.java test/*.java && java -ea -cp out ChatServerTest
```

## Metrics

| Metric | Type | What it answers |
|---|---|---|
| `chat_active_connections` | gauge | How many sockets are open right now (including clients still logging in)? |
| `chat_logged_in_users` | gauge | How many people can actually chat? |
| `chat_connections_accepted_total` | counter | Connection rate: `rate(...[1m])` |
| `chat_messages_processed_total{type}` | counter | Message rate by kind: broadcast, private, join, leave, who, quit |
| `chat_message_handling_seconds` | histogram | p50/p95 handling time: `histogram_quantile(0.95, rate(..._bucket[5m]))` |
| `chat_username_rejections_total` | counter | How often a username collision is refused |
| `chat_login_failures_total` | counter | Logins dropped after 3 wrong passwords (a spike can mean password guessing) |
| `process_start_time_seconds` | gauge | Detects restarts |

**What the latency histogram measures:** from the moment the server has read a full
line to when it has finished writing it to every recipient. That is the server's own
work, including fan-out to everyone in the room. It does not include network time,
which the server can't see; the load-test client in step 5 measures end to end.

**Why hand-written instead of the Prometheus Java client:** the code has no build tool
yet, and this keeps it at zero dependencies. The format is the standard text exposition
format, checked with the official Python parser (`prometheus_client.parser`). Swapping
in `io.prometheus:prometheus-metrics-core` later only touches `Metrics.java`.

## Changes to the v4c code

All marked in the source:

- `[metrics]` lines in `ClientHandler` and `ChatServer`; the message `if`-chain moved
  into `handleLine()` so each line can be timed and labelled.
- `[fix]` **Broadcast reached clients that hadn't logged in.** `broadcastToRoom` wrote to
  every handler in the list, including clients still at the username/password prompt.
  A client whose thread hadn't set `out` yet caused a `NullPointerException` in the
  *sender's* thread, which disconnected the sender. It now only writes to logged-in
  clients. The test `client at the login prompt does not receive chat` fails on the
  old code and passes on the new.
- `[fix]` `out`, `username`, `currentRoom` are `volatile`: they are written by one
  client's thread and read by others (broadcast, `/who`, `/msg`).
- `[fix]` "has left the chat" is only announced for users who had joined; `/msg` can't
  target someone still at the password prompt.
- Ports come from environment variables so Docker and Kubernetes can set them.
