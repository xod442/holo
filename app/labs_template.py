"""The default 8-phase HOL production pipeline, cloned onto every new lab.

Sourced from hol.md. `estimated_hours` may be None where the source has no
estimate (Video Demo, Post-Production Acceptance). Editable in a later phase.
"""

STAGE_DEVELOPMENT = "Development"
STAGE_PRODUCTION = "Production"

PHASE_TEMPLATE = [
    {
        "stage": STAGE_DEVELOPMENT,
        "name": "Concept",
        "requires_approval": False,
        "estimated_hours": 8,
        "tasks": [
            "Topic / High-Level Overview",
            "Stakeholder Discussion",
            "Concept Review Approval",
        ],
    },
    {
        "stage": STAGE_DEVELOPMENT,
        "name": "Design",
        "requires_approval": True,
        "estimated_hours": 16,
        "tasks": [
            "Objectives",
            "Hardware & Software Requirements",
            "Automation Planning",
            "Design Review",
        ],
    },
    {
        "stage": STAGE_DEVELOPMENT,
        "name": "Develop",
        "requires_approval": True,
        "estimated_hours": 40,
        "tasks": [
            "Prototype",
            "Automation Pre-Requirements",
            "Lab Guide Development",
            "Objective Mapping and Timing",
            "Development Approval",
        ],
    },
    {
        "stage": STAGE_DEVELOPMENT,
        "name": "Video Demo",
        "requires_approval": False,
        "estimated_hours": None,
        "tasks": [
            "Record Video",
            "Publish to Tech Pro",
        ],
    },
    {
        "stage": STAGE_PRODUCTION,
        "name": "Testing & Feedback",
        "requires_approval": True,
        "estimated_hours": 80,
        "tasks": [
            "Alpha Test — TE Team",
            "Beta Testing",
            "Feedback Aggregation",
            "Implement Feedback",
            "Testing Approval",
        ],
    },
    {
        "stage": STAGE_PRODUCTION,
        "name": "Publish",
        "requires_approval": False,
        "estimated_hours": 32,
        "tasks": [
            "Digital Lab Guide",
            "Digital Workshop Catalog Update",
            "Course Documentation",
            "Publishing Approval",
        ],
    },
    {
        "stage": STAGE_PRODUCTION,
        "name": "Production",
        "requires_approval": True,
        "estimated_hours": 80,
        "tasks": [
            "vLabs Scheduler",
            "Build Scripts",
            "Automation",
            "MTP-DOCS",
            "Production Approval",
        ],
    },
    {
        "stage": STAGE_PRODUCTION,
        "name": "Post-Production Acceptance",
        "requires_approval": False,
        "estimated_hours": None,
        "tasks": [
            "Train-the-Trainer",
            "Go/No-Go (run course as it will exist in production)",
            "Course Complete",
        ],
    },
]

TOTAL_ESTIMATED_HOURS = sum(p["estimated_hours"] or 0 for p in PHASE_TEMPLATE)
