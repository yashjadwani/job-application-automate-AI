"""Fixed eval cases: one synthetic CV, three contrasting JDs.

Frozen on purpose — the value of an eval is comparing runs over time, which
only works when the inputs never change. Add cases; don't edit existing ones.
"""

CV = {
    "sections": [
        {"id": "sec_0", "title": "Experience — Data Analyst, Retail Co (2021–2024)",
         "bullets": [
             {"index": 0, "text": "Built weekly sales dashboards in Power BI used by 40 store managers"},
             {"index": 1, "text": "Wrote SQL pipelines cleaning 2M+ transaction rows per month"},
             {"index": 2, "text": "Automated stock reporting in Python, saving 6 hours per week"}]},
        {"id": "sec_1", "title": "Experience — Junior Analyst, Fintech Ltd (2019–2021)",
         "bullets": [
             {"index": 0, "text": "Produced monthly churn reports for the product team"},
             {"index": 1, "text": "Maintained Excel models for customer lifetime value"}]},
        {"id": "sec_2", "title": "Projects",
         "bullets": [
             {"index": 0, "text": "Kaggle: top 15% in a demand-forecasting competition using scikit-learn"}]},
    ],
}

PROFILE = {
    "bio": "Data analyst with 5 years across retail and fintech, strong SQL and "
           "Python, moving toward analytics engineering.",
    "skills": ["SQL", "Python", "Power BI", "pandas", "scikit-learn", "Excel"],
    "additional_context": "Prefers remote-first roles.",
}

CASES = [
    {
        "id": "analytics_engineer",
        "company": "Streamly",
        "jd": """Analytics Engineer — Streamly (remote)
We're looking for an analytics engineer to own our dbt models and warehouse.
You'll build and maintain data models in dbt on Snowflake, write robust SQL,
partner with product analysts, and introduce testing and CI for our
transformations. Nice to have: Python, Airflow, dashboarding experience
(Looker or Power BI), and a track record of automating manual reporting.""",
    },
    {
        "id": "senior_data_analyst",
        "company": "HealthBridge",
        "jd": """Senior Data Analyst — HealthBridge
Join our healthcare analytics team. You will design KPI dashboards for
clinical operations, write complex SQL against Postgres, run cohort and
churn analyses, and present findings to non-technical stakeholders.
Requirements: 4+ years analytics experience, expert SQL, strong
visualisation skills, stakeholder communication. Bonus: Python, healthcare
data (HL7/FHIR), experiment design.""",
    },
    {
        "id": "ml_engineer_stretch",  # deliberate stretch: tests honesty on gaps
        "company": "VisionForge",
        "jd": """Machine Learning Engineer — VisionForge
Build and deploy computer-vision models for manufacturing QA. You'll train
PyTorch models, own the serving stack (FastAPI, Docker, Kubernetes), design
data pipelines for image ingestion, and monitor models in production.
Requirements: strong Python, PyTorch or TensorFlow, MLOps experience,
Kubernetes, cloud (AWS/GCP). This is a hands-on production ML role.""",
    },
]
