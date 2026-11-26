"""What the AI models cost: the one table the Assistant's cost counter, the Setup screen, the Listener's estimate and the
guide (docs/guides/09-setup-and-ai.md, which a test holds equal to this) all read.

Prices are $ per million tokens, list prices checked on CHECKED. Change a price here and nowhere else, then the guide's
table (a test fails until the two agree) and CHECKED.
"""

import datetime

CHECKED = "2026-11-26"

# The model the Assistant uses until the person picks another (a model they saved is always kept).
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"

CACHE_WRITE = 2.0           # the 1-hour prompt cache costs this many times the input price to write

# Claude: (input, output, cache read). The cache read is NOT one fixed share of the input price: as in this table, a
# tenth for Haiku 5.5 and the older models, a twentieth for Sonnet 5.5 and Opus 5.5, a fortieth for Fable 5.2. These
# numbers were not checked against the price pages when this was written (no internet then): check them there before
# a release. A test pins the ratios, so a changed number is noticed and the guide's table is changed with it.
CLAUDE = {
    "claude-fable-5-2": (8.0, 40.0, 0.20), "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10), "claude-haiku-5-5": (0.10, 0.50, 0.01),
    # older models the person may have saved
    "claude-fable-5-1": (10.0, 50.0, 1.0), "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5": (5.0, 25.0, 0.5), "claude-opus-4-8": (5.0, 25.0, 0.5), "claude-opus-4-7": (5.0, 25.0, 0.5),
    "claude-opus-4-6": (5.0, 25.0, 0.5), "claude-sonnet-5": (2.0, 10.0, 0.2), "claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
}
# A higher price for a request whose whole prompt (input + cache writes + cache reads) is longer than the limit.
# Haiku 5.5: $0.10 / $0.50 up to 100,000 tokens, $0.50 / $2.50 beyond. Its cache read is a tenth of its input price in
# both tiers ($0.01 and $0.05).
TIERS = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}

LABELS = {"claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}

# Gemini Flash, paid tier. Each row is (first day it applies, input, output); a day belongs to the last row that has
# started. There is no cache discount in this estimate. Gemini's free tier is $0. A price change is a new row with its
# date: nothing else in the app has to be touched, and a cost worked out for a day uses the price of that day.
GEMINI_FROM = (("2000-01-01", 0.75, 3.75),       # the introductory price
               ("2027-01-01", 1.50, 7.50))
GEMINI = dict(label="Gemini Flash (paid tier)",
              note=(f"introductory price through {(datetime.date.fromisoformat(GEMINI_FROM[1][0]) - datetime.timedelta(days=1)).isoformat()}; "
                    f"${GEMINI_FROM[1][1]:.2f} / ${GEMINI_FROM[1][2]:.2f} from {GEMINI_FROM[1][0]}"))


def today():
    """Today's date (one place, so a test can pass another day)."""
    return datetime.date.today()


def gemini_price(day=None):
    """(input, output) in $ per million tokens at Gemini Flash's paid tier on `day` (a date, or 'YYYY-MM-DD'; default
    today): the last row of GEMINI_FROM whose first day is not after it."""
    d = str(today() if day is None else day)[:10]
    row = GEMINI_FROM[0]
    for r in GEMINI_FROM:
        if r[0] <= d:
            row = r
    return row[1], row[2]


def claude_price(model, prompt_tokens=0):
    """(input, output, cache read) for one request on this Claude model, or None when the model is not in the table."""
    base = CLAUDE.get(model)
    tier = TIERS.get(model)
    if base is not None and tier and prompt_tokens > tier[0]:
        return tier[1]
    return base


def claude_cost(model, inp=0, out=0, cw=0, cr=0):
    """Dollars for ONE request (its input, output, cache-write and cache-read tokens), or None for an unknown model."""
    pr = claude_price(model, inp + cw + cr)
    if pr is None:
        return None
    pi, po, pc = pr
    return (inp * pi + cw * pi * CACHE_WRITE + cr * pc + out * po) / 1e6


def gemini_cost(inp=0, out=0, day=None):
    """An estimate in dollars at Gemini Flash's paid-tier price on `day` (default today), every input token at full price."""
    pi, po = gemini_price(day)
    return (inp * pi + out * po) / 1e6


def for_setup(model, long=False):
    """The Setup screen's view of a Claude model: label, input, output, cached and 1-hour write price. long=True is the
    higher tier of a model that has one (a very long session), else the ordinary price."""
    pi, po, pc = (TIERS[model][1] if long and model in TIERS else CLAUDE[model])
    return dict(label=LABELS[model], inp=pi, out=po, cached=pc, write=pi * CACHE_WRITE)


def money(x):
    """A dollar price as the guide writes it: $2, $0.10, $0.75."""
    s = f"{x:.2f}"
    return "$" + (s[:-3] if s.endswith(".00") else s)
