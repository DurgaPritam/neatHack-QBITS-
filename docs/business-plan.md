# PreJudge: business plan (final model, v3)

PreJudge is an AI agent that audits hackathon projects against the judging rubric before the real
judges do: a score, a fix list, README claims checked against the code, and a roast. This plan
covers **Oct 2026 – Sep 2028 (24 months), in USD**. Free pilots run in Q4 2026; paid sales start in
**Jan 2027**.

Built with cfo.ai: [shared model](https://cfo.ai/s/xBCsLLiMtconXUBf) · raw notes:
[cfo-ai-notes-raw.md](cfo-ai-notes-raw.md)

> **Assumption to confirm:** starting cash is a **$2,000 placeholder**. The plan holds as long as
> we start with at least about $250 (lowest cash in Main is $1,748).

## Customers and pricing

| Plan | Price | Audits included | Monthly churn | New customers, first paid month (growth/mo) |
|---|---|---|---|---|
| Hackathon organizers | $199/mo | 150/mo | 6% | 1 (8%) |
| Accelerators & incubators | $499/mo | 40/mo | 3% | 0.5 (6%) |
| Companies (internal hackathons) | $999/mo | 80/mo | 2.5% | 0.25 (6%) |
| Pay per event | $49 up to 50 teams · $149 for 51–300 teams | one per team | — | 4 events in Jan 2027 (+8%/mo) |
| Free tier (individual teams) | $0 | 5,000/mo in total | — | growth channel, booked as marketing |

Event mix assumption: 60% small (about 25 teams), 40% large (about 120 teams). That gives an
average of $89 and about 63 audits per event.

## Costs

| Cost | v3 assumption |
|---|---|
| AI per audit | **$0.005 quick, $0.02 deep, 70% quick-only = $0.0095 blended** |
| Hosting | $20/mo minimum + $2 per 1,000 audits (estimate); about $25/mo by Sep 2028 |
| Card fees | 3% of revenue (about 10× the AI bill) |
| Marketing | $1,000/mo from launch |
| Free tier AI | about $48/mo (5,000 audits × $0.0095) |
| Team | Founder unpaid. Hires in Jun 2027 ($3,000/mo), Oct 2027 ($2,500), Mar 2028 ($3,000), each +15% overhead |

**Where the AI cost comes from.** Our neatlogs traces measured about 2.6k LLM tokens per quick audit
and about 15k per deep audit (see [EVIDENCE.md](../EVIDENCE.md)). At Groq's list price for our
primary model, qwen3.8-27b ($0.80 per million input tokens, $4.00 per million output), that is
about $0.003–0.005 per quick audit and about $0.018 per deep audit. Calls that rotate onto
gpt-oss models cost 5–7× less, so the plan's numbers are an upper bound.

Total monthly costs: $68 before launch, about $1,100 after launch, about $4,690 once the first hire
starts (Jun 2027), and about $11,660 by Sep 2028, of which payroll is 84%.

## Results

| | **Main** | Upside | Downside |
|---|---|---|---|
| Profitable every month from | **Feb 2027** | Jan 2027 | never |
| Lowest cash | **$1,748** (Jan 2027) | $1,798 (Dec 2026) | below zero from Jun 2027 |
| Runway | **never runs out, no raise needed** | never runs out | runs out Jun 2027 |
| Gross margin, Sep 2028 | **97%** | 97% | 96% |
| Monthly revenue, Sep 2028 | **$24,651** (about $296k/yr) | $61,683 (about $740k/yr) | $5,918 (about $71k/yr) |
| Cash, Sep 2028 | **$89,522** | $370,775 | −$77,217 |

- **Upside:** higher prices, faster sales, lower churn.
- **Downside:** lower prices, slower sales, higher churn, and the paid launch slipping to Apr 2027.
- A $150k pre-seed raise is modelled as a separate, optional scenario. Main doesn't need it.

## How the model changed: v1 → v2 → v3

| | v1: first draft | v2: business model added | **v3: final** |
|---|---|---|---|
| AI cost per audit | $0.40 (estimate) | $0.40 (placeholder split) | **$0.0095 (measured)** |
| Revenue streams | licenses | + $49 flat events, 500 free audits | **+ size-based events, 5,000 free audits** |
| Funding | $150k raise, May 2027 | bootstrapped | **bootstrapped** |
| Profitable every month from | Nov 2027 | Nov 2027 | **Feb 2027** |
| Lowest cash | $322 | −$482 | **$1,748** |
| Runway | OK only because of the raise | runs out Jan–Mar 2027 | **never runs out** |
| Gross margin, Sep 2028 | 85% | 83% | **97%** |
| Monthly revenue, Sep 2028 | $22,992 | $23,905 | **$24,651** |
| Cash, Sep 2028 | $193,878 (incl. raise) | $43,824 | **$89,522** |

**v1 → v2: add the event plan and free tier, drop the raise.**
Without the raise, two assumptions opened a cash gap at launch: the $0.40 AI guess and a $300 flat
hosting bill. The flat $49 event price also lost money on any event above about 122 teams
($49 / $0.40).

**v2 → v3: replace guesses with measurements.**
- Our neatlogs traces showed AI costs about 42× less than the guess ($0.0095 vs $0.40), and
  hosting is $20, not $300. That moved break-even nine months earlier (Nov 2027 → Feb 2027)
  and closed the cash gap.
- Size-based event pricing raised revenue per event by about 80%.
- Cheap AI is what makes a 10× bigger free tier (500 → 5,000 audits) affordable.

## Key risks

1. **Sales speed is a guess.** We have no paying customers yet, and the Downside shows slow sales
   hurt more than anything else in the model. The top priority is converting pilots to paid.
2. **Organizer churn (6%/mo)**, because hackathons are seasonal. Annual contracts would protect the
   largest customer group.
3. **AI cost depends on the provider.** A pricier model or a Groq price rise lowers margins, but
   even at the original $0.40 guess gross margin stays around 83%.
4. **Small events can undercut the license.** Four small events ($196) cost less than one month of
   the $199 license. Raising the small-event price to $59 fixes this.
5. **The free tier earns nothing directly.** Its value depends on teams converting to paid plans,
   and we haven't measured that conversion rate yet.
6. **The founder is unpaid.** That's fine for a hackathon, not for a company. A $1,500/mo founder
   salary still leaves Main profitable from about Mar 2027.
7. **Mix guesses.** The 60/40 split of small and large events, the team counts per event, and the
   $2 per 1,000 audits for hosting are all assumptions.

## Hiring rule: hire only after the revenue is there

Make each hire only when **both** are true:

1. Last month's gross profit covers current operating costs **plus** the new hire's full monthly
   cost (salary + 15%).
2. Cash covers **3 months** of that hire's cost.

In Main, this lines up roughly with the June 2027 hire. In the Downside the rule never triggers,
which keeps it from becoming a $77k hole, since hires drive almost all of its losses. (A Downside
scenario with hires held back hasn't been modelled yet.)
