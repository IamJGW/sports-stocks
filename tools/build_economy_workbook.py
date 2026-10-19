"""Build 'Stat Street Economy.xlsx' from the season CSVs in data/.

Usage (from sports-exchange/):  python3 tools/build_economy_workbook.py
Then recalculate it (LibreOffice) before reading values back. Every number the game uses is a formula driven by the
blue input cells, so Justin can tune the economy in Excel without rerunning this script.
"""
import csv
import random
import re

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

OUT = "Stat Street Economy.xlsx"
FONT = "Arial"
BLUE, GREEN = "0000FF", "008000"
YELLOW = PatternFill("solid", start_color="FFFF00")
HEAD = PatternFill("solid", start_color="1F3864")
BAND = PatternFill("solid", start_color="D9E1F2")
THIN = Border(bottom=Side(style="thin", color="999999"))
MONEY, MONEY0, PCT, PCT2, NUM1 = '$#,##0.00;($#,##0.00);"-"', '$#,##0;($#,##0);"-"', '0.0%;-0.0%;"-"', '0.00%;-0.00%;"-"', '0.0'

# Each sport: data files, the stats that score points (CSV key, label, default points), and Settings row.
SPORTS = [
    {"key": "NFL", "prior": "data/nfl_2024.csv", "test": "data/nfl_2025.csv", "prior_label": "2024", "test_label": "2025",
     "weeks": 18, "games": 17, "min_gp": 6, "listed": 120, "row": 12,
     "stats": [("pass_yd", "Passing yards", 0.04), ("pass_td", "Passing TDs", 4), ("int", "Interceptions thrown", -2),
               ("rush_yd", "Rushing yards", 0.1), ("rush_td", "Rushing TDs", 6), ("rec", "Receptions (half-PPR)", 0.5),
               ("rec_yd", "Receiving yards", 0.1), ("rec_td", "Receiving TDs", 6), ("two_pt", "2-point conversions", 2),
               ("ret_td", "Kick/punt return TDs", 6), ("fum_lost", "Fumbles lost", -2)]},
    {"key": "NBA", "prior": "data/nba_2025.csv", "test": "data/nba_2026.csv", "prior_label": "2024-25", "test_label": "2025-26",
     "weeks": 25, "games": 82, "min_gp": 25, "listed": 150, "row": 13,
     "stats": [("pts", "Points", 1), ("reb", "Rebounds", 1.2), ("ast", "Assists", 1.5), ("stl", "Steals", 3),
               ("blk", "Blocks", 3), ("tov", "Turnovers", -1), ("fg3m", "3-pointers made (bonus)", 0),
               ("dbl_dbl", "Double-doubles (bonus)", 0), ("tpl_dbl", "Triple-doubles (bonus)", 0)]},
    {"key": "NHL", "prior": "data/nhl_2025.csv", "test": "data/nhl_2026.csv", "prior_label": "2024-25", "test_label": "2025-26",
     "weeks": 27, "games": 82, "min_gp": 25, "listed": 150, "row": 14,
     "stats": [("goals", "Goals", 3), ("assists", "Assists", 2), ("shots", "Shots on goal", 0.5),
               ("ppg", "Power-play goals (bonus)", 0.5), ("ppa", "Power-play assists (bonus)", 0.5),
               ("wins", "Goalie wins", 4), ("goals_against", "Goals against (goalie)", -1),
               ("saves", "Saves (goalie)", 0.15), ("shutouts", "Shutouts (goalie)", 2)]},
]
# Position groups: athletes are priced against others in their group, so a group that tends to fall back next
# season (goalies, say) gets cheaper prices instead of quietly paying less. # Lean and repeat defaults come from tools/calibrate.py, averaged over 2023->2024 and 2024->2025.
# (name, sport, positions, lean toward group average, repeat factor)
GROUPS = [("NFL QB", "NFL", "QB", 0.07, 0.66), ("NFL RB", "NFL", "RB", 0.30, 0.77),
          ("NFL WR/TE", "NFL", "WR, TE", 0.38, 0.69), ("NBA", "NBA", "All", 0.10, 0.69),
          ("NHL skaters", "NHL", "C, LW, RW, D", 0.12, 0.84), ("NHL goalies", "NHL", "G", 0.65, 0.44)]
G0 = 19  # first group row on Settings
G1 = G0 + len(GROUPS) - 1


def group_of(sport, pos):
    if sport == "NFL":
        return {"QB": "NFL QB", "RB": "NFL RB"}.get(pos, "NFL WR/TE")
    if sport == "NHL":
        return "NHL goalies" if pos == "G" else "NHL skaters"
    return "NBA"


FIRST = 3  # first data row on the sport sheets (rows 1-2 are headers)


def font(cell, color=None, bold=False, size=10, italic=False):
    cell.font = Font(name=FONT, color=color, bold=bold, size=size, italic=italic)


def header(ws, row, labels, col=1):
    for i, text in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=text)
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def title(ws, text, sub=None):
    ws["A1"] = text
    font(ws["A1"], bold=True, size=14)
    if sub:
        ws["A2"] = sub
        font(ws["A2"], italic=True, color="555555")


def load(path):
    with open(path) as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def make_tickers(sports_rows):
    used, out = set(), {}
    for key, rows in sports_rows:
        for r in rows:
            name = re.sub(r"\b(Jr|Sr|II|III|IV|V)\.?$", "", r["name"]).strip()
            parts = re.sub(r"[^A-Za-z ]", "", name).upper().split()
            last, first = (parts[-1], parts[0]) if parts else ("X", "X")
            for cand in (last[:5], first[0] + last[:4], first[:2] + last[:3]):
                if cand not in used:
                    break
            else:
                n = 2
                while f"{last[:4]}{n}" in used:
                    n += 1
                cand = f"{last[:4]}{n}"
            used.add(cand)
            out[(key, r["id"])] = cand
    return out


def build():
    wb = Workbook()
    readme = wb.active
    readme.title = "Read Me"
    settings = wb.create_sheet("Settings")
    scoring = wb.create_sheet("Scoring")

    # ---- Load data: one row per athlete who played in the pricing season.
    data = []
    for sp in SPORTS:
        prior, test = load(sp["prior"]), load(sp["test"])
        rows = [r for r in prior.values() if float(r["gp"]) >= 1]
        rows.sort(key=lambda r: -sum(float(r[k]) * w for k, _, w in sp["stats"]) / float(r["gp"]))
        data.append((sp["key"], rows, test))
    tickers = make_tickers([(k, rows) for k, rows, _ in data])

    # ---- Scoring sheet
    title(scoring, "Scoring: fantasy points per stat", "Blue cells are inputs. Change a value and every sheet updates.")
    header(scoring, 4, ["Sport", "Stat", "Points each", "Data column"])
    row = 5
    for sp in SPORTS:
        sp["weight_rows"] = {}
        for key, label, pts in sp["stats"]:
            scoring.cell(row=row, column=1, value=sp["key"])
            scoring.cell(row=row, column=2, value=label)
            c = scoring.cell(row=row, column=3, value=pts)
            font(c, color=BLUE)
            c.number_format = "0.00"
            scoring.cell(row=row, column=4, value=key)
            for col in (1, 2, 4):
                font(scoring.cell(row=row, column=col))
            sp["weight_rows"][key] = row
            row += 1
        row += 1
    notes = [
        "Where these come from:",
        "NFL: standard scoring with half a point per catch (half-PPR), the default on Yahoo and Sleeper. Only QB, RB, WR "
        "and TE are listed; kickers and team defences are not athletes we can sell shares in.",
        "NBA: FanDuel-style points (points 1, rebounds 1.2, assists 1.5, steals 3, blocks 3, turnovers -1). The bonus rows "
        "start at 0 so you can try them.",
        "NHL: goals 3, assists 2, shots 0.5, plus a small power-play bonus. Goalie weights were tuned so about 33 goalies "
        "make the 150 listed, roughly one starter per team. The free feed has no hits or blocked shots, so defencemen "
        "score low; that is a known gap.",
    ]
    for i, text in enumerate(notes):
        c = scoring.cell(row=row + 1 + i, column=1, value=text)
        font(c, bold=(i == 0), italic=(i > 0))
    scoring.column_dimensions["A"].width = 8
    scoring.column_dimensions["B"].width = 30
    scoring.column_dimensions["C"].width = 12
    scoring.column_dimensions["D"].width = 16

    # ---- Settings sheet
    title(settings, "Settings: the economy's levers",
          "Blue = input you can change. Yellow = the key levers. Black = calculated. Green = pulled from another sheet.")
    glob = [
        (4, "Starting cash per player", 100000, MONEY0, "Play money each player starts with."),
        (5, "Target average starting price", 50, MONEY, "The average listed athlete in every sport starts at this price."),
        (6, "Weekly dividend yield (in season)", 0.02, PCT2,
         "Each week of his season, an athlete expected to play at last season's level pays this share of his price "
         "in dividends. Set per week, not per season, so a dollar earns at the same speed in every sport."),
        (7, "Value kept by an athlete who misses a whole season", 0.25, PCT,
         "Used for end-of-season prices: an athlete who played no games is valued at this share of his starting price."),
    ]
    for r, label, val, fmt, note in glob:
        font(settings.cell(row=r, column=1, value=label))
        c = settings.cell(row=r, column=2, value=val)
        font(c, color=BLUE)
        c.number_format = fmt
        if r in (5, 6):
            c.fill = YELLOW
        c.comment = Comment(note, "Stat Street")
        font(settings.cell(row=r, column=3, value=note), italic=True, color="555555")
    font(settings.cell(row=10, column=1, value="Per sport"), bold=True, size=11)
    header(settings, 11, ["Sport", "Regular-season weeks", "Games per team", "Min games to be listed",
                          "Listed athletes", "Prices set from", "Dividends tested on",
                          "Avg expected season fantasy pts (listed)", "Dividend rate ($ per fantasy pt per share)",
                          "Season dividend per share, avg athlete", "Listed (check)"])
    for sp in SPORTS:
        r, k = sp["row"], sp["key"]
        settings.cell(row=r, column=1, value=k)
        for col, val in ((2, sp["weeks"]), (3, sp["games"]), (4, sp["min_gp"]), (5, sp["listed"])):
            font(settings.cell(row=r, column=col, value=val), color=BLUE)
        settings.cell(row=r, column=6, value=sp["prior_label"])
        settings.cell(row=r, column=7, value=sp["test_label"])
        settings.cell(row=r, column=5).fill = YELLOW
        # Averaged from the group table below (leaning toward the group average keeps each group's average).
        settings.cell(row=r, column=8, value=f"=SUMIFS($I${G0}:$I${G1},$B${G0}:$B${G1},A{r})"
                      f"/SUMIFS($F${G0}:$F${G1},$B${G0}:$B${G1},A{r})").number_format = NUM1
        settings.cell(row=r, column=9, value=f"=$B$5*$B$6*B{r}/H{r}").number_format = '0.0000'
        settings.cell(row=r, column=10, value=f"=$B$5*$B$6*B{r}").number_format = MONEY
    settings.cell(row=12, column=2).comment = Comment(
        "NFL: 18 weeks (17 games plus a bye). NBA: about 25 weeks, late October to mid April. NHL: about 27 weeks, "
        "early October to mid April.", "Stat Street")
    settings.cell(row=12, column=5).comment = Comment(
        "How many athletes per sport can be traded. Athletes are ranked by fantasy points per game in the pricing "
        "season, among those who played at least the minimum games.", "Stat Street")

    font(settings.cell(row=G0 - 2, column=1, value="Per position group"), bold=True, size=11)
    header(settings, G0 - 1, ["Group", "Sport", "Positions", "Lean toward group average",
                              "Repeat factor", "Listed", "Avg pts per game (listed)",
                              "Expected season pts, avg athlete", "Listed x expected (helper)",
                              "Repeat factor seen in the test season"])
    for i, (g, sport, positions, lean, repeat) in enumerate(GROUPS):
        r = G0 + i
        sh = sport
        sp = next(x for x in SPORTS if x["key"] == sport)
        sp.setdefault("group_rows", []).append(r)
        vals = [g, sport, positions, lean, repeat]
        for j, v in enumerate(vals):
            cell = settings.cell(row=r, column=1 + j, value=v)
            font(cell, color=BLUE if j in (3, 4) else None, bold=(j == 0))
            if j in (3, 4):
                cell.fill = YELLOW
                cell.number_format = "0.00"
        games = f"INDEX($C$12:$C$14,MATCH(B{r},$A$12:$A$14,0))"
        sp.setdefault("group_formulas", []).append((r, g))
        settings.cell(row=r, column=8, value=f"=G{r}*{games}*E{r}").number_format = NUM1
        settings.cell(row=r, column=9, value=f"=F{r}*H{r}").number_format = NUM1
    settings.cell(row=G0, column=4).comment = Comment(
        "0 = price each athlete on his own points per game. 1 = price everyone in the group at the group average. "
        "In between pulls stars down and bargains up, because part of a great (or awful) season doesn't repeat. "
        "Defaults come from tools/calibrate.py, averaged over two pairs of seasons.", "Stat Street")
    settings.cell(row=G0, column=5).comment = Comment(
        "Next season's points as a share of this season's (after the lean), including games missed. A group that "
        "tends to fall back, like goalies, gets a lower factor and so cheaper prices, instead of quietly paying less "
        "than its price promised. Defaults come from tools/calibrate.py.", "Stat Street")

    # Out-of-sample evidence (static numbers from tools/calibrate.py, so they don't change with the levers).
    E0 = G0 + len(GROUPS) + 2
    font(settings.cell(row=E0, column=1, value="Evidence: share of promised dividends actually paid, equal dollars in "
                       "every listed athlete (from tools/calibrate.py; fixed numbers, not live)"), bold=True, size=11)
    header(settings, E0 + 1, ["How the factors were set", "NFL", "NBA", "NHL", "NHL skaters", "NHL goalies"])
    evidence = [("Before: one price rule for every sport and position, tested on 2024 to 2025", .79, .85, .91, 1.00, .50),
                ("Groups set on 2023 to 2024, tested on 2024 to 2025", .91, .89, 1.01, 1.04, .90),
                ("Groups set on 2024 to 2025, tested on 2023 to 2024", 1.06, 1.12, .99, .95, 1.11)]
    for i, row_vals in enumerate(evidence):
        for j, v in enumerate(row_vals):
            cell = settings.cell(row=E0 + 2 + i, column=1 + j, value=v)
            font(cell, italic=True)
            if j:
                cell.number_format = "0%"
    font(settings.cell(row=E0 + 5, column=1, value="Reading it: after the change, no sport comes out ahead in both "
                       "years; which sport paid most flips from year to year, which is luck rather than a built-in "
                       "edge. Goalies needed prices about 44% of a skater's for the same points, in both years."),
         italic=True)

    # ---- Sport sheets
    for sp, (key, rows, test) in zip(SPORTS, data):
        ws = wb.create_sheet(key)
        n = len(sp["stats"])
        s = sp["row"]
        c = {}
        col = 1
        for name in ("ticker", "name", "team", "pos", "group", "gp"):
            c[name] = col
            col += 1
        c["stats"] = col
        col += n
        for name in ("fp", "fpg", "elig", "rank", "listed", "lean", "gavg", "rep", "leaned", "expfp", "wkdiv", "price",
                     "gp2"):
            c[name] = col
            col += 1
        c["stats2"] = col
        col += n
        for name in ("fp2", "div", "ret", "wkret", "endfv", "chg"):
            c[name] = col
            col += 1
        sp["c"] = c
        last = FIRST + len(rows) - 1
        sp["last"] = last
        rng = lambda name, c=c, last=last: f"${L(c[name])}${FIRST}:${L(c[name])}${last}"
        sp["rng"] = rng

        labels = ["Ticker", "Athlete", "Team", "Pos", "Group", "Games"] + [lab for _, lab, _ in sp["stats"]] + [
            "Fantasy pts", "Pts per game", "Eligible (1=yes)", "Rank", "Listed (1=yes)", "Lean toward group avg",
            "Group avg pts per game", "Repeat factor", "Leaned pts per game", "Expected season pts",
            "Expected weekly dividend", "Starting price", "Games"] + \
            [lab for _, lab, _ in sp["stats"]] + [
            "Fantasy pts", "Dividends per share (season)", "Season dividend return", "Weekly dividend return",
            "End-of-season fair value", "Price change"]
        header(ws, 2, labels)
        ws.cell(row=1, column=c["gp"], value=f"Pricing season: {sp['prior_label']} stats")
        ws.cell(row=1, column=c["fp"], value="Listing and starting price")
        ws.cell(row=1, column=c["gp2"], value=f"Test season: {sp['test_label']} stats (what actually happened next)")
        ws.cell(row=1, column=c["fp2"], value="Dividends and returns")
        for colname in ("gp", "fp", "gp2", "fp2"):
            font(ws.cell(row=1, column=c[colname]), bold=True)
        ws.row_dimensions[2].height = 45

        S = f"Settings!${{}}${s}"
        rate, weeks, games = (S.format(x) for x in ("I", "B", "C"))
        yld, kept = "Settings!$B$6", "Settings!$B$7"
        gl = lambda col_letter, R: (f"INDEX(Settings!${col_letter}${G0}:${col_letter}${G1},"
                                    f"MATCH({L(c['group'])}{R},Settings!$A${G0}:$A${G1},0))")
        for i, r in enumerate(rows):
            R = FIRST + i
            t = test.get(r["id"])
            vals = [tickers[(key, r["id"])], r["name"], r["team"], r["pos"], group_of(key, r["pos"]), float(r["gp"])]
            for j, v in enumerate(vals):
                cell = ws.cell(row=R, column=1 + j, value=int(v) if isinstance(v, float) else v)
                font(cell, color=BLUE if j in (4, 5) else None)
            for j, (k, _, _) in enumerate(sp["stats"]):
                font(ws.cell(row=R, column=c["stats"] + j, value=float(r[k]) if "." in r[k] else int(r[k])), color=BLUE)
                tv = t[k] if t else "0"
                font(ws.cell(row=R, column=c["stats2"] + j, value=float(tv) if "." in str(tv) else int(tv)), color=BLUE)
            font(ws.cell(row=R, column=c["gp2"], value=int(float(t["gp"])) if t else 0), color=BLUE)

            def fp_formula(start):
                return "=" + "+".join(f"{L(start + j)}{R}*Scoring!$C${sp['weight_rows'][k]}"
                                      for j, (k, _, _) in enumerate(sp["stats"]))
            col_ = lambda name: f"{L(c[name])}{R}"
            lean, gavg, rep = col_("lean"), col_("gavg"), col_("rep")
            f = {
                "fp": fp_formula(c["stats"]),
                "fpg": f"=IF({col_('gp')}>0,{col_('fp')}/{col_('gp')},0)",
                "elig": f"=IF({col_('gp')}>={S.format('D')},1,0)",
                "rank": f"=IF({col_('elig')}=1,COUNTIFS({rng('elig')},1,{rng('fpg')},\">\"&{col_('fpg')})+1,\"\")",
                "listed": f"=IF({col_('elig')}=1,IF({col_('rank')}<={S.format('E')},1,0),0)",
                "lean": f"={gl('D', R)}",
                "gavg": f"={gl('G', R)}",
                "rep": f"={gl('E', R)}",
                "leaned": f"=(1-{lean})*{col_('fpg')}+{lean}*{gavg}",
                "expfp": f"={col_('leaned')}*{games}*{rep}",
                "wkdiv": f"=IF({col_('listed')}=1,{col_('expfp')}*{rate}/{weeks},\"\")",
                "price": f"=IF({col_('listed')}=1,{col_('wkdiv')}/{yld},\"\")",
                "fp2": fp_formula(c["stats2"]),
                "div": f"=IF({col_('listed')}=1,MAX(0,{col_('fp2')})*{rate},\"\")",  # never charge holders
                "ret": f"=IF({col_('listed')}=1,{col_('div')}/{col_('price')},\"\")",
                "wkret": f"=IF({col_('listed')}=1,{col_('ret')}/{weeks},\"\")",
                # Re-priced the same way from the test season's points per game.
                "endfv": f"=IF({col_('listed')}=1,IF({col_('gp2')}>0,((1-{lean})*{col_('fp2')}/{col_('gp2')}+{lean}*{gavg})"
                         f"*{games}*{rep}*{rate}/{weeks}/{yld},{col_('price')}*{kept}),\"\")",
                "chg": f"=IF({col_('listed')}=1,{col_('endfv')}/{col_('price')}-1,\"\")",
            }
            fmts = {"fp": NUM1, "fpg": NUM1, "lean": "0.00", "gavg": NUM1, "rep": "0.00", "leaned": NUM1,
                    "expfp": NUM1, "wkdiv": MONEY, "price": MONEY, "fp2": NUM1,
                    "div": MONEY, "ret": PCT, "wkret": PCT2, "endfv": MONEY, "chg": PCT}
            for name, formula in f.items():
                cell = ws.cell(row=R, column=c[name], value=formula)
                font(cell, color=GREEN if name in ("lean", "gavg", "rep") else None)
                if name in fmts:
                    cell.number_format = fmts[name]
        ws.freeze_panes = ws.cell(row=FIRST, column=c["gp"])
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 24
        for j in range(3, col):
            ws.column_dimensions[L(j)].width = 11
        ws.auto_filter.ref = f"A2:{L(col - 1)}{last}"

        # Settings formulas that summarise this sheet
        settings.cell(row=s, column=11, value=f"=COUNTIF({key}!{rng('listed')},1)")
        for col_i in range(1, 12):
            font(settings.cell(row=s, column=col_i), color=GREEN if col_i in (8, 11) else
                 (BLUE if col_i in (2, 3, 4, 5) else None), bold=(col_i == 1))
        for r in sp["group_rows"]:
            lst = f"{key}!{rng('listed')},1,{key}!{rng('group')},A{r}"
            settings.cell(row=r, column=6, value=f"=COUNTIFS({lst})")
            settings.cell(row=r, column=7, value=f"=IFERROR(AVERAGEIFS({key}!{rng('fpg')},{lst}),0)").number_format = NUM1
            settings.cell(row=r, column=10, value=f"=IFERROR(SUMIFS({key}!{rng('fp2')},{lst})/(F{r}*G{r}"
                          f"*INDEX($C$12:$C$14,MATCH(B{r},$A$12:$A$14,0))),\"\")").number_format = "0.00"
            for col_i in (6, 7, 8, 9, 10):
                font(settings.cell(row=r, column=col_i), color=GREEN if col_i in (6, 7, 10) else None)
    for col_i, w in zip(range(1, 12), (34, 12, 13, 12, 10, 11, 11, 13, 14, 14, 11)):
        settings.column_dimensions[L(col_i)].width = w
    settings.row_dimensions[11].height = 58
    settings.row_dimensions[G0 - 1].height = 58
    expl = [
        "How a starting price is set (all formulas, so changing a blue cell reprices everything):",
        "1. Score each athlete's pricing-season stats with the Scoring sheet, then divide by games played: points per game.",
        "2. Lean toward the group average: leaned pts per game = (1 - lean) x his pts per game + lean x his group's average.",
        "3. Expected season points = leaned pts per game x games per team x the group's repeat factor (which builds in "
        "games missed and how much the group tends to fall back).",
        "4. The dividend rate is set so the average listed athlete's season dividends = target price x weekly yield x "
        "season weeks. One rate per sport, so a point is worth the same to every athlete in that sport.",
        "5. Expected weekly dividend = expected season points x rate / weeks. Starting price = expected weekly dividend / "
        "weekly yield.",
        "So in every sport the average athlete costs the target price, and every group is priced for what it is likely "
        "to pay, so no sport or position is the obvious buy. What decides who wins is which athletes beat expectations.",
    ]
    X0 = E0 + 8
    for i, text in enumerate(expl):
        font(settings.cell(row=X0 + i, column=1, value=text), bold=(i == 0), italic=(i > 0))

    # ---- Balance sheet
    bal = wb.create_sheet("Balance")
    title(bal, "Balance: does any sport pay better than the others?",
          "Priced from the pricing season, paid from the test season, so this is what a league would have seen.")
    header(bal, 4, ["Sport", "Listed", "Avg starting price", "Avg season dividends per share", "Avg season dividend return",
                    "Avg weekly dividend return", "Target weekly yield", "Weekly return vs target",
                    "Best weekly return", "Worst weekly return", "Share beating target", "Missed the whole test season",
                    "Avg price change over the season"])
    for i, sp in enumerate(SPORTS):
        R, k, rng = 5 + i, sp["key"], sp["rng"]
        lst = f"{k}!{rng('listed')},1"
        f = [k, f"=COUNTIF({lst})", f"=AVERAGEIFS({k}!{rng('price')},{lst})", f"=AVERAGEIFS({k}!{rng('div')},{lst})",
             f"=AVERAGEIFS({k}!{rng('ret')},{lst})", f"=AVERAGEIFS({k}!{rng('wkret')},{lst})", "=Settings!$B$6",
             f"=F{R}/G{R}", f"=_xlfn.MAXIFS({k}!{rng('wkret')},{lst})", f"=_xlfn.MINIFS({k}!{rng('wkret')},{lst})",
             f"=COUNTIFS({lst},{k}!{rng('wkret')},\">=\"&Settings!$B$6)/B{R}",
             f"=COUNTIFS({lst},{k}!{rng('gp2')},0)", f"=AVERAGEIFS({k}!{rng('chg')},{lst})"]
        for j, v in enumerate(f):
            cell = bal.cell(row=R, column=1 + j, value=v)
            font(cell, bold=(j == 0), color=GREEN if j == 6 else None)
            cell.number_format = [None, "0", MONEY, MONEY, PCT, PCT2, PCT2, "0%", PCT2, PCT2, PCT, "0", PCT][j] or "General"
    for col_i, w in zip(range(1, 14), (9, 8, 11, 13, 13, 13, 11, 11, 11, 11, 11, 12, 13)):
        bal.column_dimensions[L(col_i)].width = w
    bal.row_dimensions[4].height = 58

    # By position group, then by position. Python finds which positions are listed under the default settings.
    font(bal.cell(row=10, column=1, value="By position group"), bold=True, size=11)
    header(bal, 11, ["Group", "Sport", "Listed", "Avg starting price", "Avg weekly dividend return",
                     "Weekly return vs target"])
    for i, (g, sport, *_rest) in enumerate(GROUPS):
        R = 12 + i
        sp = next(x for x in SPORTS if x["key"] == sport)
        rng = sp["rng"]
        lst = f"{sport}!{rng('listed')},1,{sport}!{rng('group')},\"{g}\""
        vals = [g, sport, f"=COUNTIFS({lst})", f"=IFERROR(AVERAGEIFS({sport}!{rng('price')},{lst}),\"\")",
                f"=IFERROR(AVERAGEIFS({sport}!{rng('wkret')},{lst}),\"\")", f"=IFERROR(E{R}/Settings!$B$6,\"\")"]
        for j, v in enumerate(vals):
            cell = bal.cell(row=R, column=1 + j, value=v)
            font(cell, bold=(j == 0))
            cell.number_format = [None, None, "0", MONEY, PCT2, "0%"][j] or "General"
    group_end = 12 + len(GROUPS) - 1

    P0 = group_end + 3
    font(bal.cell(row=P0, column=1, value="By position (positions present under the default settings)"), bold=True,
         size=11)
    header(bal, P0 + 1, ["Sport", "Pos", "Listed", "Avg starting price", "Avg weekly dividend return",
                         "Weekly return vs target"])
    R = P0 + 2
    for sp, (key, rows, _) in zip(SPORTS, data):
        elig = [r for r in rows if float(r["gp"]) >= sp["min_gp"]][:sp["listed"]]
        positions = sorted({r["pos"] for r in elig})
        rng = sp["rng"]
        for p in positions:
            lst = f"{key}!{rng('listed')},1,{key}!{rng('pos')},\"{p}\""
            vals = [key, p, f"=COUNTIFS({lst})", f"=IFERROR(AVERAGEIFS({key}!{rng('price')},{lst}),\"\")",
                    f"=IFERROR(AVERAGEIFS({key}!{rng('wkret')},{lst}),\"\")", f"=IFERROR(E{R}/Settings!$B$6,\"\")"]
            for j, v in enumerate(vals):
                cell = bal.cell(row=R, column=1 + j, value=v)
                font(cell)
                cell.number_format = [None, None, "0", MONEY, PCT2, "0%"][j] or "General"
            R += 1
    pos_end = R - 1
    font(bal.cell(row=R + 1, column=1, value="How to read this:"), bold=True)
    for i, text in enumerate([
        "Weekly return vs target of 100% means a sport or group paid exactly what its prices promised.",
        "The lean and repeat factors on Settings were set from these same seasons plus the year before, so this sheet "
        "flatters them a little. The honest test, setting them on one pair of seasons and checking on the other, is in "
        "the Evidence table on Settings.",
        "What matters for balance is that sports and groups land close to each other. If one is clearly higher, raise "
        "its repeat factor (its prices go up) and watch this table move.",
    ]):
        font(bal.cell(row=R + 2 + i, column=1, value=text), italic=True)

    chart = BarChart()
    chart.type = "col"
    chart.title = "Weekly dividend return vs target, by sport"
    chart.y_axis.title = "Share of target paid"
    chart.y_axis.numFmt = "0%"
    chart.add_data(Reference(bal, min_col=8, min_row=4, max_row=7), titles_from_data=True)
    chart.set_categories(Reference(bal, min_col=1, min_row=5, max_row=7))
    chart.legend = None
    chart.height, chart.width = 7, 13
    bal.add_chart(chart, "H10")

    gchart = BarChart()
    gchart.type = "col"
    gchart.title = "Weekly dividend return vs target, by position group"
    gchart.y_axis.title = "Share of target paid"
    gchart.y_axis.numFmt = "0%"
    gchart.add_data(Reference(bal, min_col=6, min_row=11, max_row=group_end), titles_from_data=True)
    gchart.set_categories(Reference(bal, min_col=1, min_row=12, max_row=group_end))
    gchart.legend = None
    gchart.height, gchart.width = 7, 13
    bal.add_chart(gchart, "H25")

    # ---- Market maker sheet
    mm = wb.create_sheet("Market Maker")
    title(mm, "Market maker: the game's own trader",
          "It always quotes a buy and a sell price around fair value, and leans its prices on how many shares the "
          "league holds.")
    mm_in = [(4, "Buy-sell gap (spread)", 0.04, PCT, "Gap between the price players buy at and sell at. Stops flipping."),
             (5, "Price lean per step of league holdings", 0.01, PCT, "Each step of shares the league holds lifts the "
              "price this much; selling lowers it."),
             (6, "Shares per step", 100, "0", "How many shares make one step."),
             (7, "Example fair value", 50, MONEY, "Any athlete's fair value; the tables below scale with it.")]
    for r, label, val, fmt, note in mm_in:
        font(mm.cell(row=r, column=1, value=label))
        c = mm.cell(row=r, column=2, value=val)
        font(c, color=BLUE)
        c.number_format = fmt
        if r in (4, 5):
            c.fill = YELLOW
        font(mm.cell(row=r, column=3, value=note), italic=True, color="555555")
    font(mm.cell(row=9, column=1, value="Quotes as league holdings change"), bold=True, size=11)
    header(mm, 10, ["Shares held by the league", "Middle price", "Players sell at (bid)", "Players buy at (ask)"])
    for i, held in enumerate(range(-500, 1001, 100)):
        R = 11 + i
        font(mm.cell(row=R, column=1, value=held), color=BLUE)
        mm.cell(row=R, column=2, value=f"=$B$7*(1+$B$5)^(A{R}/$B$6)").number_format = MONEY
        mm.cell(row=R, column=3, value=f"=B{R}*(1-$B$4/2)").number_format = MONEY
        mm.cell(row=R, column=4, value=f"=B{R}*(1+$B$4/2)").number_format = MONEY
        for col_i in (2, 3, 4):
            font(mm.cell(row=R, column=col_i))

    font(mm.cell(row=9, column=6, value="Can one player pump a price? Buy 10 steps, then sell them all back"), bold=True,
         size=11)
    header(mm, 10, ["Step", "League holds before", "Buy price paid", "Cost of step", "League holds before sale",
                    "Sell price received", "Proceeds of step"], col=6)
    for i in range(10):
        R = 11 + i
        font(mm.cell(row=R, column=6, value=i + 1))
        vals = [f"=(F{R}-1)*$B$6", f"=$B$7*(1+$B$5)^(G{R}/$B$6)*(1+$B$4/2)", f"=H{R}*$B$6",
                f"=(11-F{R})*$B$6", f"=$B$7*(1+$B$5)^(J{R}/$B$6)*(1-$B$4/2)", f"=K{R}*$B$6"]
        for j, v in enumerate(vals):
            cell = mm.cell(row=R, column=7 + j, value=v)
            font(cell)
            cell.number_format = "0" if j in (0, 3) else MONEY
    summary = [
        (23, "Shares bought", "=10*$B$6", "0"),
        (24, "Total cost", "=SUM(I11:I20)", MONEY0),
        (25, "Value at the quoted sell price right after buying", "=G23*$B$7*(1+$B$5)^(10)*(1-$B$4/2)", MONEY0),
        (26, "Paper gain if valued at the quoted sell price", "=G25/G24-1", PCT),
        (27, "Cash back from selling it all", "=SUM(L11:L20)", MONEY0),
        (28, "Real result of the round trip", "=G27/G24-1", PCT),
    ]
    for r, label, f, fmt in summary:
        font(mm.cell(row=r, column=6, value=label))
        cell = mm.cell(row=r, column=7, value=f)
        font(cell, bold=r in (26, 28))
        cell.number_format = fmt
    for i, text in enumerate([
        "What this shows: buying a pile of one athlete pushes his quoted price up, so valuing holdings at the quoted sell "
        "price would show a paper gain that disappears the moment you sell.",
        "Fix for the game: value each holding at what selling all of it would actually bring in (walk the price back "
        "down), not at the quoted price. Then pumping always shows a loss.",
    ]):
        font(mm.cell(row=30 + i, column=6, value=text), italic=True)
    for col_i, w in zip(range(1, 13), (36, 12, 12, 12, 3, 8, 12, 12, 12, 13, 12, 12)):
        mm.column_dimensions[L(col_i)].width = w
    mm.row_dimensions[10].height = 45

    # ---- Season simulation: 20 friends, buy and hold.
    sim = wb.create_sheet("Season Sim")
    title(sim, "Season sim: 20 friends buy 10 athletes each and hold",
          "Equal dollars in each pick, bought at the market maker's buy price and sold at its sell price at the end.")
    font(sim.cell(row=4, column=1, value="League length (weeks)"))
    c = sim.cell(row=4, column=2, value=18)
    font(c, color=BLUE)
    c.fill = YELLOW
    font(sim.cell(row=4, column=3, value="18 weeks is about September to January, when all three sports are playing. "
                  "Each athlete pays the share of his season's dividends that fits in the league (all of it if his "
                  "season is shorter)."), italic=True, color="555555")
    font(sim.cell(row=5, column=1, value="Picks per friend"))
    font(sim.cell(row=5, column=2, value=10), color=BLUE)
    font(sim.cell(row=6, column=1, value="Starting cash"))
    font(sim.cell(row=6, column=2, value="=Settings!$B$4"), color=GREEN)
    sim["B6"].number_format = MONEY0
    font(sim.cell(row=7, column=1, value="Market maker spread"))
    font(sim.cell(row=7, column=2, value="='Market Maker'!$B$4"), color=GREEN)
    sim["B7"].number_format = PCT

    rnd = random.Random(16)
    listed = []
    for sp, (key, rows, _) in zip(SPORTS, data):
        top = rows  # sorted by pricing-season points per game
        elig = [r for r in top if float(r["gp"]) >= sp["min_gp"]][:sp["listed"]]
        for rank, r in enumerate(elig):
            listed.append((key, tickers[(key, r["id"])], rank / len(elig)))
    by_sport = {k: [t for t in listed if t[0] == k] for k in ("NFL", "NBA", "NHL")}
    stars = sorted(listed, key=lambda t: t[2])[:60]
    cheap = sorted(listed, key=lambda t: -t[2])[:90]
    strategies = (["All NFL"] * 3 + ["All NBA"] * 3 + ["All NHL"] * 3 + ["Stars only"] * 3 + ["Bargains only"] * 3
                  + ["Mixed"] * 5)
    pools = {"All NFL": by_sport["NFL"], "All NBA": by_sport["NBA"], "All NHL": by_sport["NHL"], "Stars only": stars,
             "Bargains only": cheap, "Mixed": listed}

    H0 = 10
    header(sim, H0, ["Friend", "Strategy", "Sport", "Ticker", "Athlete", "Fair value at start", "Buy price",
                     "Shares", "Cost", "League dividends per share", "Dividends", "End fair value", "Sell price",
                     "End value of shares"])
    R = H0 + 1
    for f_i, strat in enumerate(strategies):
        for sport, tick, _ in rnd.sample(pools[strat], 10):
            sp = next(s for s in SPORTS if s["key"] == sport)
            rng, k = sp["rng"], sport
            look = lambda name: f"INDEX({k}!{rng(name)},MATCH($D{R},{k}!{rng('ticker')},0))"
            vals = [f"Friend {f_i + 1}", strat, sport, tick, f"=IFERROR({look('name')},\"not found\")",
                    f"=IFERROR({look('price')}*1,0)",
                    f"=F{R}*(1+$B$7)",
                    f"=IF(G{R}>0,INT($B$6/$B$5/G{R}),0)",
                    f"=H{R}*G{R}",
                    f"=IFERROR({look('div')}*MIN($B$4,Settings!$B${sp['row']})/Settings!$B${sp['row']},0)",
                    f"=H{R}*J{R}",
                    f"=IFERROR({look('endfv')}*1,0)",
                    f"=L{R}*(1-$B$7)",
                    f"=H{R}*M{R}"]
            for j, v in enumerate(vals):
                cell = sim.cell(row=R, column=1 + j, value=v)
                font(cell, color=BLUE if j in (0, 1, 2, 3) else None)
                cell.number_format = [None, None, None, None, None, MONEY, MONEY, "#,##0", MONEY0, MONEY, MONEY0,
                                      MONEY, MONEY, MONEY0][j] or "General"
            R += 1
    hold_end = R - 1
    hr = lambda col: f"${col}${H0 + 1}:${col}${hold_end}"

    # Leaderboard beside the holdings
    LC = 16
    font(sim.cell(row=9, column=LC, value="Leaderboard"), bold=True, size=11)
    header(sim, H0, ["Friend", "Strategy", "Cash left", "Dividends", "Shares worth", "Net worth", "Return", "Rank"],
           col=LC)
    for i, strat in enumerate(strategies):
        R = H0 + 1 + i
        fr = f"{L(LC)}{R}"
        vals = [f"Friend {i + 1}", strat, f"=$B$6-SUMIF({hr('A')},{fr},{hr('I')})",
                f"=SUMIF({hr('A')},{fr},{hr('K')})", f"=SUMIF({hr('A')},{fr},{hr('N')})",
                f"={L(LC + 2)}{R}+{L(LC + 3)}{R}+{L(LC + 4)}{R}", f"={L(LC + 5)}{R}/$B$6-1",
                f"=RANK({L(LC + 5)}{R},${L(LC + 5)}${H0 + 1}:${L(LC + 5)}${H0 + 20})"]
        for j, v in enumerate(vals):
            cell = sim.cell(row=R, column=LC + j, value=v)
            font(cell)
            cell.number_format = [None, None, MONEY0, MONEY0, MONEY0, MONEY0, PCT, "0"][j] or "General"
    lb = lambda off: f"${L(LC + off)}${H0 + 1}:${L(LC + off)}${H0 + 20}"
    R = H0 + 23
    font(sim.cell(row=R, column=LC, value="Spread of results"), bold=True, size=11)
    for i, (label, f, fmt) in enumerate([
        ("Best return", f"=MAX({lb(6)})", PCT), ("Median return", f"=MEDIAN({lb(6)})", PCT),
        ("Worst return", f"=MIN({lb(6)})", PCT), ("Gap between best and worst", f"=MAX({lb(6)})-MIN({lb(6)})", PCT),
        ("Dividends received, as share of all starting cash", f"=SUM({lb(3)})/(20*$B$6)", PCT)]):
        font(sim.cell(row=R + 1 + i, column=LC, value=label))
        cell = sim.cell(row=R + 1 + i, column=LC + 2, value=f)
        font(cell)
        cell.number_format = fmt
    R += 8
    font(sim.cell(row=R, column=LC, value="Average return by strategy"), bold=True, size=11)
    for i, strat in enumerate(["All NFL", "All NBA", "All NHL", "Stars only", "Bargains only", "Mixed"]):
        font(sim.cell(row=R + 1 + i, column=LC, value=strat))
        cell = sim.cell(row=R + 1 + i, column=LC + 2, value=f"=AVERAGEIF({lb(1)},\"{strat}\",{lb(6)})")
        font(cell)
        cell.number_format = PCT
    font(sim.cell(row=R + 8, column=LC, value="Prices here only move with each athlete's performance; real players "
                  "trading will move them more."), italic=True)
    sim.freeze_panes = sim.cell(row=H0 + 1, column=1)
    for col_i, w in enumerate((9, 13, 6, 8, 22, 11, 10, 8, 10, 11, 10, 11, 10, 11, 2, 9, 13, 11, 11, 11, 11, 9, 6), 1):
        sim.column_dimensions[L(col_i)].width = w
    sim.row_dimensions[H0].height = 45

    # ---- Read Me
    title(readme, "Stat Street economy workbook", "Milestone 0. Built 2026-10-16, position groups added 2026-10-17. Data: ESPN's public stats feed.")
    lines = [
        ("What this is", True),
        ("A model of the game's money: how athletes are priced, how much they pay in dividends, and whether any sport or "
         "strategy is an obvious winner. Prices are set from one season's stats and dividends paid from the next "
         "season's, so it shows what a real league would have experienced.", False),
        ("", False),
        ("How to use it", True),
        ("Change the blue cells. Yellow cells are the main levers. Everything else is a formula and updates on its own.", False),
        ("Start with Settings (cash, target price, weekly yield, how many athletes are listed), then look at Balance "
         "and Season Sim to see the effect.", False),
        ("", False),
        ("The sheets", True),
        ("Settings: the economy's levers, the position groups (lean toward average and repeat factor), the evidence "
         "for them, and how a price is worked out.", False),
        ("Scoring: fantasy points per stat for each sport.", False),
        ("NFL, NBA, NHL: every athlete, his stats in both seasons, whether he's listed, his starting price, the dividends "
         "he would have paid, and his end-of-season fair value. Filter on 'Listed (1=yes)' to see only tradeable athletes.",
         False),
        ("Balance: average dividend return per sport, position group and position, against the target.", False),
        ("Market Maker: how the game's own trader quotes prices, and a test of whether one player can pump a price.", False),
        ("Season Sim: 20 friends with different strategies buy and hold for a season. Who wins, and by how much?", False),
        ("", False),
        ("Colour key", True),
        ("Blue text = input you can change. Yellow fill = key lever. Black = formula. Green = pulled from another sheet.",
         False),
        ("", False),
        ("Data notes", True),
        ("Source: ESPN's public stats feed (site.web.api.espn.com), regular seasons only. NFL priced from 2024 and tested "
         "on 2025; NBA and NHL priced from 2024-25 and tested on 2025-26. The script tools/fetch_season_stats.py "
         "downloads them again. NFL 2023 and NBA/NHL 2023-24 are used only by tools/calibrate.py, which sets the "
         "position-group factors.", False),
        ("ESPN's NFL list leaves out players who weren't 'qualified' (often injured), so the top 200 NFL players missing "
         "from 2025 were looked up one by one. A test-season row of zeros means the athlete didn't play that season.",
         False),
        ("Athletes who switched teams show their pricing-season team. Rookies in the test season aren't here: in the game "
         "they would arrive as mid-season IPOs.", False),
    ]
    for i, (text, bold) in enumerate(lines):
        cell = readme.cell(row=4 + i, column=1, value=text)
        font(cell, bold=bold, size=11 if bold else 10)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    readme.column_dimensions["A"].width = 120

    wb.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
