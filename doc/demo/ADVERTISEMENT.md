# Aurora — Intranet Landing Page Copy

**Owner:** Office of the CTO, Rapid AI Innovation Team
**Surface:** Company-wide information site (intranet). This is the standing landing-page copy that lives after the launch announcement scrolls off.

The text below is markdown for easy paste into the intranet CMS. Replace the bracketed placeholders before publishing.

---

## Headline

# Aurora — standards body intelligence, on tap.

## Sub-head

*An AI assistant that reads the Wi-Fi Alliance, IETF, and IEEE so you don't have to. In your browser. In Teams. From the Office of the CTO Rapid AI Innovation Team.*

---

## What it does for you

> **Three short panels — pick the three personas most relevant to the target page; rotate them quarterly based on which audience needs the most uplift.**

### For Product Managers

You can't ship what you don't know is coming. Aurora reads every WBA NextGen call, every IETF draft, every Wi-Fi Alliance press release — and pulls the roadmap-shaping signal out for you. Ask it *"what changed in Wi-Fi 8 this month?"* and it'll answer with citations. Spin up a custom agent that posts a Monday brief to your Teams DM every week, on the topics your product depends on.

### For Solution Architects

Customers ask what new standards mean for their networks. The honest answer used to take an afternoon of reading. Aurora composes that answer in twenty seconds from the actual source documents — IEEE, WFA, WBA Extranet, IETF — and gives you the citations so you can stand behind it. Use it to brief customers. Use it to diff versions of a spec. Use it to find the one named person actually driving a thread.

### For Standards / Firmware / Chip engineers

You already track the working groups that matter. Aurora lets you stop dialling into the calls and reading the PDFs you don't have time for. It logs in to the WBA Extranet, follows the digest threads, and lets you `@wba_extranet_iot_p5g latest activity` to get the summary you'd otherwise have built by hand. Bodies are discarded after parsing — we keep the metadata and synopsis, not the source documents.

---

## How it works, in 60 seconds

1. **Log in with your Extreme SSO.** No signup form. Your user record is created on first login.
2. **Set up in the app.** Open Preferences, join the working groups you care about, mark the topics that matter to you. Sixty seconds.
3. **Use it.** Ask questions in plain English in the browser. Or install the Aurora app for Microsoft Teams and ask the bot directly.

---

## What's inside

- **Member-only standards intelligence.** Aurora authenticates against the WBA Extranet and reads workgroup digests that aren't on the public internet.
- **Cross-source synthesis.** One answer composed from IEEE, IETF, WBA, and WFA — with citations.
- **Custom agents.** Define your own AI assistant — name, persona, topics, cadence — and have it post daily or weekly digests to your feed or your Teams chat.
- **Working-group digests on demand.** `@source` mentions in chat give you targeted answers from one body without contamination from the others.
- **Knowledge graph foundation.** Aurora is built on Neo4j — every document, person, organisation, and topic is a node you can navigate. Useful when you need provenance.

---

## Get started

- **Try Aurora now:** `<aurora-internal-url>`
- **Install the Teams app:** `<teams-app-install-url>` *(available [date] — pending IT)*
- **Survey — five minutes:** `<microsoft-forms-url>`
- **Office hours:** Tuesdays & Thursdays 11:00–11:30, link in the [calendar invite]
- **Questions:** post in the `#aurora-pilot-feedback` Teams channel

---

## A note about the prototype

Aurora is a prototype from the **Office of the CTO, Rapid AI Innovation Team**. It is intentionally early — feature gaps and rough edges are expected. We are running a 25-person pilot the week of 2026-05-18, opening to a wider cohort the week after. Feedback shapes the next iteration. If something is missing or wrong, please tell us — that is the entire point.

---

## Call-to-action button text — A/B options

Pick the one that matches the intranet page's tone:

1. **Try Aurora →**
2. **Open Aurora →**
3. **Start asking →**
4. **Get a daily standards brief →** *(for a panel that leans into the agent story)*

---

## Asset list — for the design team

| Asset | Description | Recommended size |
|---|---|---|
| Hero screenshot | Aurora chat showing a `@wba` answer with the source list visible | 1600×900, dark mode |
| Mid-page screenshot | Agent Management page with the "Wi-Fi 8 Daily Brief" agent defined | 1400×800, dark mode |
| Teams screenshot | Teams chat with the Aurora bot returning a feed card | 1200×700 |
| Sub-head visual / logo | Aurora wordmark + OCTO Rapid AI sub-mark | SVG preferred, with raster fallback at 600×200 |
| Open Graph image | For when the page is shared in Teams chats | 1200×630 |

Screenshots should come from the production Aurora instance, with a sanitised demo account (no PII, no real workgroup digests visible in the frame).

---

## Footer

> **Prototype from the Office of the CTO, Rapid AI Innovation Team. We'd love your feedback — `<microsoft-forms-url>`.**
>
> Aurora respects your access permissions: you only see content from the working groups you've joined. Read more in the [security notes].
