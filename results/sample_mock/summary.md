# Balagan resilience summary

| Topology | none | crash | byzantine |
|---|---|---|---|
| flat | 100% (n=8) | 100% (n=8) | 100% (n=8) |
| hierarchical | 100% (n=8) | 75% (n=8) | 100% (n=8) |
| ring | 100% (n=8) | 88% (n=8) | 88% (n=8) |

- Trials: 72 | trial-level errors: 0
- LLM calls: 448 | total tokens: 18816

Accuracy = share of trials where the mesh's collective decision matched ground truth. An undecided mesh scores as incorrect.
