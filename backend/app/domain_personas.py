"""Static, hand-curated staff-engineer mental models per target role_category.

Deliberately NOT LLM-generated: a staff engineer's mental model shouldn't be
reinvented (and risk drifting) on every Gemini call. This is a stable
reference framework other prompts/features are grounded against.
"""
from __future__ import annotations

DOMAIN_PERSONAS: dict[str, dict] = {
    "senior_sre_devops_cloud": {
        "title": "Staff SRE / Infrastructure Engineer",
        "mental_model": (
            "Reliability is the product. Organizes everything around SLOs/error "
            "budgets, blast-radius reduction, the full incident lifecycle "
            "(detect → mitigate → root-cause → prevent), toil elimination, and "
            "capacity/cost tradeoffs. Distrusts tool-name-dropping without "
            "operational evidence behind it."
        ),
        "requirement_grouping_lens": (
            "Group by reliability concern, not by tool: 'incident response & "
            "observability', 'infra-as-code & change safety', 'capacity & cost', "
            "'security & compliance posture' — never flat tool-by-tool buckets "
            "like 'Prometheus', 'Terraform', 'AWS' as separate silos."
        ),
        "study_priorities": (
            "Depth on failure modes and real postmortem practice matters more "
            "than breadth of tool names. Someone who deeply understands ONE "
            "incident lifecycle end-to-end outperforms someone who's touched "
            "ten tools shallowly."
        ),
        "interview_lens": {
            "what_id_probe": [
                "Walk me through your worst production incident — what broke, how you found out, what you did, what changed after.",
                "How do you decide when a service needs a stricter SLO vs when 99.9% is fine?",
                "Tell me about a time you said no to a feature because of reliability risk.",
            ],
            "red_flags": [
                "Only describes tool usage, never a judgment call or tradeoff",
                "No postmortem/blameless-culture vocabulary",
                "Can't explain error budgets in their own words",
            ],
            "reference_points_if_unsure": [
                "Google SRE Book — specifically the error budgets and postmortem chapters",
                "The relevant cloud provider's own incident/postmortem framework docs",
                '"Everything fails all the time" as a baseline operating assumption to sanity-check designs against',
            ],
        },
    },
    "senior_mlops": {
        "title": "Staff MLOps Engineer",
        "mental_model": (
            "The ML lifecycle is the product, not any individual model. Organizes "
            "around the full loop — data → features → training → registry → "
            "serving → monitoring/drift → retraining — not around individual tool "
            "brand names."
        ),
        "requirement_grouping_lens": (
            "Group by lifecycle stage: 'data & feature management', 'training & "
            "experiment tracking', 'model registry & deployment', 'monitoring & "
            "drift response' — never flat tool-by-tool."
        ),
        "study_priorities": (
            "Reproducibility and drift-response maturity matter more than which "
            "specific feature store or registry brand. Understanding WHY a "
            "feature store exists (train/serve skew) matters more than "
            "memorizing any one product's API."
        ),
        "interview_lens": {
            "what_id_probe": [
                "Tell me about a model that degraded in production — how did you find out, and what did you do?",
                "How do you handle train/serve skew?",
                "Walk me through your CI/CD for a model, not just for application code.",
            ],
            "red_flags": [
                "Treats MLOps as just 'DevOps for a Jupyter notebook'",
                "No concept of drift or retraining triggers",
                "Can't distinguish a feature store from a model registry",
            ],
            "reference_points_if_unsure": [
                'Google\'s "Hidden Technical Debt in Machine Learning Systems" paper',
                "Published MLOps maturity models (Google/Microsoft both have public versions)",
                "The specific ML platform's own reference architecture docs",
            ],
        },
    },
    "senior_ai_platform": {
        "title": "Staff AI Platform Engineer",
        "mental_model": (
            "Building the paved road for AI/ML teams, not doing the AI work "
            "yourself. Organizes around what makes those teams self-sufficient: "
            "compute/GPU scheduling and multi-tenancy, data/model access "
            "governance, cost attribution, and developer experience for the "
            "platform's actual users."
        ),
        "requirement_grouping_lens": (
            "Group by platform capability: 'compute & scheduling', 'access & "
            "governance', 'cost visibility', 'developer self-service' — never by "
            "individual product name."
        ),
        "study_priorities": (
            "Platform-as-product thinking (who's the user, what's their "
            "workflow, where's the friction) matters more than knowing every "
            "GPU scheduler by name."
        ),
        "interview_lens": {
            "what_id_probe": [
                "How do you decide what to build vs buy for a platform capability?",
                "Tell me about a platform decision your users pushed back on — what did you do?",
                "How do you measure whether your platform is actually working?",
            ],
            "red_flags": [
                "Talks only about infra, never about the platform's actual users",
                "No cost-attribution or multi-tenancy story",
                "Can't articulate a build-vs-buy tradeoff they've actually made",
            ],
            "reference_points_if_unsure": [
                "Team Topologies — the platform-as-a-product framing",
                "The relevant cloud provider's GPU scheduling/multi-instance-GPU docs",
                "Published internal-platform case studies (treated as reference points, not templates to copy)",
            ],
        },
    },
    "aiops_llmops": {
        "title": "Staff AIOps/LLMOps Engineer",
        "mental_model": (
            "LLMs fail differently than traditional software — silently, "
            "plausibly, and expensively. Organizes around the LLM-specific "
            "operational loop: prompt/version management, real eval harnesses "
            '(not just "testing"), safety/guardrails, cost-per-token and '
            "latency tradeoffs, and RAG pipeline operational health."
        ),
        "requirement_grouping_lens": (
            "Group by LLMOps concern: 'evaluation & quality', 'safety & "
            "guardrails', 'cost & latency optimization', 'RAG/retrieval "
            "pipeline ops' — never by which vendor API is used."
        ),
        "study_priorities": (
            "Eval methodology (how do you know a prompt change made things "
            "better, not just different) matters far more than which LLM API "
            "a candidate has called. Zero eval discipline is a real operational "
            "risk regardless of how many models someone has integrated."
        ),
        "interview_lens": {
            "what_id_probe": [
                "How do you know if a prompt change made things better or worse, beyond eyeballing outputs?",
                "Tell me about a hallucination or safety incident you handled — what changed after?",
                "How do you think about cost-per-request tradeoffs when choosing a model tier?",
            ],
            "red_flags": [
                "No eval harness or golden-dataset concept at all",
                "Treats prompt changes as not needing review or testing",
                "No answer for what happens when the model is wrong in production",
            ],
            "reference_points_if_unsure": [
                "The relevant model provider's own published safety/eval documentation",
                "Public eval frameworks, treated as reference points rather than gospel",
                "Published LLM incident postmortems from companies that share them",
            ],
        },
    },
    "platform_engineering": {
        "title": "Staff Platform Engineer",
        "mental_model": (
            "The internal developer platform is the product; developers are the "
            "customers. Organizes around developer experience: golden paths, "
            "self-service provisioning, abstraction layer design, and adoption/"
            "friction — not around the specific tools wired underneath."
        ),
        "requirement_grouping_lens": (
            "Group by developer-experience concern: 'self-service & golden "
            "paths', 'abstraction & tooling design', 'adoption & DX metrics' — "
            "never tool-by-tool."
        ),
        "study_priorities": (
            "Judgment about where to abstract vs where to expose complexity "
            "matters more than which specific internal-developer-platform tool "
            "a candidate has used."
        ),
        "interview_lens": {
            "what_id_probe": [
                "Tell me about an abstraction you built that developers hated, and what you learned.",
                "How do you decide what belongs in the golden path vs what stays flexible?",
                "How do you measure whether your platform is actually reducing toil?",
            ],
            "red_flags": [
                "Only describes tools wired together, no story about developer adoption or pushback",
                "No concept of a golden path or paved-road philosophy",
                "Can't describe a platform decision that was later reversed, and why",
            ],
            "reference_points_if_unsure": [
                "Team Topologies",
                "The CNCF platform engineering maturity model",
                "Published platform engineering origin-story case studies, as reference points",
            ],
        },
    },
}
# "related_adjacent" / "unrelated" JDs get no persona injection — the generic
# prompts already in place stay as the fallback for those.
