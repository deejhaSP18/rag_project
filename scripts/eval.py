"""Score the RAG. Usage: python -m scripts.eval [--answers]
Retrieval: is the expected source in top-k, and does any retrieved chunk contain the key fact?
Answers (--answers): does the generated answer contain the key fact? Off-topic ("none") cases are
printed for manual review."""
import sys

from src import config
from src.rag import ask, retrieve

P = "Data-pipeline-readme.md"
# (question, expected source or None, [facts: any one must appear, case-insensitive])
CASES = [
    ("Which EDI database does TV2 / McKesson data go to?", P, ["EDI_DB_3"]),
    ("How does the pipeline deduplicate claims?", P, ["SHA-256"]),
    ("Is dedup done per file or per claim?", P, ["per claim"]),
    ("How old can an EDI file be before it is rejected?", P, ["548"]),
    ("Which EDI DB is deprecated and why?", P, ["VANT"]),
    ("How often does the Celery pick_claims_for_gi task run and how many rows per batch?", P, ["5 min", "1,000"]),
    ("What are the row status values used in pick/copy?", P, ["IN_PROGRESS"]),
    ("How often do Redshift loads run and what is the batch size?", P, ["3 minutes", "10,000"]),
    ("What happens to files that fail parsing in Tv2ToWinLoader?", P, ["Error/"]),
    ("How are rejected files reprocessed?", P, ["generate_reprocess_csv", "reprocess_files.csv"]),
    ("What does the ClaimPredictionPipeline export?", P, ["api_claimsoutput"]),
    ("Which table tracks the Clearview export watermark?", P, ["glide_data_export_status"]),
    ("What is the known gap in the third-party HIPAA EDI Windows software?", P, ["duplicate rows"]),
    ("Which customers use EDI_DB_4?", P, ["AMD"]),
    ("What are the config tables that map a customer to an EDI DB?", P, ["customerdatabaseconfig"]),
    ("What is the TSA liquids rule?", "tsa_liquids_rule.md", ["3.4"]),
    ("Do I need REAL ID to fly domestic?", "tsa_real_id.md", ["May 7, 2025", "May 2025"]),
    ("What happens if I am denied boarding due to overbooking?", "air_travel_overselling_denied_boarding_wikipedia.md", ["compensation"]),
    ("hi", None, []),
    ("Who won the 2018 world cup?", None, []),
    ("What is the capital of France?", None, []),
]


def main():
    answers = "--answers" in sys.argv
    src_ok = fact_ok = ans_ok = n = a = 0
    for q, src, facts in CASES:
        hits = retrieve(q, config.TOP_K)
        top = [(h["source"], round(1 - h["distance"], 2)) for h in hits]
        if src:
            n += 1
            s = any(h["source"] == src for h in hits)
            f = any(x.lower() in h["text"].lower() for h in hits for x in facts)
            src_ok += s; fact_ok += f
            print(f"[{'OK ' if s else 'MISS'}|{'fact' if f else 'NOFACT'}] {q}  top={top[0]}")
        else:
            print(f"[OFF] {q}  top={top[0]}")
        if answers:
            ans, _ = ask(q, stream=False)
            if src:
                a += 1
                g = any(x.lower() in ans.lower() for x in facts)
                ans_ok += g
                print(f"     answer {'OK' if g else 'BAD'}: {ans[:160]!r}")
            else:
                print(f"     answer (review): {ans[:200]!r}")
    print(f"\nretrieval source@{config.TOP_K}: {src_ok}/{n}   fact@{config.TOP_K}: {fact_ok}/{n}", end="")
    print(f"   answer fact: {ans_ok}/{a}" if answers else "")


if __name__ == "__main__":
    main()
