# Architecture

## Layers

| Layer | Location | Responsibility |
|---|---|---|
| IBM Bob core | `rgc/` | Analyze workspace, deploy graph, five checkers, citations, human gate |
| Platform API | `releasegraph/` | Turns Bob’s outputs into releases, graph, readiness, incidents, Fix PRs, Copilot tools |
| Web UI | `web/` | The eight-step developer workflow as pages |
| Sample orgs | `demo/`, `fixtures/` | Ecommerce + streaming + org YAML for the hackathon loop |

## Agentic loop (Bob capabilities → product)

```
1 Analyze repo     Readiness scan / rgc check --workspace
2 Dependencies     Release Graph (Kahn sort, closure, cycles)
3 Risky changes    Checkers + risk engine
4 Tests            tests/ (Bob-authored) + playwright_map
5 Release review   Releases + deploy gate + Copilot tools
6 Readiness        GO/NO-GO checklist + citations
7 Fixes            Fix PRs (file/line/engine fix); human applies
8 Re-check         Re-scan; tickets close only if finding is gone
        └── back to 3 if anything remains
```

No database server. Demo state is in-process memory. Verdicts stay in `rgc`; the UI never invents findings.

## IBM Bob

The `rgc` suite was implemented with IBM Bob 2.0 (execution plan, org scan, generic org config, gate, CLI). ReleaseGraph Copilot is the product surface on that core. See the README section **Is the hackathon workflow depicted?**
