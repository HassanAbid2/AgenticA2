from rag.requirements import clean_requirement, extract_requirements
from rag.skills import extract_skills
from rag.verify import is_claim, strip_citations, strip_unsupported, verify_claims

EVIDENCE = [
    {"evidence_id": "e1", "text": "Built a churn model with XGBoost and scikit-learn. Recall 0.82; saved $140k a year.",
     "skills": ["XGBoost", "scikit-learn"]},
    {"evidence_id": "e2", "text": "Curriculum vitae. 6 years of freelance and contract work in Python.", "skills": ["Python"]},
]


def test_requirement_extraction_and_cleaning():
    job = {"title": "x", "skills": ["dbt"], "description": "We need clean reports.\n\nRequirements:\n- Strong experience with "
           "Snowflake\n- dbt (must have)\n\nDeliverables:\n- docs"}
    reqs = extract_requirements(job)
    assert reqs[:2] == ["Snowflake", "dbt"] and "clean reports" in reqs
    assert clean_requirement("- Proven Airflow work") == "Airflow"


def test_skill_lexicon_matches_aliases_and_code():
    assert {"Next.js", "PostgreSQL", "Celery"} <= set(extract_skills("next.js app on postgres with a Celery queue"))
    assert "R" not in extract_skills("for r in rows: pass")
    assert "dbt" in extract_skills("select * from {{ ref('stg') }}", code=True)


def test_claim_detection():
    assert is_claim("I built a churn model that saved $140k.")
    assert not is_claim("I would start with a discovery call.")
    assert not is_claim("What does success look like?")
    assert not is_claim("Your team needs 3 dashboards.")


def test_fabricated_numbers_and_tools_are_unsupported():
    draft = ("I built a churn model with XGBoost that saved $140k a year [1]. "
             "I also scaled it to 9 million users with Kubernetes [1]. I have 6 years of experience [2].")
    res = {r.claim[:20]: r.label for r in verify_claims(draft, EVIDENCE)}
    labels = list(res.values())
    assert labels[1] == "unsupported"
    assert labels[0] in ("supported", "partly_supported") and labels[2] in ("supported", "partly_supported")
    cleaned = strip_unsupported(draft, verify_claims(draft, EVIDENCE))
    assert "Kubernetes" not in cleaned and "XGBoost" in cleaned


def test_citations_are_stripped_for_the_client():
    assert strip_citations("I built it [1]. Results improved [2][3].") == "I built it. Results improved."


def test_year_in_evidence_metadata_counts_and_wrong_year_does_not():
    ev = [{"evidence_id": "e", "text": "Insurance pricing model. Gini up 0.06 over the GLM.", "skills": ["XGBoost"], "date": "2022-05"}]
    ok = verify_claims("In 2022 I delivered an insurance pricing model that lifted Gini by 0.06 over the GLM [1].", ev)
    bad = verify_claims("In 2019 I delivered an insurance pricing model that lifted Gini by 0.06 [1].", ev)
    assert ok[0].label != "unsupported" and bad[0].label == "unsupported"
