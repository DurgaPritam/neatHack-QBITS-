"""'Write my cfo.ai prompt': a ready-to-paste prompt for Ari (cfo.ai's assistant) built from the
cost/usage/pricing numbers actually written in the repo's README, with [___] for the rest.

At most one LLM call. Every number in the model's output must appear in the README snippets we
found; any other number becomes [___]. The export-and-link reminder is added by code.
"""
import json
import re

from pydantic import BaseModel, Field

from app.agent.loop import ask_json
from app.agent.prompts import SECURITY_RULES, untrusted
from app.extras import EXTRAS_VERSION
from app.llm import BudgetExhausted, LLM, LLMError
from app.tools.github import GitHubClient, GitHubError, parse_repo_url

BLANK = "[___]"
_KEYWORDS = re.compile(r"\$|€|₹|£|\bprice|pricing|\bcost|\bper (month|year|audit|run|user|seat|call|request)|"
                       r"/mo\b|/month|\btokens?\b|\busers?\b|\bcustomers?\b|\bsubscri|\brevenue|\bmargin|\bchurn|"
                       r"\bhosting|\bserver|\bruns?\b.{0,20}\bper\b|\blatency|\bconversion|\bfree tier|\bplan\b", re.I)
_NUMBER = re.compile(r"\d")
_MONEYISH = re.compile(r"(?:[$€₹£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?)|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:%|k\b|K\b|ms\b|"
                       r"tokens?\b|users?\b|customers?\b|/mo\b|/month\b|per month\b|requests?\b|calls?\b|seats?\b))")

FIELDS = [  # (label, keywords that make a snippet relevant)
    ("Pricing (plans and price per month or per unit)", re.compile(r"price|pricing|\$\d+\s*/|per (month|seat|user)|plan", re.I)),
    ("Cost to serve one run/request (AI + infra)", re.compile(r"cost|per (audit|run|call|request)|tokens?", re.I)),
    ("Hosting / fixed monthly costs", re.compile(r"hosting|server|ec2|vercel|per month|/mo", re.I)),
    ("Expected usage (runs or requests per customer per month)", re.compile(r"per (day|month|hour)|requests?|runs?|calls?", re.I)),
    ("Customers or users at launch and monthly growth", re.compile(r"users?|customers?|teams?|growth|signups?", re.I)),
    ("Starting cash / funding", re.compile(r"cash|funding|raise|bootstrap", re.I)),
]


def number_snippets(readme: str, limit: int = 14) -> list[str]:
    """README lines that mention money/usage/pricing words AND contain a number (trimmed)."""
    out = []
    for line in (readme or "").splitlines():
        line = " ".join(line.strip().strip("|-*#>").split())
        if 8 <= len(line) and _NUMBER.search(line) and _KEYWORDS.search(line) and not line.startswith(("http", "![")):
            out.append(line[:180])
        if len(out) >= limit:
            break
    return out


def _known(text: str, snippets: list[str]) -> str:
    """Numbers not present in the README snippets become [___]."""
    known = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", " ".join(snippets))}

    def keep(m: re.Match) -> str:
        nums = [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", m.group(0))]
        return m.group(0) if nums and all(n in known for n in nums) else BLANK
    return _MONEYISH.sub(keep, text or "")


REMINDER = ("When the plan is done: export it from cfo.ai, share the link, and put that link in the README "
            "(with the pricing, costs, revenue and runway it shows) so judges can open it.")


def template(repo: str, desc: str, snippets: list[str]) -> str:
    lines = [f"Hi Ari. Build a 24-month business plan for {repo}: {desc or BLANK}.", "",
             "Use these numbers (from our README):" if snippets else "We don't have numbers yet; fill the blanks with us:"]
    lines += [f"- {s}" for s in snippets[:8]]
    lines += ["", "Model these, using the numbers above where they apply:"]
    for label, rx in FIELDS:
        hit = next((s for s in snippets if rx.search(s)), None)
        lines.append(f"- {label}: {('see: ' + hit[:90]) if hit else BLANK}")
    lines += ["", "Show monthly revenue, costs, gross margin, cash and runway, a base/upside/downside scenario, "
              "and the month we break even. Flag any assumption that looks unrealistic.", "", REMINDER]
    return "\n".join(lines)


class _Prompt(BaseModel):
    prompt: str = Field(max_length=3000)


ARI_SYSTEM = f"""You write one prompt that a hackathon team will paste into Ari, cfo.ai's AI financial analyst,
to build their business plan.
{SECURITY_RULES}
Return JSON {{"prompt": "..."}}. The prompt must:
- describe the product in one line, then list the numbers given (pricing, cost per run, hosting, usage,
  customers, cash) exactly as written in the README snippets;
- use [___] for every number that is NOT in the snippets (never invent, round or estimate a number);
- ask for a 24-month plan with monthly revenue, costs, gross margin, cash, runway, break-even and
  base/upside/downside scenarios. Under 220 words. Plain text, no markdown headings."""


async def fetch_readme(repo_url: str) -> str:
    try:
        async with GitHubClient() as gh:
            return (await gh.get_readme(parse_repo_url(repo_url)))["text"] or ""
    except (GitHubError, ValueError, KeyError):
        return ""


async def ari_prompt(report: dict, llm: LLM | None, readme: str | None = None) -> dict:
    repo = (report.get("repo") or {}).get("full_name") or report.get("repo_url", "")
    desc = " ".join(((report.get("repo") or {}).get("description") or "").split())[:160]
    if readme is None:
        readme = await fetch_readme(report.get("repo_url") or f"https://github.com/{repo}")
    snippets = number_snippets(readme)
    text, source = template(repo, desc, snippets), "template"
    if llm is not None:
        messages = [{"role": "system", "content": ARI_SYSTEM},
                    {"role": "user", "content": f"Product: {repo} — {desc or 'no description'}\n\nREADME number snippets:\n"
                     + untrusted("readme_numbers", json.dumps(snippets, indent=1))}]
        try:
            out = await ask_json(llm, "ari_prompt", messages, _Prompt, max_tokens=700)
        except (LLMError, BudgetExhausted):
            out = None
        if out and out.prompt.strip():
            text, source = _known(out.prompt.strip(), snippets) + "\n\n" + REMINDER, "llm"
    return {"version": EXTRAS_VERSION, "source": source, "prompt": text, "numbers_found": snippets,
            "blanks": text.count(BLANK)}
