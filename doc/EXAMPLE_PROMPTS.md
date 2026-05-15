# Aurora — Example Prompts by Role

A reference guide for users from different disciplines. Aurora's strength is cross-body synthesis: a single question can draw from Wi-Fi Alliance whitepapers, WBA Extranet working-group minutes, IEEE 802.11 drafts, and IETF RFCs simultaneously — content that would normally require separate logins, subscriptions, or meeting attendance.

---

## How to Read This Guide

- **@ mentions** pin results to a specific source group (e.g. `@wifi8mtg`, `@wba`, `@causeway`)
- **No @ mention** = Aurora searches everything and picks the best sources
- Pipeline times shown are for the **fast** route on warm cache; cold first-run is typically 2× slower

---

## Tested Demo Questions

These were run against the production system (2026-05-15) with fast-pipeline forced. Results are repeatable on warm cache.

| # | Question | Pipeline | Time | Confidence | Notes |
|---|---|---|---|---|---|
| 1 | What compliance requirements exist for Wi-Fi 6E devices? | fast | 11.4s | High 82% | Regulatory + certification synthesis |
| 2 | What is spatial reuse and how is it implemented in Wi-Fi 6? | fast | 9.5s | High 96% | Technical deep-dive |
| 3 | What is the difference between Wi-Fi 7 and Wi-Fi 8? | fast | 7.8s | High 82% | Comparison across generations |
| 4 | What WBA workgroups are focused on Wi-Fi security topics? | fast | 5.3s | Low 44% | WBA Extranet — best with `@wba` |
| 5 | Explain the roaming problem caused by sticky clients | fast | 7.6s | High 96% | Pulls internal WG meeting minutes |
| 6 | Summarise the latest Wi-Fi Alliance Causeway workgroup activity | fast | 11.7s | Med 46% | Use `@causeway` for best results |
| 7 | What has the WBA AI/ML for Wi-Fi workgroup produced? | fast | 5.0s | High 80% | Use `@wba` to pin to WBA Extranet |
| 8 | @wifi8mtg what has been discussed recently in the Wi-Fi 8 task group? | fast | 7.5s | High 98% | Best answer — internal MRD drafts |

**Tip:** Questions 4, 6, 7 improve significantly with an @ mention — see the role-specific prompts below for the right syntax.

---

## Role-Based Prompt Guide

### Product Manager

*Goal: track roadmap inputs, certification timelines, and competitive positioning without reading every working-group document.*

```
What features is Wi-Fi 8 targeting, and which are in the Market Requirements Document?
```

```
@wifi8mtg what certification milestones are planned and what timeline is the task group targeting?
```

```
What new Wi-Fi Alliance certification programmes were announced in the last 6 months, and what devices do they cover?
```

```
How does Wi-Fi 7 Multi-Link Operation change the competitive landscape for enterprise access points?
```

```
What are the key themes from recent Wi-Fi industry events?
```

---

### Solutions Architect / Field CTO

*Goal: understand interoperability requirements, deployment implications, and cross-standard dependencies.*

```
What compliance requirements exist for Wi-Fi 6E devices in Europe and the US?
```

```
Explain the roaming problem caused by sticky clients and what standards address it
```

```
What is the difference between Wi-Fi 7 and Wi-Fi 8, and what should architects plan for in enterprise deployments?
```

```
What is spatial reuse and how does BSS coloring improve performance in dense environments?
```

```
How does OpenRoaming work and what does it require from network operators?
```

```
What has the WBA Next Gen Hotspot workgroup published on carrier Wi-Fi convergence?
```

---

### Feature Developer / Engineer

*Goal: understand exact specification detail, protocol behaviour, and what working groups have formally agreed.*

```
@wifi8mtg what has been discussed recently in the Wi-Fi 8 task group?
```

```
What does the 802.11be amendment specify for Multi-Link Operation power management?
```

```
What IETF RFCs are relevant to Wi-Fi authentication and identity federation?
```

```
What are the TWT enhancements proposed for Wi-Fi 8 and how do they differ from Wi-Fi 6 TWT?
```

```
What does the WFA Security task group say about PMF enforcement in enterprise deployments?
```

```
@causeway what was discussed in the last Wi-Fi 7 task group meeting?
```

---

### Standards & Policy Liaison

*Goal: track new drafts, formal decisions, regulatory submissions, and cross-body liaison activity.*

```
What new IETF RFCs or advancing internet-drafts are relevant to Wi-Fi security or roaming?
```

```
What regulatory submissions has the Wi-Fi Alliance made on 6 GHz spectrum in the last year?
```

```
What AFC requirements apply to outdoor Wi-Fi 6E in the United States?
```

```
What IEEE 802.11 amendments are currently in progress and what is their expected timeline?
```

```
What liaison letters have been exchanged between IETF and IEEE 802.11 recently?
```

```
@wba what is the status of the WBA OpenRoaming programme and its latest specifications?
```

---

### UX / Design Researcher

*Goal: understand user-facing capabilities, experience improvements, and device behaviour in plain terms.*

```
What roaming improvements does Wi-Fi 7 bring for mobile users moving between access points?
```

```
How does Target Wake Time (TWT) in Wi-Fi 6 improve battery life for IoT and mobile devices?
```

```
What is the Wi-Fi CERTIFIED Optimized Connectivity programme and what experience does it deliver?
```

```
What user-experience problems does Multi-Link Operation in Wi-Fi 7 solve?
```

```
What are the latest Wi-Fi Alliance certifications that affect device user experience?
```

---

## System Agent Templates

*Admin-configured, shared feeds — set up once, visible to all users in the relevant group.*

### Standards Monitoring — All Bodies

> Monitor all IETF, IEEE 802.11, WFA Causeway, and WBA workgroup activity. Weekly digest of: new drafts submitted, decisions reached in working-group minutes, and open issues still under debate. Cross-reference against known product feature areas where possible.

**Cadence:** Weekly digest  
**Best for:** Standards team, programme managers

---

### Product Roadmap Intelligence

> Each week, summarise what Wi-Fi standards activity is most relevant to product roadmap decisions — new certification programmes, upcoming Wi-Fi Alliance press releases, and any features entering the WFA Causeway requirements pipeline. Flag anything that changes a timeline or introduces a new interoperability requirement.

**Cadence:** Weekly digest  
**Best for:** Product management, strategy

---

### Wi-Fi Security Monitoring

> Weekly: summarise new security-related contributions across IETF SEC area, WBA PKI workgroup, and WFA Security task group. Flag any changes to WPA3/OWE/PMF specifications, AFC security requirements, or identity/roaming security proposals.

**Cadence:** Weekly digest  
**Best for:** Security team, compliance

---

### IoT & Device Certification Watch

> Monitor Matter, Wi-Fi for Matter, WFA IoT certification updates, and relevant IETF IoT working groups. Alert on: new certification announcements, changes to power/spectrum requirements for IoT profiles, and device compliance guidance updates.

**Cadence:** Daily digest  
**Best for:** IoT product team, hardware engineers

---

## Personal Agent Templates

*Per-user, configured via Profile → My Agents. Each agent learns from feedback over time.*

### Product Manager — Wi-Fi 7/8 Roadmap Tracking

> I'm a product manager responsible for our Wi-Fi 7 and Wi-Fi 8 product roadmap. Track the Wi-Fi 8 task group (WiFi8MTG), Wi-Fi 7 task group, and related WFA certification programmes. Weekly brief on: what features are being added to the Market Requirements Document, what certification milestones are approaching, and any competitive positioning language from Wi-Fi Alliance press releases. Flag anything that affects our 2026 product launch timeline.

**Tone:** Analytical  
**Cadence:** Weekly digest

---

### Solutions Architect — Enterprise Wi-Fi Design

> I'm a solutions architect designing large enterprise Wi-Fi deployments. I need to stay current on 802.11k/v/r roaming improvements, BSS coloring, OFDMA, and MLO multi-link operation. Weekly summary of: new technical guidance documents, interoperability test results, sticky client and roaming issue discussions across task groups, and any new Wi-Fi Alliance certification relevant to enterprise vendors.

**Tone:** Technical  
**Cadence:** Weekly digest

---

### Feature Developer — Wi-Fi Security Features

> I work on Wi-Fi security features including WPA3, PMF, and SAE. Monitor IEEE 802.11, IETF LAMPS, IETF DANCE, and WFA Security task groups. Alert me when: new errata or amendments touch authentication or key exchange, there are minutes from the WFA Security task group, or any RFC or internet-draft relevant to Wi-Fi authentication advances to a new stage.

**Tone:** Technical  
**Cadence:** Daily digest

---

### Standards Liaison — Policy & Regulatory

> I track standards and regulatory developments for our company's Wi-Fi strategy. Weekly: new IETF RFCs or advancing drafts in WIT/SEC/INT areas, IEEE 802.11 liaison letters, WFA regulatory submissions, and any AFC or 6 GHz spectrum policy developments in EU, US, or APAC. Tone should be concise and executive — highlight decisions, not discussions.

**Tone:** Executive  
**Cadence:** Weekly digest

---

### UX Researcher — Wi-Fi User Experience

> I work on user experience for Wi-Fi connected devices. Track roaming experience improvements, power management (TWT, MLPM), and latency/QoS features like OFDMA and QoS Management. Weekly: what new user-experience capabilities are being standardised, what certification programmes address UX (e.g. Wi-Fi CERTIFIED Optimized Connectivity), and any user-facing performance benchmarks published by Wi-Fi Alliance. Keep it non-technical — translate specs into user impact.

**Tone:** Balanced  
**Cadence:** Weekly digest

---

## Tips: @ Mentions and Source Filtering

| Syntax | What it does |
|---|---|
| `@wifi8mtg` | Pins results to the Wi-Fi 8 task group documents on WFA Causeway |
| `@wifi7mtg` | Pins results to the Wi-Fi 7 task group |
| `@causeway` | Searches across all WFA Causeway task groups |
| `@wba` | Searches the WBA Extranet (all programmes and workgroups) |
| `@broadcast` | Pins to the WFA Causeway Broadcast TG |
| `@security` | Pins to the WFA Causeway Security MTG |
| `@iot` | Pins to the WFA Causeway IoT MSTG |
| No @ mention | Aurora searches everything and picks the most relevant sources |

You can combine an @ mention with a natural question: `@wifi8mtg what are the open issues on multi-link power management?`

To join a workgroup and see its content by default, go to **Profile → Sources** and enable the relevant group. Your personal agent will also automatically weight those sources higher.
