# GhostData-Team-Madira-

AI-powered deletion-audit agent that determines whether a person’s data was actually deleted, identifies records and processes that still expose or can recreate that data, and produces an ordered, evidence-backed plan to finish or verify deletion.

## Overview

For each deletion request, decide whether the person's data is really gone, and produce an ordered plan (findings, fixes, checks).

## Architecture

- **Engine** (`ghost/`): Plain Python rules (evidence -> identity -> state -> timing -> policy -> plan)
- **AI Layer** (`ghost/agent.py`, `ghost/agent_tools.py`): OpenAI model + 8 read-only tools investigating independently
- **Gate**: Validates and reconciles model plan vs engine canonical plan
- **Viz** (`viz/`): Visualizer and inspection utilities

