"""Score the RAG. Usage: python -m scripts.eval [--answers] [--verbose]

Retrieval: is the expected source among the passages sent to the model, and does any of them contain
the key fact? Answers (--answers): does the generated answer contain the key fact, and does the
grounding check pass? Off-topic cases ("none") must retrieve nothing, so the model is never asked.
Relationship cases need facts from two different places in a document to be retrieved together."""
import sys

from src import config
from src.rag import ask, gather_context, build_passages

HB = "The Employee Handbook FY 2026-27 (1).pdf"
DP = "data-pipeline.md"
HP = "(Book 7) Harry Potter And The Deathly Hallows.pdf"

# (question, expected source or None, [facts: any one must appear, case-insensitive])
CASES = [
    # data pipeline (markdown)
    ("Which EDI database does TV2 / McKesson data go to?", DP, ["EDI DB 3", "MYSQL_DB_3"]),
    ("How does the pipeline deduplicate claims?", DP, ["SHA-256"]),
    ("Is dedup done per file or per claim?", DP, ["per-claim", "per claim"]),
    ("How old can an EDI file be before it is rejected?", DP, ["548"]),
    ("Which EDI DB is deprecated and why?", DP, ["VANT"]),
    ("How often does the Celery pick_claims_for_gi task run and how many rows per batch?", DP, ["5 min", "1,000"]),
    ("What are the row status values used in pick/copy?", DP, ["IN_PROGRESS"]),
    ("What does the ClaimPredictionPipeline export?", DP, ["api_claimsoutput"]),
    ("Which table tracks the Clearview export watermark?", DP, ["glide_data_export_status"]),
    ("Which customers use EDI_DB_4?", DP, ["AMD"]),
    # employee handbook (PDF with numbered sections and tables)
    ("How long is the probation period?", HB, ["3 months"]),
    ("How much is the referral bonus for a technical candidate with 5 to 8 years of experience?", HB, ["75,000"]),
    ("What notice period must a new employee serve?", HB, ["30 days"]),
    ("Which leaves can be taken during probation?", HB, ["Sick and Bereavement"]),
    ("What is the retention bonus after 10 years of continuous service?", HB, ["2,00,000"]),
    ("What topics does the employee handbook cover?", HB, ["LEAVE POLICY", "Leave Policy"]),
    # relationships: the answer needs two places in the document
    ("Can someone still on probation get a referral bonus, and when is it paid?", HB, ["probation"]),
    ("Who is not eligible for the referral bonus?", HB, ["not eligible"]),
    # a long novel: many near-similar passages
    ("What are the three Deathly Hallows?", HP, ["Elder Wand", "Resurrection Stone", "Cloak of Invisibility"]),
    ("Who is Bathilda Bagshot?", HP, ["Bathilda"]),
    ("What did Dumbledore leave Harry in his will?", HP, ["Snitch"]),
    # off topic: nothing may be retrieved
    ("hi", None, []),
    ("Who won the 2018 world cup?", None, []),
    ("What is the capital of France?", None, []),
    ("How do I bake a chocolate cake?", None, []),
    ("What is the current price of Apple stock?", None, []),
]


def main():
    answers = "--answers" in sys.argv
    verbose = "--verbose" in sys.argv
    src_ok = fact_ok = ans_ok = off_ok = grounded = n = a = off = 0
    for q, src, facts in CASES:
        hits = gather_context([q], config.TOP_K)
        passages = build_passages(hits, [q])
        top = hits[0] if hits else None
        shown = f"top={top['source'][:18]} p{top['page_start']} rerank={top['rerank']} cos={top['cosine']:.2f}" if top else "nothing retrieved"
        if src:
            n += 1
            s = any(p["source"] == src for p in passages)
            f = any(x.lower() in p["body"].lower() for p in passages for x in facts)
            src_ok += s
            fact_ok += f
            print(f"[{'OK ' if s else 'MISS'}|{'fact' if f else 'NOFACT'}] {q}  {shown}")
        else:
            off += 1
            clean = not hits
            off_ok += clean or q == "hi"
            print(f"[{'OFF-OK' if clean else 'LEAK'}] {q}  {shown}")
        if verbose:
            for p in passages:
                print(f"      [{p['n']}] {p['role']:7} {p['source'][:20]} p{p['page_start']} {p['section'][:60]}")
        if answers:
            ans, _ = ask(q, stream=False)
            if src:
                a += 1
                g = any(x.lower() in ans.lower() for x in facts)
                ans_ok += g
                print(f"     answer {'OK' if g else 'BAD'}: {ans[:200]!r}")
            else:
                print(f"     answer (review): {ans[:200]!r}")
    print(f"\nretrieval source@{config.TOP_K}: {src_ok}/{n}   fact in context: {fact_ok}/{n}   off-topic refused: {off_ok}/{off}", end="")
    if answers:
        print(f"   answers with the key fact: {ans_ok}/{a}", end="")
    print()


if __name__ == "__main__":
    main()
