# Aurora — Demo Setup & Recovery Playbook

The literal command sequence to get from a cold morning to a green demo. Walk through this with two terminal windows open: one for the production EC2 (`make connect_aurora_ec2`) and one for the demo laptop (local tools, ngrok).

If you're new to this playbook, **read it once end-to-end before running any command**. Several steps depend on the previous one not failing silently.

---

## T-1 hour — production data & service health

**Goal:** prove the production system is healthy, the data is fresh, and a smoke query lands.

```bash
# From your laptop, open an SSM session to the Aurora EC2.
make connect_aurora_ec2

# On the EC2:
sudo -i -u ec2-user
cd ~/octo-rapid-aurora/prod-deployment

# Service status — every row should be "running (healthy)".
docker compose ps

# If anything is restarting, tail its logs:
docker compose logs --tail 200 -f <service>
```

Health checks to confirm:

- `oracle` listening: `curl -sf http://localhost:8002/health && echo OK`
- `auth` listening: `curl -sf http://localhost:8001/health && echo OK`
- `backend` listening: `curl -sf http://localhost:8000/health && echo OK`
- Neo4j browser reachable from the bastion: open `http://<ec2-host>:7474/`, log in, run `MATCH (n) RETURN count(n);` — expect a non-trivial node count.

Then back on your laptop, open the production frontend in a browser, log in via SSO, and run a smoke query:

```
What is the difference between Wi-Fi 7 and Wi-Fi 8?
```

Expected: substantive multi-paragraph answer in 5–10 seconds, source list at the bottom.

If the answer is thin or "Unable to get a response", **stop and diagnose** — do not proceed to the demo. Common causes and fixes:

- *Empty answer from fast pipeline*: redis cache may contain a zero-node result. Flush (see "T-30 min" below).
- *Service error*: tail `oracle` logs for stack traces. Most often this is a Cypher syntax error in a new template — roll back to last known good if so.
- *"Unable to get a response" with the streaming SSE endpoint*: a recent fix added fast→baseline fallback in the streaming path. If you see this, the deploy may be missing — confirm `query.py` has the try/except around `engine.query()` in the streaming endpoint.

---

## T-30 min — cache warm-up

**Goal:** every query in the demo should return in <8 s. Cold queries are slower because the fast cache is empty.

Connect to redis on the production EC2:

```bash
# On the EC2:
docker compose exec redis redis-cli

# Flush all stale fast caches — this is safe; they regenerate on demand.
EVAL "local k=redis.call('keys',ARGV[1]) for i=1,#k,5000 do redis.call('del',unpack(k,i,math.min(i+4999,#k))) end return #k" 0 "fast:*"

# Exit redis-cli.
exit
```

Then run each demo query twice from the web UI: once to populate the cache, once to confirm it's fast. The queries to warm (from `DEMO_PLAN.md`):

1. `@wba what's new in NextGen Wi-Fi this month`
2. `What are the priorities of the IoT programme this quarter?`
3. `What is the difference between Wi-Fi 7 and Wi-Fi 8?`
4. `What has Qualcomm contributed to Wi-Fi 8 discussions?`
5. `@ietf show me recent drafts on 6 GHz spectrum`

If any of these return thin content, **swap in a fallback query from `DEMO_PLAN.md`** during the demo rather than improvising.

While you're here, also open the **Admin Monitoring** page and confirm:

- No "stalled" batches in the active list. If any, click **Mark failed** (or run `POST /admin/fix-stalled-batches`) to clear before the demo.
- The most recent WBA Extranet scrape completed within the last 24 hours. If not, trigger a manual run from System Config so fresh content lands before the demo.

---

## T-15 min — Teams ngrok tunnel

**Goal:** Teams bot reachable from the dev tenant via your laptop. Only relevant for the Teams portion of the demo.

On your laptop:

```bash
# Start the Teams bot locally pointing at the production Aurora backend.
cd /Users/bbonner/code/octo/octo-rapid-aurora/teams-agent

# .env should already be configured with BOT_ID / BOT_PASSWORD for the dev tenant
# and AURORA_BACKEND_URL pointing at the prod API.
npm run dev &

# Wait ~5 seconds for the bot to bind to 3978.
sleep 5
curl -sf http://localhost:3978/api/health && echo "Bot up"

# Open the ngrok tunnel.
ngrok http 3978
```

Copy the `https://...ngrok-free.app` URL ngrok prints.

Update the dev-tenant Bot Framework registration endpoint:

1. Go to the Azure portal in your dev tenant.
2. Bot Service → Aurora-dev → Configuration → Messaging endpoint.
3. Paste `https://<your-ngrok>.ngrok-free.app/api/messages`. Save.

Confirm end-to-end:

1. Open Microsoft Teams web in the dev tenant.
2. Send `help` to the Aurora bot. Expect the help card to render in <3 seconds.
3. Send `feed`. Expect at least one feed card.

If the help card doesn't render: check the bot's terminal for incoming POSTs. If nothing arrives, the ngrok endpoint is wrong. If POSTs arrive but the response fails, check `BOT_ID`/`BOT_PASSWORD` and the dev-tenant credentials.

---

## T-5 min — browser state & meeting room

**Goal:** zero fumbling once the camera is on.

- Two browser tabs, in this order left-to-right: **Aurora web** (left), **Teams web** (right).
- Both tabs zoomed to ~125% for readability on the projector.
- Aurora web in dark mode (toggle in user menu — defaults to system, force dark if your system is light).
- Aurora web has Preferences open in the sidebar but no groups joined yet — you'll join them live in Act 1.
- Network tab in DevTools closed. Console closed. No browser notifications.
- Teams web is in a personal chat with the Aurora bot — not a channel; channels add scroll and noise.
- Phone is on Do Not Disturb. Slack is closed. Email is closed.
- A glass of water within reach.

If you're projecting, run a 30-second test:

- Switch between tabs — confirm transitions are clean.
- Make a query in the web UI — confirm the typing speed is readable on the projector.
- Send a message to the bot — confirm the Teams chat is wide enough.

---

## During the demo — recovery playbook

One line per failure mode. Memorise these.

| Failure | Recovery |
|---|---|
| Query takes >15 s | Acknowledge ("let me ask a sharper version of that"), switch to the fallback query in `DEMO_PLAN.md`. |
| Query returns "Unable to get a response" | Reload the page, try once more. If it fails again, switch acts — do Act 4 (agents) and come back to Act 2 (member-only) later. |
| Cross-source answer is thin | Use the fallback: `What has Qualcomm contributed to Wi-Fi 8 discussions?` — narrower scope, reliably substantive. |
| Teams bot doesn't respond | Open the bot terminal — if no POSTs are arriving, ngrok dropped. Show the web feed instead, mention "Teams in dev tenant is on a tunnel — corporate is provisioning this week". |
| SSO redirect loops | Clear the corporate cookie, re-login. (Pre-stage by being logged in already — don't show the cold login on stage if you can avoid it.) |
| Monitoring page shows a stalled batch | Don't open the monitoring page. Cut Act 2 last 30 seconds. |
| Frontend shows a stack trace | Apologise once, refresh. If it returns, switch to demoing the Teams surface and come back to the web after Q&A. |
| LLM rate-limit / 429 | Wait ~10 seconds, try again. If persistent, you're on the wrong API key — check `OPENAI_*` env vars on prod. |
| Your laptop dies | Move to the backup laptop. The demo URL is the same. ngrok URL needs re-registering on the bot dev tenant (~3 min). |

---

## Post-demo — cleanup

```bash
# Kill the local Teams bot dev process and ngrok.
pkill -f "ngrok http 3978"
pkill -f "ts-node-dev"  # or whatever npm run dev spawns

# On the EC2: archive the demo-account chat history for the engagement retrospective.
docker compose exec postgres psql -U aurora -d aurora -c \
  "COPY (SELECT * FROM oracle_query_log WHERE user_id = '<demo-user-id>' AND created_at > '2026-05-18'::date) TO STDOUT WITH CSV HEADER;" \
  > ~/aurora-demo-queries-2026-05-18.csv
```

Notes:

- **Don't delete the demo account.** Future demos reuse it. Just clear the joined workgroups and topics from Preferences so the next demo can show the empty-state UI.
- **Revoke the ngrok URL.** If you keep it, anyone on the dev tenant could send messages to the bot pointing at production Aurora.
- **Capture the room reaction.** Five minutes after the demo, jot down the three questions or remarks that surprised you. Add them to the `DEMO_PLAN.md` Q&A section for next time.

---

## Reference — admin endpoints used during setup

| Endpoint | Purpose |
|---|---|
| `GET /admin/monitoring/batches` | Active scraper batches |
| `POST /admin/fix-stalled-batches` | Mark stalled batches as failed |
| `POST /scrape/manual/<datasource_id>` | Trigger a one-off scrape |
| `GET /admin/scheduler` | Curator + retriever schedule view |
| `redis-cli -h <host>` | Cache management |
| `docker compose exec neo4j cypher-shell -u neo4j -p <pwd>` | Direct Cypher |

All require admin role on the SSO account.
