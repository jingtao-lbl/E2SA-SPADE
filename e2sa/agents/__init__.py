"""E2SA specialist sub-agents.

The orchestrator drives a six-agent pipeline; each agent is one stage:

    litreview      literature review (S1)
    data_assembly  discover/retrieve/organize/harmonize/QC/post-process (S2-S6)
    ml_modeldev    ML/DL model development (S7)
    calibration    process-model calibration, bridged to A2MC (S7/S8)
    validation     independent held-out + external-product validation, UQ (S8)
    model_evolve   diagnose -> modify code -> verify -> PR; loop (S8/S10)
    report         figures, maps, tables, draft memo (S9)

Each agent lives in its own subpackage; import the one you need (some pull heavy
optional dependencies). Design: `docs/design/11_agent_pipeline.md`.
"""
